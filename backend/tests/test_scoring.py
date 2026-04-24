"""6 个 scorer 单元测试。

策略：手工构造 FeatureSnapshot，校验打分数值 / direction / band / 证据条数。
不依赖 DB。
"""

from __future__ import annotations

import pytest

from backend.core.config import load_settings
from backend.models import (
    LiquiditySweepEvent,
    PowerImbalancePoint,
    SmartMoneySegment,
    TrendExhaustionPoint,
    TrendPuritySegment,
    VacuumBand,
)
from backend.rules.features import ChochLatestView, FeatureSnapshot
from backend.rules.scoring import (
    LevelCandidate,
    LevelSource,
    MagnetCandidate,
    score_accumulation,
    score_breakout,
    score_distribution,
    score_level,
    score_magnet,
    score_reversal,
)


@pytest.fixture
def cfg():
    """直接用项目默认配置（不改原文件）。"""
    return load_settings().rules_defaults


def _base_snap(**overrides) -> FeatureSnapshot:
    defaults = dict(
        symbol="BTC",
        tf="30m",
        anchor_ts=1_700_000_000_000,
        last_price=100.0,
        atr=0.5,
    )
    defaults.update(overrides)
    return FeatureSnapshot(**defaults)


# ═══════════════ accumulation ═══════════════════════════


def test_accumulation_all_hit(cfg):
    snap = _base_snap(
        vwap_last=99.5,
        vwap_slope=0.02,
        fair_value_delta_pct=0.005,
        poc_shift_trend="up",
        poc_shift_delta_pct=0.01,
        imbalance_green_ratio=0.9,
        imbalance_red_ratio=0.0,
        cvd_slope=500.0,
        cvd_slope_sign="up",
        nearest_support_price=99.5,
        nearest_support_distance_pct=0.001,
        resonance_buy_count=3,
        resonance_sell_count=0,
        whale_net_direction="buy",
    )
    cap = score_accumulation(snap, cfg)
    assert cap.name == "accumulation"
    assert cap.score >= 95   # 六项全中接近满分
    assert cap.band in ("very_strong",)
    assert cap.direction == "bullish"
    assert len(cap.evidence) == 6
    assert all(e.hit for e in cap.evidence)


def test_accumulation_all_miss(cfg):
    snap = _base_snap(
        vwap_slope=-0.01,
        poc_shift_trend="down",
        poc_shift_delta_pct=-0.01,
        imbalance_green_ratio=0.0,
        imbalance_red_ratio=1.0,
        cvd_slope=-500.0,
        cvd_slope_sign="down",
        resonance_buy_count=0,
        resonance_sell_count=3,
    )
    cap = score_accumulation(snap, cfg)
    assert cap.score == 0.0
    assert cap.band == "weak"


def test_accumulation_missing_vwap_safe(cfg):
    """vwap 缺失时 fair_value_slope 条不应崩（ratio=0 贡献 0）。"""
    snap = _base_snap(vwap_last=None, vwap_slope=None)
    cap = score_accumulation(snap, cfg)
    assert 0 <= cap.score <= 100
    assert any(e.rule_id == "fair_value_slope" and not e.hit for e in cap.evidence)


# ═══════════════ distribution ═══════════════════════════


def test_distribution_symmetry(cfg):
    snap = _base_snap(
        vwap_slope=-0.02,
        poc_shift_trend="down",
        poc_shift_delta_pct=-0.01,
        imbalance_green_ratio=0.0,
        imbalance_red_ratio=0.9,
        cvd_slope=-500.0,
        cvd_slope_sign="down",
        nearest_resistance_price=100.5,
        nearest_resistance_distance_pct=0.001,
        resonance_buy_count=0,
        resonance_sell_count=3,
        whale_net_direction="sell",
    )
    cap = score_distribution(snap, cfg)
    assert cap.score >= 95
    assert cap.direction == "bearish"
    assert cap.band == "very_strong"


# ═══════════════ breakout ═══════════════════════════


