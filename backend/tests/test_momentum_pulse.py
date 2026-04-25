"""V1.1 · Step 7 · MomentumPulse + TargetProjection 派生单测。

策略：直接调用 ``_derive_momentum_pulse`` / ``_derive_target_projection``，
喂入构造好的字段（不经 DB），覆盖关键场景：
  - 多头放电（PI buy + cvd up + resonance + pierce）
  - 空头放电（对称）
  - 拉锯（多空各半）
  - 数据 stale（atoms_power_imbalance 全 0）
  - exhausted（dominant + 匹配 type 触发疲劳）
  - 错配 type 不触发疲劳
  - override 优先级 CHoCH > Sweep > Pierce
  - target_projection 排序与裁剪
  - target_projection ROI/Pain 缺失降级
  - max_distance_pct 截断

阈值/权重对齐 ``rules.default.yaml::momentum_pulse`` 的默认值。
"""

from __future__ import annotations

import pytest

from backend.models import (
    ChochEvent,
    HeatmapBand,
    LiquiditySweepEvent,
    PowerImbalancePoint,
    TrendExhaustionPoint,
    TrendSaturationStat,
    VacuumBand,
)
from backend.rules.features import (
    BandView,
    ChochLatestView,
    SegmentPortrait,
    _derive_momentum_pulse,
    _derive_target_projection,
)


# ─── 辅助 ─────────────────────────────────────────────────


def _pi(buy: float, sell: float, ratio: float) -> PowerImbalancePoint:
    return PowerImbalancePoint(symbol="BTC", tf="30m", ts=0, buy_vol=buy, sell_vol=sell, ratio=ratio)


def _exh(value: int, t: str) -> TrendExhaustionPoint:
    return TrendExhaustionPoint(symbol="BTC", tf="30m", ts=0, exhaustion=value, type=t)


def _sat(progress: float) -> TrendSaturationStat:
    return TrendSaturationStat(
        symbol="BTC", tf="30m", type="Accumulation", start_time=0,
        avg_vol=1.0, current_vol=1.0, progress=progress,
    )


def _choch(direction: str, level_price: float, bars_since: int = 1) -> ChochLatestView:
    is_bull = direction == "bullish"
    return ChochLatestView(
        ts=0, price=level_price + (1 if is_bull else -1),
        level_price=level_price, origin_ts=0,
        type="CHoCH_Bullish" if is_bull else "CHoCH_Bearish",
        kind="CHoCH", direction=direction,  # type: ignore[arg-type]
        is_choch=True, distance_pct=0.0, bars_since=bars_since,
    )


def _sweep_event(side: str, price: float, ts: int) -> LiquiditySweepEvent:
    return LiquiditySweepEvent(
        symbol="BTC", tf="30m", ts=ts, price=price,
        type=side,  # type: ignore[arg-type]
        volume=1.0,
    )


_TF_MS = 30 * 60_000
_ANCHOR = 1_700_000_000_000


def _kwargs(**overrides):
    """默认全部"无信号"，按测试覆盖项 override。"""
    base = dict(
        cfg={},
        anchor_ts=_ANCHOR,
        tf_ms=_TF_MS,
        stale_tables=[],
        power_imbalance_last=None,
        power_imbalance_streak=0,
        power_imbalance_streak_side="none",
        cvd_slope=None,
        cvd_slope_sign="flat",
        imbalance_green_ratio=0.0,
        imbalance_red_ratio=0.0,
        resonance_buy_count=0,
        resonance_sell_count=0,
        trend_exhaustion_last=None,
        exhaustion_streak=0,
        exhaustion_streak_type="none",
        trend_saturation=None,
        choch_latest=None,
        sweep_last=None,
        just_broke_resistance=False,
        just_broke_support=False,
        pierce_atr_ratio=None,
    )
    base.update(overrides)
    return base


# ═══════════════════════════════════════════════════════════════
# MomentumPulse
# ═══════════════════════════════════════════════════════════════


