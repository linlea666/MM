"""模块 6：交易建议（V1 规则输出，A/B/C 三情景）。

产出 A/B/C 至多 3 个 TradingPlan：
- A  主情景（基于最高分能力 + phase + participation）
- B  次情景（对称反向，给风险意识）
- C  观望（若 vet 条件命中：耗竭高、纯度低、非活跃时段等）

每个 plan 附带 entry / stop / TP / 星级 / 仓位 / 前提 / 失效条件。
"""

from __future__ import annotations

from typing import Any

from backend.models import ParticipationGate, PhaseState, TradeAction, TradingPlan

from ..features import FeatureSnapshot
from ..scoring import CapabilityScore
from ..scoring.common import cfg_path


def _stars_from_score(score: float, bands: dict) -> int:
    """bands 是 {1: 20, 2: 40, 3: 60, 4: 75, 5: 90}，返回达到最高的星级。"""
    if not bands:
        return 0
    items = sorted(
        [(int(k), float(v)) for k, v in bands.items()], key=lambda kv: kv[0]
    )
    stars = 0
    for n, th in items:
        if score >= th:
            stars = n
    return stars


def _size_from_stars(stars: int, cfg: dict[str, Any] | None):
    light = int(cfg_path(cfg, "trade_plan.position_size.light_max_stars", 2))
    heavy = int(cfg_path(cfg, "trade_plan.position_size.heavy_min_stars", 4))
    if stars <= light:
        return "轻仓"
    if stars >= heavy:
        return "重仓"
    return "标仓"


def _entry_range(price: float, pct: float) -> tuple[float, float]:
    return (round(price * (1 - pct), 6), round(price * (1 + pct), 6))


def _veto_reason(snap: FeatureSnapshot, cfg: dict[str, Any] | None) -> str | None:
    ex_th = int(cfg_path(cfg, "trade_plan.veto.exhaustion", 7))
    purity_th = float(cfg_path(cfg, "trade_plan.veto.purity", 30))
    active_th = float(cfg_path(cfg, "trade_plan.veto.active_session", 0.3))
    # V1.1：波段四维否决条件（默认全部关闭 → 零行为影响）
    time_veto = bool(cfg_path(cfg, "trade_plan.veto.time_exhausted", False))
    dd_veto = bool(cfg_path(cfg, "trade_plan.veto.dd_pierced", False))

    reasons: list[str] = []
    te = snap.trend_exhaustion_last
    if te and te.exhaustion >= ex_th:
        reasons.append(f"趋势耗竭 {te.exhaustion} ≥ {ex_th}")
    tp = snap.trend_purity_last
    if tp and tp.purity < purity_th:
        reasons.append(f"趋势纯度 {round(tp.purity, 1)} < {purity_th}")
    if snap.current_hour_activity < active_th:
        reasons.append(
            f"时段活跃度 {round(snap.current_hour_activity, 2)} < {active_th}"
        )
    # V1.1 · 趋势时间死亡线（越过 = 撞黄墙，立刻全平）
    sp = snap.segment_portrait
    if time_veto and sp is not None and sp.bars_to_max is not None and sp.bars_to_max <= 0:
        reasons.append(f"已撞时间死亡线 bars_to_max={sp.bars_to_max}")
    # V1.1 · 📌 护城河已破（dd_pierce_count ≥ 1 → 强制观望）
    if dd_veto and sp is not None and sp.dd_pierce_count is not None and sp.dd_pierce_count >= 1:
        reasons.append(f"📌 护城河刺穿 {sp.dd_pierce_count} 次")
    return "; ".join(reasons) if reasons else None


def _make_plan(
    label: str,
    action: TradeAction,
    stars: int,
    entry: tuple[float, float] | None,
    stop: float | None,
    tps: list[float],
    premise: str,
    invalidation: str,
    cfg: dict[str, Any] | None,
) -> TradingPlan:
    return TradingPlan(
        label=label,  # type: ignore[arg-type]
        action=action,
        stars=stars,
        entry=entry,
        stop=stop,
        take_profit=tps,
        position_size=_size_from_stars(stars, cfg) if action != "观望" else None,
        premise=premise,
        invalidation=invalidation,
    )


def _plan_bullish(
    snap: FeatureSnapshot, caps: dict[str, CapabilityScore], cfg: dict[str, Any] | None
) -> tuple[TradingPlan, int]:
    price = snap.last_price
    entry_pct = float(cfg_path(cfg, "trade_plan.entry_zone_pct", 0.004))
    stop_buf = float(cfg_path(cfg, "trade_plan.stop_buffer_pct", 0.003))
    tp_ratios = cfg_path(cfg, "trade_plan.target_ratios", [1.5, 3.0]) or [1.5, 3.0]
    bands = cfg_path(cfg, "trade_plan.stars", {}) or {}
    # V1.1：波段四维开关（默认 false → 完全兼容现有行为）
    use_portrait = bool(cfg_path(cfg, "trade_plan.use_segment_portrait", False))

    # 基础分：max(accumulation, breakout_bullish)
    brk = caps["breakout"]
    brk_contrib = brk.score if brk.direction == "bullish" else 0
    base = max(caps["accumulation"].score, brk_contrib)
    stars = _stars_from_score(base, bands)
    entry = _entry_range(price, entry_pct)

    sp = snap.segment_portrait if use_portrait else None

    # stop = 最近支撑 - 缓冲；V1.1：若开启 portrait 且有 pain_max 在更近（上方）→ 用 pain_max
    if snap.nearest_support_price:
        stop = round(snap.nearest_support_price * (1 - stop_buf), 6)
    else:
        atr = snap.atr or (price * 0.005)
        stop = round(price - atr, 6)
    # V1.1：pain_max_price = "实线极限防线" 击穿 = 溃败 → 更严格的止损
    if sp is not None and sp.pain_max_price is not None and sp.pain_max_price < price:
        pain_stop = round(sp.pain_max_price * (1 - stop_buf), 6)
        # 取更接近当前价的（更严格）止损，避免把止损挂得过远
        if pain_stop > stop:
            stop = pain_stop

    risk = price - stop
    # V1.1：T1/T2 优先用 roi_limit_avg_price / roi_limit_max_price（官方"及格线"/"天花板"）
    if sp is not None and sp.roi_limit_avg_price is not None and sp.roi_limit_max_price is not None \
            and sp.roi_limit_avg_price > price and sp.roi_limit_max_price > price:
        tps = [round(sp.roi_limit_avg_price, 6), round(sp.roi_limit_max_price, 6)]
    else:
        tps = [round(price + risk * r, 6) for r in tp_ratios] if risk > 0 else []

    action: TradeAction = "追多" if brk.direction == "bullish" and brk.score >= 60 else "回踩做多"
    premise = (
        f"accumulation={int(caps['accumulation'].score)}  "
        f"breakout={int(brk.score)}({brk.direction})  "
        f"whale={snap.whale_net_direction}"
    )
    invalidation = f"跌破 {stop}" if stop else "跌破最近支撑"
    plan = _make_plan("A", action, stars, entry, stop, tps, premise, invalidation, cfg)
    return plan, stars


