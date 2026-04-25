"""模块 7：V1.1 · 数字化白话卡。

核心目的：把 Phase 2 已做好的 ``FeatureSnapshot.view`` 直出给前端大屏。
大屏一眼看到 💣 爆仓带的具体价位 / ⚡ CHoCH 触发点 / 🎯 ROI 目标线等，
同时便于 AI 观察模式理解（数字化 + 白话）。

职责边界：
  - 本模块只做 **映射 + 排版文案**，不参与任何打分/过滤/决策；
  - 强度归一化口径与 ``liquidity_map.py`` 保持一致（便于 AI 交叉对齐）；
  - 单位容错：空 / None / 0 都给安全默认值。
"""

from __future__ import annotations

from typing import Any

from backend.models import (
    BandCard,
    ChochCard,
    DashboardCards,
    MomentumContribItem,
    MomentumOverrideEvent,
    MomentumPulseCard,
    SegmentCard,
    TargetItemCard,
    TargetProjectionCard,
)

from ..features import (
    BandView,
    ChochLatestView,
    FeatureSnapshot,
    MomentumPulseView,
    SegmentPortrait,
    TargetProjectionView,
)

__all__ = ["build_dashboard_cards"]


# ── 白话文案工具 ──

def _fmt_price(v: float) -> str:
    """价格保留 2 位小数，用 ``,`` 千位分隔。小币种（<1）降级为 4 位。"""
    if abs(v) < 1:
        return f"{v:,.4f}"
    return f"{v:,.2f}"


def _fmt_strength(volume: float, signal_count: int | None) -> str:
    """人类可读强度：cascade 优先展示炸弹数量（5.0M 💣），retail 展示金额（1.2M）。"""
    if signal_count is not None and signal_count > 0:
        if signal_count >= 1_000_000:
            return f"{signal_count / 1_000_000:.1f}M 💣"
        if signal_count >= 1_000:
            return f"{signal_count / 1_000:.1f}K 💣"
        return f"{signal_count} 💣"

    abs_v = abs(volume)
    if abs_v >= 1_000_000:
        return f"{abs_v / 1_000_000:.1f}M"
    if abs_v >= 1_000:
        return f"{abs_v / 1_000:.1f}K"
    return f"{abs_v:.0f}"


def _bars_hint(bars: int) -> str:
    if bars <= 0:
        return "刚刚"
    if bars == 1:
        return "1 根前"
    return f"{bars} 根前"


# ── 卡片构建 ──

def _choch_card(view: ChochLatestView) -> ChochCard:
    arrow = "↑" if view.direction == "bullish" else "↓"
    kind_zh = "破" if view.kind == "CHoCH" else "突"
    hint = (
        f"⚡ {view.kind}_{view.direction[0].upper() + view.direction[1:]} · "
        f"{arrow}{kind_zh} {_fmt_price(view.level_price)} · {_bars_hint(view.bars_since)}"
    )
    return ChochCard(
        ts=view.ts,
        price=round(view.price, 6),
        level_price=round(view.level_price, 6),
        type=view.type,
        kind=view.kind,
        direction=view.direction,
        distance_pct=round(view.distance_pct, 4),
        bars_since=view.bars_since,
        hint=hint,
    )


def _band_card(
    view: BandView,
    *,
    intensity_max_ref: float,
) -> BandCard:
    """把 BandView 映射为 BandCard。

    intensity 口径与 ``liquidity_map`` 对齐：
      - cascade 用 signal_count / max(signal_count)
      - retail  用 volume / max(volume)
    """
    if view.signal_count is not None and intensity_max_ref > 0:
        intensity = min(1.0, view.signal_count / intensity_max_ref)
    elif view.volume and intensity_max_ref > 0:
        intensity = min(1.0, view.volume / intensity_max_ref)
    else:
        intensity = 0.0

    return BandCard(
        start_time=view.start_time,
        avg_price=round(view.avg_price, 6),
        top_price=round(view.top_price, 6),
        bottom_price=round(view.bottom_price, 6),
        side=view.side,
        type=view.type,
        above_price=view.above_price,
        distance_pct=round(view.distance_pct, 4),
        intensity=round(intensity, 3),
        strength_label=_fmt_strength(view.volume, view.signal_count),
        signal_count=view.signal_count,
    )


def _segment_hint(portrait: SegmentPortrait) -> str:
    """白话口诀：T1/T2 · 护城河 · 死亡线倒计时。"""
    parts: list[str] = []
    if portrait.roi_limit_avg_price is not None or portrait.roi_limit_max_price is not None:
        tp_tokens: list[str] = []
        if portrait.roi_limit_avg_price is not None:
            tp_tokens.append(f"T1 {_fmt_price(portrait.roi_limit_avg_price)}")
        if portrait.roi_limit_max_price is not None:
            tp_tokens.append(f"T2 {_fmt_price(portrait.roi_limit_max_price)}")
        if tp_tokens:
            parts.append("🎯 " + " · ".join(tp_tokens))

    if portrait.dd_trailing_current is not None:
        moat = f"🛡️ 护城河 {_fmt_price(portrait.dd_trailing_current)}"
        if portrait.dd_pierce_count:
            moat += f" · 📌×{portrait.dd_pierce_count}"
        parts.append(moat)

    if portrait.bars_to_max is not None:
        if portrait.bars_to_max < 0:
            parts.append("⏰ 死亡线已越过")
        elif portrait.bars_to_max == 0:
            parts.append("⏰ 撞死亡线")
        else:
            parts.append(f"⏰ 死亡线 {portrait.bars_to_max} 根")

    if portrait.pain_max_price is not None:
        parts.append(f"💧 极限洗盘 {_fmt_price(portrait.pain_max_price)}")

    return " | ".join(parts)