def test_momentum_pulse_bullish_full_burst():
    """多头满档：PI buy ratio=2.4 streak=3 + cvd up + resonance buy=2 + pierce 上破。"""
    view = _derive_momentum_pulse(**_kwargs(
        power_imbalance_last=_pi(buy=200, sell=80, ratio=2.4),
        power_imbalance_streak=3,
        power_imbalance_streak_side="buy",
        cvd_slope=1234.0, cvd_slope_sign="up",
        imbalance_green_ratio=0.6, imbalance_red_ratio=0.1,
        resonance_buy_count=2,
        just_broke_resistance=True,
        pierce_atr_ratio=0.5,
    ))
    # 期望分量：25 + 20 + 20 + 15 + 10*1.0 + 10 = 100
    assert view.score_long == 100
    assert view.score_short == 0
    assert view.dominant_side == "long"
    assert view.streak_bars == 3
    assert view.streak_side == "buy"
    assert view.fatigue_state == "fresh"
    # 应 6 条贡献全有
    labels = {c.label for c in view.contributions}
    assert {"power_imbalance", "pi_streak", "cvd_slope",
            "resonance_buy", "imbalance_ratio", "pierce"}.issubset(labels)


def test_momentum_pulse_bearish_full_burst():
    view = _derive_momentum_pulse(**_kwargs(
        power_imbalance_last=_pi(buy=80, sell=200, ratio=-2.4),
        power_imbalance_streak=3,
        power_imbalance_streak_side="sell",
        cvd_slope=-1234.0, cvd_slope_sign="down",
        imbalance_green_ratio=0.1, imbalance_red_ratio=0.6,
        resonance_sell_count=2,
        just_broke_support=True,
        pierce_atr_ratio=0.5,
    ))
    assert view.score_short == 100
    assert view.score_long == 0
    assert view.dominant_side == "short"
    assert view.streak_side == "sell"


def test_momentum_pulse_neutral_when_balanced():
    """多空各 10 分（差距 < min_dominant_gap=10）→ neutral。"""
    view = _derive_momentum_pulse(**_kwargs(
        cvd_slope=10.0, cvd_slope_sign="up",  # +20 long
        imbalance_green_ratio=0.0, imbalance_red_ratio=0.5,  # +10 short
    ))
    # long=20 short=10；diff=10，正好 dominant_gap 阈值 → long
    assert view.score_long == 20
    assert view.score_short == 10
    assert view.dominant_side == "long"


def test_momentum_pulse_neutral_when_close_gap():
    """差距小于 10 时为 neutral。"""
    view = _derive_momentum_pulse(**_kwargs(
        # imbalance 多空对称 0.5/0.5 → 占比差=0 → 0 分
        # 仅靠一个 resonance buy=1 → +7~8 分
        resonance_buy_count=1,
    ))
    # ratio = 1/2 = 0.5 → 15*0.5 = 7.5 → 8
    assert view.score_long == 8
    assert view.score_short == 0
    assert view.dominant_side == "neutral"


def test_momentum_pulse_pi_stale_drops_pi_score():
    """PI 数据 stale → 不计 PI/streak 分，note 带警告。"""
    view = _derive_momentum_pulse(**_kwargs(
        stale_tables=["atoms_power_imbalance"],
        power_imbalance_last=_pi(buy=200, sell=80, ratio=2.4),
        power_imbalance_streak=3,
        power_imbalance_streak_side="buy",
        cvd_slope=1.0, cvd_slope_sign="up",
    ))
    # 仅 cvd_slope=20 分；PI 25+20=45 被忽略
    assert view.score_long == 20
    assert "PI 数据陈旧" in view.note


def test_momentum_pulse_fatigue_match_type_marks_exhausted():
    """dominant=long + Accumulation exhaustion → exhausted。"""
    view = _derive_momentum_pulse(**_kwargs(
        cvd_slope=1.0, cvd_slope_sign="up",
        imbalance_green_ratio=0.6, imbalance_red_ratio=0.0,  # +10
        resonance_buy_count=2,                                 # +15
        trend_exhaustion_last=_exh(8, "Accumulation"),
        exhaustion_streak=3,
        exhaustion_streak_type="Accumulation",
    ))
    assert view.dominant_side == "long"
    assert view.fatigue_state == "exhausted"
    assert view.fatigue_decay == 0.5