def _plan_bearish(
    snap: FeatureSnapshot, caps: dict[str, CapabilityScore], cfg: dict[str, Any] | None
) -> tuple[TradingPlan, int]:
    price = snap.last_price
    entry_pct = float(cfg_path(cfg, "trade_plan.entry_zone_pct", 0.004))
    stop_buf = float(cfg_path(cfg, "trade_plan.stop_buffer_pct", 0.003))
    tp_ratios = cfg_path(cfg, "trade_plan.target_ratios", [1.5, 3.0]) or [1.5, 3.0]
    bands = cfg_path(cfg, "trade_plan.stars", {}) or {}
    use_portrait = bool(cfg_path(cfg, "trade_plan.use_segment_portrait", False))

    brk = caps["breakout"]
    brk_contrib = brk.score if brk.direction == "bearish" else 0
    base = max(caps["distribution"].score, brk_contrib)
    stars = _stars_from_score(base, bands)
    entry = _entry_range(price, entry_pct)

    sp = snap.segment_portrait if use_portrait else None

    if snap.nearest_resistance_price:
        stop = round(snap.nearest_resistance_price * (1 + stop_buf), 6)
    else:
        atr = snap.atr or (price * 0.005)
        stop = round(price + atr, 6)
    # V1.1：pain_max_price 对称：做空时 > price 即视作上方极限防线
    if sp is not None and sp.pain_max_price is not None and sp.pain_max_price > price:
        pain_stop = round(sp.pain_max_price * (1 + stop_buf), 6)
        if pain_stop < stop:
            stop = pain_stop

    risk = stop - price
    if sp is not None and sp.roi_limit_avg_price is not None and sp.roi_limit_max_price is not None \
            and sp.roi_limit_avg_price < price and sp.roi_limit_max_price < price:
        tps = [round(sp.roi_limit_avg_price, 6), round(sp.roi_limit_max_price, 6)]
    else:
        tps = [round(price - risk * r, 6) for r in tp_ratios] if risk > 0 else []

    action: TradeAction = "追空" if brk.direction == "bearish" and brk.score >= 60 else "反弹做空"
    premise = (
        f"distribution={int(caps['distribution'].score)}  "
        f"breakout={int(brk.score)}({brk.direction})  "
        f"whale={snap.whale_net_direction}"
    )
    invalidation = f"涨破 {stop}" if stop else "涨破最近阻力"
    plan = _make_plan("B", action, stars, entry, stop, tps, premise, invalidation, cfg)
    return plan, stars


def _plan_wait(reasons: str) -> TradingPlan:
    return TradingPlan(
        label="C",
        action="观望",
        stars=0,
        entry=None,
        stop=None,
        take_profit=[],
        position_size=None,
        premise=reasons or "当前信号强度不足",
        invalidation="直到出现更明确的方向信号",
    )


def build_trade_plan(
    snap: FeatureSnapshot,
    caps: dict[str, CapabilityScore],
    phase: PhaseState,
    participation: ParticipationGate,
    cfg: dict[str, Any] | None = None,
) -> list[TradingPlan]:
    plans: list[TradingPlan] = []
    veto = _veto_reason(snap, cfg)

    # 如果 veto 命中且参与度低 → 只出观望
    if veto and participation.level in ("疑似散户", "垃圾时间"):
        plans.append(_plan_wait(veto + f"; participation={participation.level}"))
        return plans

    bull_plan, bull_stars = _plan_bullish(snap, caps, cfg)
    bear_plan, bear_stars = _plan_bearish(snap, caps, cfg)

    # A 选主（高分那个），B 对称反向
    if bull_stars >= bear_stars:
        plans.append(bull_plan)
        if bear_stars > 0:
            bear_plan.label = "B"
            plans.append(bear_plan)
    else:
        bear_plan.label = "A"
        plans.append(bear_plan)
        if bull_stars > 0:
            bull_plan.label = "B"
            plans.append(bull_plan)

    # 追加观望情景（C）
    if veto:
        plans.append(_plan_wait(veto))
    elif max(bull_stars, bear_stars) <= 1:
        plans.append(_plan_wait("所有情景星级 ≤ 1，建议观望"))

    return plans[:3]


__all__ = ["build_trade_plan"]