def test_breakout_bullish_confirmed(cfg):
    snap = _base_snap(
        just_broke_resistance=True,
        just_broke_support=False,
        resonance_buy_count=3,
        resonance_sell_count=0,
        whale_net_direction="buy",
        power_imbalance_last=PowerImbalancePoint(
            symbol="BTC", tf="30m", ts=1, buy_vol=10, sell_vol=4, ratio=2.0
        ),
        trend_purity_last=TrendPuritySegment(
            symbol="BTC", tf="30m", start_time=1, end_time=2,
            avg_price=100.0, buy_vol=60, sell_vol=40, total_vol=100, purity=70, type="Accumulation",
        ),
        vacuums=[VacuumBand(symbol="BTC", tf="30m", low=102.0, high=104.0)],
        atr=0.5,
    )
    cap = score_breakout(snap, cfg)
    assert cap.direction == "bullish"
    assert cap.score >= 70  # 5 条几乎全中
    assert cap.band in ("strong_real",)


def test_breakout_no_pierce(cfg):
    snap = _base_snap()  # 全默认：没有穿越
    cap = score_breakout(snap, cfg)
    assert cap.direction == "neutral"
    # space_ahead 不会命中（neutral 方向），whale/power/ob 大概率也不中
    assert cap.score < 40


def test_breakout_bidirectional_uses_cvd_tiebreak(cfg):
    snap = _base_snap(
        just_broke_resistance=True,
        just_broke_support=True,
        cvd_slope=-500.0,
        cvd_slope_sign="down",
    )
    cap = score_breakout(snap, cfg)
    assert cap.direction == "bearish"


# ═══════════════ reversal ═══════════════════════════


def test_reversal_bearish_on_top_exhaustion(cfg):
    """顶部反转看跌：Accumulation 耗竭（吸筹方打光子弹涨不动）→ bearish。

    口径严格对齐 docs/upstream-api/endpoints/trend_exhaustion.md §大屏使用。
    历史上该方向曾被写反（Distribution→bearish），此用例作为回归守门人。
    """
    snap = _base_snap(
        sweep_count_recent=2,
        sweep_last=LiquiditySweepEvent(
            symbol="BTC", tf="30m", ts=1, price=101.0, type="bearish_sweep", volume=10.0
        ),
        trend_exhaustion_last=TrendExhaustionPoint(
            symbol="BTC", tf="30m", ts=1, exhaustion=8, type="Accumulation"
        ),
        fair_value_delta_pct=0.02,
        just_broke_resistance=True,
    )
    cap = score_reversal(snap, cfg)
    assert cap.direction == "bearish"
    assert cap.score >= 80  # 四项都该中


def test_reversal_bullish_on_distribution_exhaustion(cfg):
    """底部反转看涨：Distribution 耗竭（派发方巨量资金砸不动）→ bullish。

    参见 docs/upstream-api/endpoints/trend_exhaustion.md：
    Distribution 耗竭 = 空头子弹打光 = 底部反转预警 = bullish。
    """
    snap = _base_snap(
        sweep_count_recent=1,
        sweep_last=LiquiditySweepEvent(
            symbol="BTC", tf="30m", ts=1, price=99.0, type="bullish_sweep", volume=10.0
        ),
        trend_exhaustion_last=TrendExhaustionPoint(
            symbol="BTC", tf="30m", ts=1, exhaustion=8.5, type="Distribution"
        ),
        fair_value_delta_pct=-0.02,
        just_broke_support=True,
    )
    cap = score_reversal(snap, cfg)
    assert cap.direction == "bullish"


def test_reversal_no_signal(cfg):
    snap = _base_snap()
    cap = score_reversal(snap, cfg)
    assert cap.score == 0
    # direction 可能是 neutral/bullish/bearish 取决于 fair_value；但 score=0 就够了


# ═══════════════ V1.1 · CHoCH / BOS ═══════════════════════


def _choch_view(**overrides) -> ChochLatestView:
    defaults = dict(
        ts=1_700_000_000_000,
        price=100.0,
        level_price=99.0,
        origin_ts=1_699_999_000_000,
        type="CHoCH_Bullish",
        kind="CHoCH",
        direction="bullish",
        is_choch=True,
        distance_pct=-0.01,
        bars_since=1,
    )
    defaults.update(overrides)
    return ChochLatestView(**defaults)


def test_reversal_choch_bullish_overrides_direction(cfg):
    """⚡ CHoCH_Bullish 命中 → 覆盖 direction 为 bullish（即便 te=Accumulation 推 bearish）。"""
    snap = _base_snap(
        trend_exhaustion_last=TrendExhaustionPoint(
            symbol="BTC", tf="30m", ts=1, exhaustion=8, type="Accumulation"
        ),
        choch_latest=_choch_view(type="CHoCH_Bullish", direction="bullish"),
    )
    cap = score_reversal(snap, cfg)
    # CHoCH 事件 > te 推断，direction 被覆盖
    assert cap.direction == "bullish"
    # evidence 应包含 choch_reversal 条
    ids = [e.rule_id for e in cap.evidence]
    assert "choch_reversal" in ids