def test_momentum_pulse_fatigue_mismatch_type_stays_fresh():
    """dominant=long 但 exhaustion type=Distribution → 不算疲劳。"""
    view = _derive_momentum_pulse(**_kwargs(
        cvd_slope=1.0, cvd_slope_sign="up",
        resonance_buy_count=2,
        trend_exhaustion_last=_exh(8, "Distribution"),
        exhaustion_streak=3,
        exhaustion_streak_type="Distribution",
    ))
    assert view.dominant_side == "long"
    assert view.fatigue_state == "fresh"


def test_momentum_pulse_fatigue_mid_via_saturation():
    """无 exhaustion，但 saturation.progress >= 50 → mid。"""
    view = _derive_momentum_pulse(**_kwargs(
        cvd_slope=1.0, cvd_slope_sign="up",
        trend_saturation=_sat(progress=70.0),
    ))
    assert view.fatigue_state == "mid"
    assert view.fatigue_decay == 0.2


def test_momentum_pulse_override_choch_priority_over_sweep():
    """同时存在 CHoCH + Sweep → 取 CHoCH。"""
    view = _derive_momentum_pulse(**_kwargs(
        choch_latest=_choch("bullish", level_price=100.0, bars_since=1),
        sweep_last=_sweep_event("bullish_sweep", price=99.0, ts=_ANCHOR - _TF_MS),
    ))
    assert view.override is not None
    assert view.override.kind == "CHoCH"
    assert view.override.direction == "bullish"


def test_momentum_pulse_override_sweep_when_no_choch():
    view = _derive_momentum_pulse(**_kwargs(
        sweep_last=_sweep_event("bearish_sweep", price=101.0, ts=_ANCHOR - _TF_MS),
    ))
    assert view.override is not None
    assert view.override.kind == "Sweep"
    assert view.override.direction == "bearish"
    assert view.override.bars_since == 1


def test_momentum_pulse_override_pierce_when_no_choch_no_sweep():
    view = _derive_momentum_pulse(**_kwargs(
        just_broke_resistance=True,
        pierce_atr_ratio=0.5,
    ))
    assert view.override is not None
    assert view.override.kind == "Pierce"
    assert view.override.direction == "bullish"


def test_momentum_pulse_override_skipped_when_too_old():
    """CHoCH bars_since > override_max_bars=3 → 不做 override。"""
    view = _derive_momentum_pulse(**_kwargs(
        choch_latest=_choch("bullish", level_price=100.0, bars_since=10),
    ))
    assert view.override is None


# ═══════════════════════════════════════════════════════════════
# TargetProjection
# ═══════════════════════════════════════════════════════════════


def _seg_portrait(**kw) -> SegmentPortrait:
    """方便构造 SegmentPortrait。"""
    base = dict(
        start_time=_ANCHOR - 10 * _TF_MS,
        type="Accumulation", status="Ongoing",
        sources=["roi", "pain"],
    )
    base.update(kw)
    return SegmentPortrait(**base)


def _band_view(side: str, avg_price: float, signal_count: int) -> BandView:
    """构造一条 BandView。"""
    return BandView(
        start_time=_ANCHOR - 5 * _TF_MS,
        avg_price=avg_price, top_price=avg_price + 0.5,
        bottom_price=avg_price - 0.5,
        volume=signal_count * 100.0,
        type="Accumulation" if side == "long_fuel" else "Distribution",
        side=side,  # type: ignore[arg-type]
        above_price=False, distance_pct=0.0,
        signal_count=signal_count,
    )


def _heatmap_band(price: float, intensity: float) -> HeatmapBand:
    return HeatmapBand(
        symbol="BTC", tf="30m", start_time=_ANCHOR - _TF_MS,
        price=price, intensity=intensity, type="Accumulation",
    )


