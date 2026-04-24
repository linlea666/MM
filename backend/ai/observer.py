"""V1.1 · Phase 9 · AI 观察 Observer（统一模型编排器）。

核心职责：
1. **输入映射**：从 ``FeatureSnapshot`` 构造 ``AIObserverInput``；
2. **触发控制**：节流 + 冷却 + "关键事件强制刷新"（CHoCH / phase_switch）；
3. **三层串行/并行调用**：
     - L1 TrendClassifier + L2 MoneyFlowReader **并行**；
     - L3 TradePlanner 条件触发（不默认跑，见下方阈值）；
     - **三层共用** ``ObserverSettings.model_tier`` 选定的模型（默认 flash）。
4. **降级与回退**：任一层失败 → ``AgentResult.error`` 透传，不影响其它层；
5. **持久化**：成功组装的 ``AIObserverFeedItem`` 交给 ``AIObservationStore``。

L3 触发条件（V1.1 统一模型下仍生效）：
- ``TrendLayerOut.confidence ≥ auto_trend_confidence`` **且** ``MoneyFlowLayerOut.confidence ≥ auto_money_flow_confidence``；
- **且** ``TrendLayerOut.direction ≠ 'neutral'`` 且 ``MoneyFlowLayerOut.dominant_side ≠ 'neutral'``；
- 或者 caller 显式 ``force_trade_plan=True``（对应前端"求交易计划"按钮）。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from backend.ai.agents import (
    AgentResult,
    run_money_flow_agent,
    run_trade_plan_agent,
    run_trend_agent,
)
from backend.ai.providers.base import LLMProvider
from backend.ai.schemas import (
    AIObserverFeedItem,
    AIObserverInput,
    AIObserverSummary,
    MoneyFlowLayerOut,
    SummaryBandPreview,
    TradePlanLayerOut,
    TrendLayerOut,
)
from backend.ai.storage import AIObservationStore
from backend.rules.features import FeatureSnapshot

logger = logging.getLogger("ai.observer")


# ════════════════════════════════════════════════════════════════════
# 配置聚合（不与 core.config.AIConfig 同步 —— observer 只用到子集）
# ════════════════════════════════════════════════════════════════════


@dataclass
class ObserverSettings:
    """Observer 运行参数。由 RulesConfigService 注入，默认值保守。

    V1.1 · 统一模型：``model_tier`` 决定三层全部用哪个 tier（flash/pro）。
    observer 不再硬编码"L1/L2 flash、L3 pro"；但仍保留 timeout/temperature
    两套（按当前 tier 自动选对应的那组参数）。
    """

    enabled: bool = False
    min_interval_seconds: int = 180              # 最小触发间隔（防止每 tick 都调）
    cache_ttl_seconds: int = 300                 # 同 anchor_ts 缓存窗

    # 模型策略（统一）
    model_tier: str = "flash"                    # "flash" | "pro"
    thinking_enabled: bool = False               # 思维模式开关（与 json_object 互斥，provider 层自动处理）

    # L3 触发门槛
    auto_trade_plan: bool = True                 # 默认允许 observer 自动升级 Layer 3
    auto_trend_confidence: float = 0.70
    auto_money_flow_confidence: float = 0.60

    # 并发 / 超时 / 温度（按 tier 自动选 flash 或 pro 那组）
    max_concurrent: int = 1
    timeout_s_flash: float = 20.0
    timeout_s_pro: float = 45.0
    temperature_flash: float = 0.2
    temperature_pro: float = 0.15

    def current_timeout_s(self) -> float:
        """当前 tier 对应的 timeout（thinking 开时自动 x2，因为 thinking 显著变慢）。"""
        base = self.timeout_s_pro if self.model_tier == "pro" else self.timeout_s_flash
        return base * 2.0 if self.thinking_enabled else base

    def current_temperature(self) -> float:
        """当前 tier 对应的 temperature。注意：thinking 开时 provider 会忽略此值（官方不支持）。"""
        return self.temperature_pro if self.model_tier == "pro" else self.temperature_flash


# ════════════════════════════════════════════════════════════════════
# 输入映射：FeatureSnapshot → AIObserverInput
# ════════════════════════════════════════════════════════════════════


def build_observer_input(snap: FeatureSnapshot) -> AIObserverInput:
    """把特征快照压成给 LLM 的精简 JSON。

    原则：
    - 只带"当前状态 + 关键派生"，不带全量 recent 序列（token 爆炸）；
    - 枚举字段直接透传；数组字段做简化 projection。
    """
    cascade_top = []
    for b in snap.cascade_bands[:6]:
        cascade_top.append(
            {
                "side": b.side,
                "avg_price": round(b.avg_price, 2),
                "distance_pct": round(b.distance_pct, 4),
                "signal_count": b.signal_count,
            }
        )
    retail_top = []
    for b in snap.retail_stop_bands[:6]:
        retail_top.append(
            {
                "side": b.side,
                "avg_price": round(b.avg_price, 2),
                "distance_pct": round(b.distance_pct, 4),
            }
        )

    segment_flat: dict[str, Any] | None = None
    sp = snap.segment_portrait
    if sp is not None:
        segment_flat = {
            "start_time": sp.start_time,
            "type": sp.type,
            "status": sp.status,
            "roi_avg_price": sp.roi_avg_price,
            "roi_limit_avg_price": sp.roi_limit_avg_price,
            "roi_limit_max_price": sp.roi_limit_max_price,
            "pain_avg_price": sp.pain_avg_price,
            "pain_max_price": sp.pain_max_price,
            "bars_to_avg": sp.bars_to_avg,
            "bars_to_max": sp.bars_to_max,
            "dd_limit_pct": sp.dd_limit_pct,
            "dd_trailing_current": sp.dd_trailing_current,
            "dd_pierce_count": sp.dd_pierce_count,
            "sources": sp.sources,
        }

    vp_flat: dict[str, Any] | None = None
    if snap.volume_profile is not None:
        vp = snap.volume_profile
        vp_flat = {
            "poc_price": round(vp.poc_price, 2),
            "value_area_low": round(vp.value_area_low, 2),
            "value_area_high": round(vp.value_area_high, 2),
            "value_area_volume_ratio": round(vp.value_area_volume_ratio, 3),
            "last_price_position": vp.last_price_position,
            "poc_distance_pct": round(vp.poc_distance_pct, 4),
            "top_nodes": [
                {
                    "price": round(n.price, 2),
                    "total": round(n.total, 2),
                    "dominant_side": n.dominant_side,
                    "purity_ratio": round(n.purity_ratio, 3),
                }
                for n in vp.top_nodes[:5]
            ],
        }

    heatmap_flat: dict[str, Any] | None = None
    if snap.time_heatmap_view is not None:
        hv = snap.time_heatmap_view
        heatmap_flat = {
            "current_hour": hv.current_hour,
            "current_activity": round(hv.current_activity, 3),
            "current_rank": hv.current_rank,
            "peak_hours": hv.peak_hours,
            "dead_hours": hv.dead_hours,
            "is_active_session": hv.is_active_session,
        }

    trend_purity = snap.trend_purity_last.type if snap.trend_purity_last else None

    choch_kind = "none"
    choch_dir = "none"
    choch_dist = None
    choch_bars = None
    if snap.choch_latest is not None:
        choch_kind = snap.choch_latest.kind
        choch_dir = snap.choch_latest.direction
        choch_dist = snap.choch_latest.distance_pct
        choch_bars = snap.choch_latest.bars_since

    return AIObserverInput(
        symbol=snap.symbol,
        tf=snap.tf,
        anchor_ts=snap.anchor_ts,
        last_price=snap.last_price,
        atr=snap.atr,
        vwap_last=snap.vwap_last,
        vwap_slope_pct=snap.vwap_slope,
        fair_value_delta_pct=snap.fair_value_delta_pct,
        trend_purity=trend_purity,
        cvd_slope=snap.cvd_slope,
        cvd_sign=snap.cvd_slope_sign,
        cvd_converge_ratio=snap.cvd_converge_ratio,
        imbalance_green_ratio=snap.imbalance_green_ratio,
        imbalance_red_ratio=snap.imbalance_red_ratio,
        poc_shift_trend=snap.poc_shift_trend,
        power_imbalance_streak=snap.power_imbalance_streak,
        power_imbalance_streak_side=snap.power_imbalance_streak_side,
        trend_exhaustion_streak=snap.exhaustion_streak,
        trend_exhaustion_streak_type=snap.exhaustion_streak_type,
        resonance_buy_count=snap.resonance_buy_count,
        resonance_sell_count=snap.resonance_sell_count,
        sweep_count_recent=snap.sweep_count_recent,
        whale_net_direction=snap.whale_net_direction,
        nearest_resistance_price=snap.nearest_resistance_price,
        nearest_resistance_distance_pct=snap.nearest_resistance_distance_pct,
        nearest_support_price=snap.nearest_support_price,
        nearest_support_distance_pct=snap.nearest_support_distance_pct,
        just_broke_resistance=snap.just_broke_resistance,
        just_broke_support=snap.just_broke_support,
        pierce_atr_ratio=snap.pierce_atr_ratio,
        pierce_recovered=snap.pierce_recovered,
        choch_latest_kind=choch_kind,  # type: ignore[arg-type]
        choch_latest_direction=choch_dir,  # type: ignore[arg-type]
        choch_latest_distance_pct=choch_dist,
        choch_latest_bars_since=choch_bars,
        cascade_bands_top=cascade_top,
        retail_stop_bands_top=retail_top,
        segment_portrait=segment_flat,
        volume_profile=vp_flat,
        time_heatmap=heatmap_flat,
        trend_saturation_progress=(
            snap.trend_saturation.progress if snap.trend_saturation else None
        ),
        trend_saturation_type=(
            snap.trend_saturation.type if snap.trend_saturation else "none"
        ),
        stale_tables=snap.stale_tables,
    )


# ════════════════════════════════════════════════════════════════════
# Observer 主体
# ════════════════════════════════════════════════════════════════════


@dataclass
class _LastRunState:
    anchor_ts: int = 0
    started_at: float = 0.0
    finished_at: float = 0.0


class AIObserver:
    """AI 观察 orchestrator。

    典型调用路径：
      1. ``RuleRunner`` 产生 snapshot 后调 ``await observer.run_async(snap)``（fire-and-forget）；
      2. ``POST /api/ai/run`` 同步调 ``await observer.run(snap, trigger='manual', force_trade_plan=True)``；
      3. ``POST /api/ai/test`` 调 ``await observer.ping()``。
    """

    def __init__(
        self,
        *,
        provider: LLMProvider,
        store: AIObservationStore,
        settings: ObserverSettings | None = None,
    ) -> None:
        self._provider = provider
        self._store = store
        self._settings = settings or ObserverSettings()
        self._last = _LastRunState()
        self._sem = __import__("asyncio").Semaphore(max(1, self._settings.max_concurrent))

    # ── 公共 API ────────────────────────────────────────────

    async def run(
        self,
        snap: FeatureSnapshot,
        *,
        trigger: str = "scheduled",
        force_trade_plan: bool = False,
        force: bool = False,
    ) -> AIObserverFeedItem:
        """单次完整观察。会走并发闸门 + 节流。

        Args:
            trigger: 触发源（scheduled / manual / api / ...）
            force_trade_plan: 手动强制走 L3（绕过置信度阈值）
            force: 绕过节流/缓存，用于 REST ``POST /api/ai/observations/run`` 用户显式请求
        """
        import asyncio

        if not self._settings.enabled:
            return self._empty_item(snap, trigger=trigger, note="ai.enabled=false")

        # 节流：相同 anchor_ts + 冷却期内直接复用最新（force=True 时跳过）
        if not force and not self._should_run(snap):
            latest = await self._store.latest()
            if latest is not None and latest.anchor_ts == snap.anchor_ts:
                return latest

        async with self._sem:
            return await self._run_unsafe(snap, trigger=trigger, force_trade_plan=force_trade_plan)

    async def run_async(
        self, snap: FeatureSnapshot, *, trigger: str = "scheduled"
    ) -> None:
        """fire-and-forget 异步：供 RuleRunner 非阻塞调用。

        直接把 ``run`` 扔进 asyncio.create_task；外层无须 await。
        """
        import asyncio

        if not self._settings.enabled:
            return
        try:
            asyncio.create_task(self._wrap_safe(snap, trigger))
        except RuntimeError:
            logger.debug("no running loop; skip ai observer", extra={"tags": ["AI"]})

    async def ping(self) -> bool:
        return await self._provider.ping()

    async def latest_summary(
        self, snap: FeatureSnapshot | None = None
    ) -> AIObserverSummary | None:
        """拿 store 里最新一条的 summary；若 observer 未启用则返回 None。

        Args:
            snap: 可选，用于判断最新 item 是否属于当前 anchor_ts；
                  若不传则直接返回 latest（不过滤）。
        """
        if not self._settings.enabled:
            return None
        item = await self._store.latest()
        if item is None:
            return None
        if snap is not None and item.anchor_ts != snap.anchor_ts:
            # 仍然返回，但前端通过 age_seconds 能识别是"上一根 K 线"的陈旧观察
            return build_summary(item)
        return build_summary(item)

    @property
    def store(self) -> AIObservationStore:
        return self._store

    @property
    def settings(self) -> ObserverSettings:
        return self._settings

    @property
    def provider(self) -> LLMProvider:
        return self._provider

    # ── 内部 ────────────────────────────────────────────────

    async def _wrap_safe(self, snap: FeatureSnapshot, trigger: str) -> None:
        try:
            await self.run(snap, trigger=trigger)
        except Exception as e:  # noqa: BLE001 - 观察层异常不允许污染主链路
            logger.exception(
                f"ai observer background error: {e}", extra={"tags": ["AI"]}
            )

    def _should_run(self, snap: FeatureSnapshot) -> bool:
        now = time.time()
        if self._last.anchor_ts == snap.anchor_ts:
            # 同一根 K 线，看 cache_ttl
            if now - self._last.finished_at < self._settings.cache_ttl_seconds:
                return False
        # 全局节流
        if now - self._last.started_at < self._settings.min_interval_seconds:
            return False
        return True

    def _empty_item(
        self, snap: FeatureSnapshot, *, trigger: str, note: str
    ) -> AIObserverFeedItem:
        return AIObserverFeedItem(
            ts=int(time.time() * 1000),
            symbol=snap.symbol,
            tf=snap.tf,
            anchor_ts=snap.anchor_ts,
            last_price=snap.last_price,
            trigger=trigger,  # type: ignore[arg-type]
            provider=self._provider.name,
            note=note,
        )

    def _should_upgrade(
        self,
        trend: TrendLayerOut | None,
        money_flow: MoneyFlowLayerOut | None,
    ) -> bool:
        if not self._settings.auto_trade_plan:
            return False
        if trend is None or money_flow is None:
            return False
        if trend.confidence < self._settings.auto_trend_confidence:
            return False
        if money_flow.confidence < self._settings.auto_money_flow_confidence:
            return False
        if trend.direction == "neutral":
            return False
        if money_flow.dominant_side == "neutral":
            return False
        return True

    async def _run_unsafe(
        self,
        snap: FeatureSnapshot,
        *,
        trigger: str,
        force_trade_plan: bool,
    ) -> AIObserverFeedItem:
        import asyncio

        self._last.anchor_ts = snap.anchor_ts
        self._last.started_at = time.time()

        payload = build_observer_input(snap)
        started = time.perf_counter()

        # V1.1 · 统一模型：三层都用 settings.model_tier 对应的 tier；
        # L1 + L2 仍然并行（彼此独立）；L3 仍按阈值 gated，但也走同一 tier。
        tier = self._settings.model_tier
        temp = self._settings.current_temperature()
        timeout = self._settings.current_timeout_s()
        thinking = self._settings.thinking_enabled

        r1, r2 = await asyncio.gather(
            run_trend_agent(
                provider=self._provider,
                payload=payload,
                model_tier=tier,
                temperature=temp,
                timeout_s=timeout,
                thinking_enabled=thinking,
            ),
            run_money_flow_agent(
                provider=self._provider,
                payload=payload,
                trend_narrative=None,
                model_tier=tier,
                temperature=temp,
                timeout_s=timeout,
                thinking_enabled=thinking,
            ),
        )

        trend_out: TrendLayerOut | None = r1.output  # type: ignore[assignment]
        mf_out: MoneyFlowLayerOut | None = r2.output  # type: ignore[assignment]

        do_upgrade = force_trade_plan or self._should_upgrade(trend_out, mf_out)
        trade_out: TradePlanLayerOut | None = None
        r3: AgentResult | None = None
        if do_upgrade:
            r3 = await run_trade_plan_agent(
                provider=self._provider,
                payload=payload,
                trend_narrative=trend_out.narrative if trend_out else None,
                money_flow_narrative=mf_out.narrative if mf_out else None,
                model_tier=tier,
                temperature=temp,
                timeout_s=timeout,
                thinking_enabled=thinking,
            )
            trade_out = r3.output  # type: ignore[assignment]

        latency_ms = int((time.perf_counter() - started) * 1000)

        layers_used: list[str] = []
        models_used: dict[str, str] = {}
        usage_total: dict[str, int] = {"prompt": 0, "completion": 0, "total": 0}
        errors: dict[str, str] = {}

        for r in (r1, r2, r3):
            if r is None:
                continue
            if r.output is not None:
                layers_used.append(r.layer)
                models_used[r.layer] = r.model
                for k, v in r.usage.items():
                    key = {"prompt_tokens": "prompt", "completion_tokens": "completion"}.get(
                        k, k.replace("_tokens", "")
                    )
                    usage_total[key] = usage_total.get(key, 0) + int(v)
            elif r.error:
                errors[r.layer] = r.error

        item = AIObserverFeedItem(
            ts=int(time.time() * 1000),
            symbol=snap.symbol,
            tf=snap.tf,
            anchor_ts=snap.anchor_ts,
            last_price=snap.last_price,
            layers_used=[x for x in layers_used if x in {"trend", "money_flow", "trade_plan"}],  # type: ignore[misc]
            models_used=models_used,
            provider=self._provider.name,
            latency_ms=latency_ms,
            cost_tokens=usage_total,
            trend=trend_out,
            money_flow=mf_out,
            trade_plan=trade_out,
            trigger=trigger,  # type: ignore[arg-type]
            errors=errors,
        )
        await self._store.append(item)
        self._last.finished_at = time.time()
        logger.info(
            f"AI observer done {snap.symbol}/{snap.tf} layers={layers_used} "
            f"latency={latency_ms}ms tokens={usage_total.get('total',0)}",
            extra={"tags": ["AI"], "context": {"trigger": trigger, "upgrade": do_upgrade}},
        )
        return item

    async def aclose(self) -> None:
        await self._provider.aclose()


# ════════════════════════════════════════════════════════════════════
# 摘要派生（用于前端 card 和 REST `latest` 端点）
# ════════════════════════════════════════════════════════════════════


def build_summary(
    item: AIObserverFeedItem, *, now_ts: int | None = None
) -> AIObserverSummary:
    """把 feed item 压成卡片摘要。

    C 阶段扩展：提取关键数值（置信度/强度/磁吸带/R:R/risk_flags/成本），
    让主卡无需展开历史即可看到决策要点。
    """
    now = now_ts if now_ts is not None else int(time.time() * 1000)

    trend = item.trend
    mf = item.money_flow
    plan = item.trade_plan

    # 磁吸带预览：取 key_bands 前 3 条
    # 约定：prompt 要求 LLM 按磁吸强度/重要性从前到后排列 key_bands，
    # summary 只做 passthrough，不二次排序。
    bands_preview: list[SummaryBandPreview] = []
    if mf and mf.key_bands:
        for b in mf.key_bands[:3]:
            bands_preview.append(
                SummaryBandPreview(
                    kind=b.kind,
                    avg_price=b.avg_price,
                    distance_pct=b.distance_pct,
                    note=b.note,
                )
            )

    # 计划聚合
    has_plan = bool(plan and plan.legs)
    legs_count = len(plan.legs) if plan else 0
    top_rr: float | None = None
    if plan and plan.legs:
        top_rr = max((leg.risk_reward for leg in plan.legs), default=None)
    risk_flags: list[str] = list(plan.risk_flags[:5]) if plan else []

    tokens_total = sum(int(v) for v in (item.cost_tokens or {}).values())

    return AIObserverSummary(
        ts=item.ts,
        age_seconds=max(0, (now - item.ts) // 1000),
        trigger=item.trigger,
        provider=item.provider,
        # 趋势
        trend_direction=trend.direction if trend else None,
        trend_stage=trend.stage if trend else None,
        trend_strength=trend.strength if trend else None,
        trend_confidence=trend.confidence if trend else None,
        trend_narrative=trend.narrative if trend else None,
        # 资金
        money_flow_dominant=mf.dominant_side if mf else None,
        money_flow_confidence=mf.confidence if mf else None,
        money_flow_narrative=mf.narrative if mf else None,
        key_bands_preview=bands_preview,
        # 计划
        has_trade_plan=has_plan,
        trade_plan_narrative=plan.narrative if plan else None,
        trade_plan_confidence=plan.confidence if plan else None,
        trade_plan_legs_count=legs_count,
        trade_plan_top_rr=top_rr,
        risk_flags=risk_flags,
        # 元数据
        layers_used=list(item.layers_used),
        latency_ms=item.latency_ms,
        tokens_total=tokens_total,
        errors=dict(item.errors),
    )