def test_reversal_choch_out_of_window_no_direction_override(cfg):
    """CHoCH 超窗 → 不覆盖 direction，保留 te 的 bearish 判断。"""
    snap = _base_snap(
        trend_exhaustion_last=TrendExhaustionPoint(
            symbol="BTC", tf="30m", ts=1, exhaustion=8, type="Accumulation"
        ),
        choch_latest=_choch_view(bars_since=99),
    )
    cap = score_reversal(snap, cfg)
    # 超窗 → choch 不生效 → te 推断胜出
    assert cap.direction == "bearish"


def test_breakout_bos_bearish_overrides_direction(cfg):
    """⚡ BOS_Bearish 命中 → direction 被覆盖为 bearish，即使 resistance 穿越。"""
    snap = _base_snap(
        just_broke_resistance=True,  # 无 CHoCH 时本应 bullish
        choch_latest=_choch_view(
            type="BOS_Bearish",
            kind="BOS",
            direction="bearish",
            is_choch=False,
            bars_since=1,
        ),
    )
    cap = score_breakout(snap, cfg)
    assert cap.direction == "bearish"
    ids = [e.rule_id for e in cap.evidence]
    assert "bos_confirm" in ids


# ═══════════════ key_level ═══════════════════════════


def test_score_level_strong(cfg):
    snap = _base_snap(
        trend_purity_last=TrendPuritySegment(
            symbol="BTC", tf="30m", start_time=1, end_time=2,
            avg_price=100.0, buy_vol=60, sell_vol=40, total_vol=100, purity=80, type="Accumulation",
        ),
    )
    lvl = LevelCandidate(
        price=99.5, side="support",
        sources=[
            LevelSource(kind="hvn", weight=40),
            LevelSource(kind="absolute_zone", weight=20),
            LevelSource(kind="trend_price", weight=10),
        ],
    )
    res = score_level(lvl, snap, cfg)
    assert res.score >= 70
    assert res.band == "strong"
    # 来源 3 条 + purity 1 条 + trend_price bonus 1 条 = 5
    assert len(res.evidence) >= 3


def test_score_level_decay_applied(cfg):
    snap = _base_snap()
    lvl = LevelCandidate(
        price=99.5, side="support",
        sources=[LevelSource(kind="hvn", weight=40)],
    )
    res_first = score_level(lvl, snap, cfg, test_count=1, state="first_test")
    res_worn = score_level(lvl, snap, cfg, test_count=4, state="worn_out")
    assert res_first.score > res_worn.score


def test_score_level_empty_sources(cfg):
    snap = _base_snap()
    lvl = LevelCandidate(price=99.5, side="support", sources=[])
    res = score_level(lvl, snap, cfg)
    assert res.score == 0.0


# ═══════════════ liquidity_magnet ═══════════════════════════


def test_score_magnet_strong_near(cfg):
    cand = MagnetCandidate(
        price=105.0, side="upside",
        heatmap_intensity=0.9, fuel_strength=0.7, vacuum_pull=0.6,
        distance_pct=0.005,
    )
    res = score_magnet(cand, cfg)
    # 0.9*40 + 0.7*30 + 0.6*20 + 0.9*10 = 78
    assert res.score >= 75
    assert res.side == "upside"


def test_score_magnet_too_far_zero_distance(cfg):
    cand = MagnetCandidate(
        price=200.0, side="upside",
        heatmap_intensity=1.0, fuel_strength=1.0, vacuum_pull=1.0,
        distance_pct=0.1,    # 远超 max_distance_pct=0.05
    )
    res = score_magnet(cand, cfg)
    # 其他全满但距离归 0，只丢掉 distance_close 的 10 分上限 → 剩 90
    assert res.score == pytest.approx(90.0)


def test_score_magnet_all_zero(cfg):
    cand = MagnetCandidate(price=100.0, side="downside")
    res = score_magnet(cand, cfg)
    # distance_pct=0 → 距离满分 10；其他 0 → 总 10
    assert res.score == pytest.approx(10.0)