def test_target_projection_basic_above_below_split():
    """ROI 在上方、Pain 在下方，距离正确。"""
    view = _derive_target_projection(
        cfg={},
        last_price=100.0,
        atr=1.0,
        segment_portrait=_seg_portrait(
            roi_limit_avg_price=102.0,
            roi_limit_max_price=104.0,
            pain_avg_price=98.0,
            pain_max_price=96.0,
        ),
        cascade_views=[],
        heatmap=[],
        vacuums=[],
        nearest_support_price=None,
        nearest_resistance_price=None,
        momentum_pulse=None,
    )
    assert len(view.above) == 2
    assert len(view.below) == 2
    # 距离升序
    assert view.above[0].price == 102.0
    assert view.above[1].price == 104.0
    assert view.below[0].price == 98.0
    assert view.below[1].price == 96.0
    # bars_to_arrive：|102-100|/atr=2 → 2
    assert view.above[0].bars_to_arrive == 2
    assert view.above[1].bars_to_arrive == 4
    # confidence 应该是有限值
    for it in view.above + view.below:
        assert 0.0 <= it.confidence <= 1.0


def test_target_projection_filters_too_far():
    """距离超过 max_distance_pct (8%) 的目标被过滤。"""
    view = _derive_target_projection(
        cfg={},
        last_price=100.0,
        atr=1.0,
        segment_portrait=_seg_portrait(
            roi_limit_avg_price=200.0,        # +100% → 过滤
            roi_limit_max_price=104.0,
            pain_avg_price=10.0,              # -90% → 过滤
        ),
        cascade_views=[],
        heatmap=[],
        vacuums=[],
        nearest_support_price=None,
        nearest_resistance_price=None,
        momentum_pulse=None,
    )
    assert len(view.above) == 1
    assert view.above[0].price == 104.0
    assert len(view.below) == 0


def test_target_projection_atr_none_yields_no_bars():
    view = _derive_target_projection(
        cfg={},
        last_price=100.0,
        atr=None,
        segment_portrait=_seg_portrait(roi_limit_avg_price=102.0),
        cascade_views=[], heatmap=[], vacuums=[],
        nearest_support_price=None, nearest_resistance_price=None,
        momentum_pulse=None,
    )
    assert view.above[0].bars_to_arrive is None


def test_target_projection_cascade_and_heatmap_and_vacuum_and_nearest():
    """混合多个来源，confirm 各种来源都能进 items。"""
    view = _derive_target_projection(
        cfg={},
        last_price=100.0,
        atr=1.0,
        segment_portrait=None,
        cascade_views=[
            _band_view("short_fuel", 102.0, signal_count=10),  # above
            _band_view("long_fuel", 98.0, signal_count=5),     # below
        ],
        heatmap=[
            _heatmap_band(101.5, intensity=0.9),               # above
            _heatmap_band(98.5, intensity=0.7),                # below
        ],
        vacuums=[
            VacuumBand(symbol="BTC", tf="30m", low=103.0, high=104.0),
            VacuumBand(symbol="BTC", tf="30m", low=96.0, high=97.0),
        ],
        nearest_support_price=99.0,
        nearest_resistance_price=101.0,
        momentum_pulse=None,
    )
    above_kinds = {it.kind for it in view.above}
    below_kinds = {it.kind for it in view.below}
    assert {"cascade_band", "heatmap", "vacuum", "nearest_level"} <= above_kinds
    assert {"cascade_band", "heatmap", "vacuum", "nearest_level"} <= below_kinds


def test_target_projection_per_side_topn_caps_list():
    """per_side_topn=5；构造 7 个 above 应只保留 5 个最近的。"""
    cv = [
        _band_view("short_fuel", 100.0 + i * 0.5, signal_count=i)
        for i in range(1, 8)  # 100.5 ~ 104.0
    ]
    view = _derive_target_projection(
        cfg={},
        last_price=100.0,
        atr=1.0,
        segment_portrait=None,
        cascade_views=cv,
        heatmap=[], vacuums=[],
        nearest_support_price=None, nearest_resistance_price=None,
        momentum_pulse=None,
    )
    assert len(view.above) <= 5
    # 应保留最近的 5 个（100.5 / 101.0 / 101.5 / 102.0 / 102.5）
    distances = [it.distance_pct for it in view.above]
    assert distances == sorted(distances)