def _segment_card(portrait: SegmentPortrait) -> SegmentCard:
    return SegmentCard(
        type=portrait.type,
        status=portrait.status,
        roi_avg_price=portrait.roi_avg_price,
        roi_limit_avg_price=portrait.roi_limit_avg_price,
        roi_limit_max_price=portrait.roi_limit_max_price,
        pain_avg_price=portrait.pain_avg_price,
        pain_max_price=portrait.pain_max_price,
        bars_to_avg=portrait.bars_to_avg,
        bars_to_max=portrait.bars_to_max,
        time_avg_ts=portrait.time_avg_ts,
        time_max_ts=portrait.time_max_ts,
        dd_trailing_current=portrait.dd_trailing_current,
        dd_limit_pct=portrait.dd_limit_pct,
        dd_pierce_count=portrait.dd_pierce_count,
        sources=list(portrait.sources),
        hint=_segment_hint(portrait),
    )


def _momentum_pulse_card(view: MomentumPulseView) -> MomentumPulseCard:
    """MomentumPulseView → MomentumPulseCard（直映）。"""
    override = None
    if view.override is not None:
        override = MomentumOverrideEvent(
            kind=view.override.kind,
            direction=view.override.direction,
            bars_since=view.override.bars_since,
            detail=view.override.detail,
        )
    contributions = [
        MomentumContribItem(
            label=c.label, value=c.value, delta=c.delta, side=c.side,
        )
        for c in view.contributions
    ]
    return MomentumPulseCard(
        score_long=view.score_long,
        score_short=view.score_short,
        dominant_side=view.dominant_side,
        streak_bars=view.streak_bars,
        streak_side=view.streak_side,
        fatigue_state=view.fatigue_state,
        fatigue_decay=view.fatigue_decay,
        override=override,
        contributions=contributions,
        note=view.note,
    )


def _target_projection_card(view: TargetProjectionView) -> TargetProjectionCard:
    """TargetProjectionView → TargetProjectionCard（直映）。"""
    def _conv(it) -> TargetItemCard:
        return TargetItemCard(
            kind=it.kind, side=it.side, tier=it.tier,
            price=it.price, distance_pct=it.distance_pct,
            confidence=it.confidence, bars_to_arrive=it.bars_to_arrive,
            evidence=it.evidence,
        )
    return TargetProjectionCard(
        above=[_conv(it) for it in view.above],
        below=[_conv(it) for it in view.below],
        max_distance_pct=view.max_distance_pct,
        note=view.note,
    )


def _split_band_cards(
    views: list[BandView], *, ref_kind: str
) -> tuple[list[BandCard], list[BandCard]]:
    """按 side 拆多空，并用全局最大值做同维归一化（保持同一族内强度可比）。

    ref_kind: ``"cascade"`` 或 ``"retail"``。决定用 signal_count 还是 volume 做分母。
    """
    if not views:
        return [], []

    if ref_kind == "cascade":
        ref_max = max(
            (v.signal_count or 0) for v in views if v.signal_count is not None
        )
    else:
        ref_max = max((v.volume or 0.0) for v in views)
    if not ref_max:
        ref_max = 1.0

    long_fuel: list[BandCard] = []
    short_fuel: list[BandCard] = []
    for v in views:
        card = _band_card(v, intensity_max_ref=float(ref_max))
        if v.side == "long_fuel":
            long_fuel.append(card)
        else:
            short_fuel.append(card)
    return long_fuel, short_fuel


# ── 对外入口 ──

def build_dashboard_cards(
    snap: FeatureSnapshot,
    cfg: dict[str, Any] | None = None,
) -> DashboardCards:
    """从 FeatureSnapshot 的 view 数据构建数字化白话卡。

    本函数对 cfg 无依赖（前端另有 UI 层展示开关 / TopN）；
    保留 cfg 参数是为了将来扩展（例如：按行情模式隐藏某些卡）。
    """
    del cfg  # 目前无运行时配置；预留接口

    # ⚡ CHoCH 卡
    choch_latest = _choch_card(snap.choch_latest) if snap.choch_latest is not None else None

    # 近窗 CHoCH 列表（前端可选展开）
    choch_recent: list[ChochCard] = []
    for v in snap.choch_recent:
        choch_recent.append(_choch_card(v))

    # 💣 / 散户止损带
    cascade_long_fuel, cascade_short_fuel = _split_band_cards(
        snap.cascade_bands, ref_kind="cascade"
    )
    retail_long_fuel, retail_short_fuel = _split_band_cards(
        snap.retail_stop_bands, ref_kind="retail"
    )

    # 波段四维画像
    segment = (
        _segment_card(snap.segment_portrait) if snap.segment_portrait is not None else None
    )

    # V1.1 · Step 7：动能能量柱 + 目标投影
    momentum_pulse = (
        _momentum_pulse_card(snap.momentum_pulse)
        if snap.momentum_pulse is not None else None
    )
    target_projection = (
        _target_projection_card(snap.target_projection)
        if snap.target_projection is not None else None
    )

    return DashboardCards(
        choch_latest=choch_latest,
        choch_recent=choch_recent,
        cascade_long_fuel=cascade_long_fuel,
        cascade_short_fuel=cascade_short_fuel,
        retail_long_fuel=retail_long_fuel,
        retail_short_fuel=retail_short_fuel,
        segment=segment,
        momentum_pulse=momentum_pulse,
        target_projection=target_projection,
    )
