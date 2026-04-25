"""RuleRunner：规则引擎的编排层。

流水线：
    FeatureExtractor.extract(symbol, tf)
      → 4 个 snapshot 级 scorer  (accumulation / distribution / breakout / reversal)
      → 6 个 module builder
      → TimelineEvent 聚合
      → DashboardHealth 映射
      → DashboardSnapshot（一次性组装）

本类只做编排，不做缓存，不做调度。
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from backend.core.exceptions import NoDataError
from backend.models import (
    CapabilityScore as CapabilityScoreDTO,
    DashboardHealth,
    DashboardSnapshot,
    TimelineEvent,
)
from backend.storage.db import Database

from .features import FeatureExtractor, FeatureSnapshot

if TYPE_CHECKING:
    # 懒引用，避免循环：backend.ai → backend.rules.features → ...
    from backend.ai.observer import AIObserver

logger = logging.getLogger("rules.runner")
from .modules import (
    build_dashboard_cards,
    build_hero,
    build_key_levels,
    build_liquidity_map,
    build_main_force_radar,
    build_participation,
    build_phase_state,
    build_trade_plan,
)
from .scoring import CapabilityScore as CapabilityScoreInternal
from .scoring import (
    score_accumulation,
    score_breakout,
    score_distribution,
    score_reversal,
)


# NoDataError 从 backend.core.exceptions 统一导入（继承 MMError → API 层自动 404）。
# 下方 re-export 保证旧代码 ``from backend.rules.runner import NoDataError`` 继续工作。


# ─── TimelineEvent 聚合 ──────────────────────────────────


def _build_timeline(snap: FeatureSnapshot, *, limit: int = 8) -> list[TimelineEvent]:
    """把 snapshot 里 5 类原子事件按 ts 聚合，挑最近 ``limit`` 条。"""
    events: list[TimelineEvent] = []

    # 1) sweep 最近一次（sweep_count_recent 只是数量；具体条只保留了 last）
    if snap.sweep_last is not None:
        sw = snap.sweep_last
        dir_cn = "上方猎杀（扫空头）" if sw.type == "bearish_sweep" else "下方猎杀（扫多头）"
        events.append(
            TimelineEvent(
                ts=sw.ts, kind="sweep",
                headline=f"{dir_cn} @ {sw.price}",
                detail=(
                    f"type={sw.type} volume={round(sw.volume, 2)} "
                    f"事件窗累计 {snap.sweep_count_recent} 次"
                ),
                severity="warning",
            )
        )

    # 2) 鲸鱼共振（使用 resonance_recent 列表）
    for ev in snap.resonance_recent:
        dir_cn = "鲸鱼共振买" if ev.direction == "buy" else "鲸鱼共振卖"
        events.append(
            TimelineEvent(
                ts=ev.ts, kind="resonance",
                headline=f"{dir_cn} @ {round(ev.price, 2)}",
                detail=f"direction={ev.direction} count={ev.count} exchanges={','.join(ev.exchanges)}",
                severity="info",
            )
        )

    # 3) 能量条极端
    if snap.power_imbalance_last is not None and snap.power_imbalance_last.ratio >= 1.5:
        pi = snap.power_imbalance_last
        events.append(
            TimelineEvent(
                ts=pi.ts, kind="power_imbalance",
                headline=f"能量条 {round(pi.ratio, 2)}x 放大",
                detail=f"buy={round(pi.buy_vol, 2)} sell={round(pi.sell_vol, 2)}",
                severity="info",
            )
        )

    # 4) 趋势耗竭警戒
    if snap.trend_exhaustion_last is not None and snap.trend_exhaustion_last.exhaustion >= 5:
        te = snap.trend_exhaustion_last
        sev = "alert" if te.exhaustion >= 7 else "warning"
        events.append(
            TimelineEvent(
                ts=te.ts, kind="exhaustion",
                headline=f"{te.type} 耗竭 {te.exhaustion}",
                detail=f"type={te.type} exhaustion={te.exhaustion}",
                severity=sev,
            )
        )

    # 5) 关键位穿越（anchor_ts 当时间）
    if snap.just_broke_resistance:
        events.append(
            TimelineEvent(
                ts=snap.anchor_ts, kind="breakout",
                headline="刚穿越阻力",
                detail=f"price={snap.last_price}"
                + (f" nearest_r={snap.nearest_resistance_price}" if snap.nearest_resistance_price else ""),
                severity="warning",
            )
        )
    if snap.just_broke_support:
        events.append(
            TimelineEvent(
                ts=snap.anchor_ts, kind="breakdown",
                headline="刚跌破支撑",
                detail=f"price={snap.last_price}"
                + (f" nearest_s={snap.nearest_support_price}" if snap.nearest_support_price else ""),
                severity="warning",
            )
        )

    events.sort(key=lambda e: e.ts, reverse=True)
    return events[:limit]


# ─── DashboardHealth 映射 ──────────────────────────────────


def _build_health(
    snap: FeatureSnapshot, *, now_ms: int | None = None
) -> DashboardHealth:
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    stale_seconds = max(0, (now - snap.anchor_ts) // 1000)
    warnings = [f"{t} 陈旧" for t in snap.stale_tables]
    return DashboardHealth(
        fresh=len(snap.stale_tables) == 0,
        last_collector_ts=snap.anchor_ts,
        stale_seconds=int(stale_seconds),
        warnings=warnings,
    )


# ─── capability_scores 类型转换 ──────────────────────────────────


def _to_capability_dto(cap: CapabilityScoreInternal) -> CapabilityScoreDTO:
    total = len(cap.evidence) or 1
    hits = sum(1 for e in cap.evidence if e.hit)
    confidence = round(hits / total, 2)
    evidences: list[str] = []
    for e in cap.evidence:
        if not e.hit:
            continue
        val = "" if e.value is None else f"={e.value}"
        evidences.append(f"{e.label}{val}")
    return CapabilityScoreDTO(
        name=cap.name,
        score=int(round(cap.score)),
        confidence=confidence,
        evidences=evidences,
        notes=f"band={cap.band}  dir={cap.direction}",
    )


# ─── RuleRunner ──────────────────────────────────


class RuleRunner:
    """规则引擎编排器。

    用法::

        runner = RuleRunner(db, rules_defaults)
        snap = await runner.run("BTC", "30m")
    """

    def __init__(
        self,
        db: Database,
        config: dict[str, Any] | None = None,
        *,
        feature_extractor: FeatureExtractor | None = None,
        ai_observer: "AIObserver | None" = None,
    ) -> None:
        self._db = db
        self._config = config or {}
        self._ext = feature_extractor or FeatureExtractor(db, config=self._config)
        # AI 观察器（V1.1 · Phase 9）：可选注入；为空时主流程不受影响
        self._ai_observer = ai_observer

    def set_ai_observer(self, observer: "AIObserver | None") -> None:
        """运行时注入 observer（lifespan 可在其他依赖就绪后再注入）。"""
        self._ai_observer = observer

    async def run(self, symbol: str, tf: str) -> DashboardSnapshot:
        """跑完整流水线，返回 DashboardSnapshot。

        Raises:
            NoDataError: FeatureExtractor 无法产出 snapshot 时
        """
        snap = await self._ext.extract(symbol, tf)
        if snap is None:
            raise NoDataError(
                f"{symbol}/{tf} 无可用数据",
                detail={"symbol": symbol, "tf": tf},
            )
        dashboard = self._assemble(snap)
        # AI 观察 V1.1（3 层 agent）已在 dashboard UI 移除并不再被前端消费；
        # 后端保留 ``/api/ai/observations/run`` 手动 API 入口（供历史排查），
        # 但流水线不再自动调度，避免持续刷 schema 验证失败 / 浪费 token。
        # 如需恢复，去掉下方 short-circuit 即可。
        return dashboard

    def _assemble(self, snap: FeatureSnapshot) -> DashboardSnapshot:
        cfg = self._config

        # 1) 4 个 snapshot 级 capability
        caps_internal = {
            "accumulation": score_accumulation(snap, cfg),
            "distribution": score_distribution(snap, cfg),
            "breakout": score_breakout(snap, cfg),
            "reversal": score_reversal(snap, cfg),
        }

        # 2) 6 个模块
        behavior = build_main_force_radar(snap, caps_internal, cfg)
        participation = build_participation(snap, cfg)
        phase = build_phase_state(
            snap, caps_internal, cfg, participation_level=participation.level
        )
        levels = build_key_levels(snap, cfg)
        liquidity = build_liquidity_map(snap, cfg)
        plans = build_trade_plan(snap, caps_internal, phase, participation, cfg)
        choch_alert_bars = int(
            (cfg or {}).get("hero", {}).get("choch_alert_bars", 3)
        )
        hero = build_hero(
            behavior=behavior, phase=phase, participation=participation,
            levels=levels, liquidity=liquidity, plans=plans,
            choch_latest=snap.choch_latest,
            choch_alert_bars=choch_alert_bars,
        )

        # 3) timeline / capability_scores / health
        timeline = _build_timeline(snap)
        cap_dtos = [_to_capability_dto(caps_internal[n]) for n in
                    ("accumulation", "distribution", "breakout", "reversal")]
        health = _build_health(snap)

        # 4) V1.1 · 数字化白话卡（view → card 直出）
        cards = build_dashboard_cards(snap, cfg)

        return DashboardSnapshot(
            timestamp=snap.anchor_ts,
            symbol=snap.symbol,
            tf=snap.tf,
            current_price=snap.last_price,
            hero=hero,
            behavior=behavior,
            phase=phase,
            participation=participation,
            levels=levels,
            liquidity=liquidity,
            plans=plans,
            ai_observations=[],   # V1 留空，V1.1 由 AI 观察模式注入
            capability_scores=cap_dtos,
            recent_events=timeline,
            health=health,
            cards=cards,
        )


__all__ = ["NoDataError", "RuleRunner"]
