"""6 模块 builder 单元测试。

覆盖：
- main_force_radar  主标签挑选 / alerts 生成
- phase_state       8 阶段判定 + unstable
- participation     命中数 → 等级映射
- key_levels        候选收集 / 聚合 / 打分 / R/S 阶梯
- liquidity_map     上下方目标 / nearest 判定
- trade_plan        A/B/C 三情景 / veto 逻辑
- hero              拼装
"""

from __future__ import annotations

import pytest

from backend.core.config import load_settings
from backend.models import (
    AbsoluteZone,
    HeatmapBand,
    HvnNode,
    LiquidationFuelBand,
    LiquiditySweepEvent,
    MicroPocSegment,
    OrderBlock,
    PowerImbalancePoint,
    ResonanceEvent,
    SmartMoneySegment,
    TrendExhaustionPoint,
    TrendPuritySegment,
    TrendSaturationStat,
    VacuumBand,
)
from backend.rules.features import FeatureSnapshot
from backend.rules.modules import (
    build_hero,
    build_key_levels,
    build_liquidity_map,
    build_main_force_radar,
    build_participation,
    build_phase_state,
    build_trade_plan,
)
from backend.rules.scoring import (
    score_accumulation,
    score_breakout,
    score_distribution,
    score_reversal,
)


@pytest.fixture
def cfg():
    return load_settings().rules_defaults


def _snap(**kw) -> FeatureSnapshot:
    base = dict(
        symbol="BTC", tf="30m",
        anchor_ts=1_700_000_000_000,
        last_price=100.0, atr=0.5,
    )
    base.update(kw)
    return FeatureSnapshot(**base)


def _caps(snap, cfg):
    return {
        "accumulation": score_accumulation(snap, cfg),
        "distribution": score_distribution(snap, cfg),
        "breakout": score_breakout(snap, cfg),
        "reversal": score_reversal(snap, cfg),
    }


# ═══════════════ main_force_radar ═══════════════════════════


def test_main_force_radar_strong_accumulation(cfg):
    snap = _snap(
        vwap_last=99.0, vwap_slope=0.03, fair_value_delta_pct=0.01,
        poc_shift_trend="up", poc_shift_delta_pct=0.01,
        imbalance_green_ratio=0.9, cvd_slope_sign="up", cvd_slope=500,
        nearest_support_price=99.5, nearest_support_distance_pct=0.001,
        resonance_buy_count=3, whale_net_direction="buy",
    )
    caps = _caps(snap, cfg)
    behavior = build_main_force_radar(snap, caps, cfg)
    assert behavior.main == "强吸筹"
    assert behavior.sub_scores["吸筹"] >= 80
    # 贴近支撑 + whale buy + 绿占比 → support alert
    assert any(a.type == "护盘中" for a in behavior.alerts)


def test_main_force_radar_sweep_alert(cfg):
    snap = _snap(
        sweep_count_recent=3,
        sweep_last=LiquiditySweepEvent(
            symbol="BTC", tf="30m", ts=1, price=100.0, type="bullish_sweep", volume=10.0
        ),
    )
    caps = _caps(snap, cfg)
    b = build_main_force_radar(snap, caps, cfg)
    assert any(a.type == "猎杀进行中" for a in b.alerts)


def test_main_force_radar_bull_trap(cfg):
    snap = _snap(
        just_broke_resistance=True,
        whale_net_direction="sell",
        resonance_sell_count=2,
        power_imbalance_last=PowerImbalancePoint(
            symbol="BTC", tf="30m", ts=1, buy_vol=1, sell_vol=8, ratio=3.0
        ),
    )
    caps = _caps(snap, cfg)
    b = build_main_force_radar(snap, caps, cfg)
    assert any(a.type == "诱多" for a in b.alerts)


# ═══════════════ phase_state ═══════════════════════════


def test_phase_real_breakout(cfg):
    snap = _snap(
        just_broke_resistance=True,
        resonance_buy_count=3,
        whale_net_direction="buy",
        power_imbalance_last=PowerImbalancePoint(
            symbol="BTC", tf="30m", ts=1, buy_vol=10, sell_vol=2, ratio=2.5
        ),
        trend_purity_last=TrendPuritySegment(
            symbol="BTC", tf="30m", start_time=1, end_time=2,
            avg_price=100.0, buy_vol=70, sell_vol=30, total_vol=100, purity=80, type="Accumulation",
        ),
        vacuums=[VacuumBand(symbol="BTC", tf="30m", low=102.0, high=104.0)],
    )
    caps = _caps(snap, cfg)
    phase = build_phase_state(snap, caps, cfg)
    assert phase.current == "真突破启动"


def test_phase_exhaustion(cfg):
    snap = _snap(
        trend_exhaustion_last=TrendExhaustionPoint(
            symbol="BTC", tf="30m", ts=1, exhaustion=8, type="Distribution"
        ),
        trend_saturation=TrendSaturationStat(
            symbol="BTC", tf="30m", type="Distribution", start_time=1,
            avg_vol=100, current_vol=95, progress=85,
        ),
    )
    caps = _caps(snap, cfg)
    phase = build_phase_state(snap, caps, cfg)
    assert phase.current == "趋势耗竭"


def test_phase_chaotic_fallback(cfg):
    snap = _snap()
    caps = _caps(snap, cfg)
    phase = build_phase_state(snap, caps, cfg)
    assert phase.current == "无序震荡"
    assert phase.unstable is True   # chaotic 兜底给 50 < 60


# ═══════════════ participation ═══════════════════════════


def test_participation_all_four(cfg):
    snap = _snap(
        resonance_count_recent=4, resonance_buy_count=3, resonance_sell_count=1,
        fair_value_delta_pct=0.02,
        power_imbalance_last=PowerImbalancePoint(
            symbol="BTC", tf="30m", ts=1, buy_vol=10, sell_vol=2, ratio=3.0
        ),
        current_hour_activity=0.7,
    )
    p = build_participation(snap, cfg)
    assert p.level == "主力真参与"
    assert p.confidence == 1.0
    assert len(p.evidence) == 4


def test_participation_none_hit(cfg):
    snap = _snap()
    p = build_participation(snap, cfg)
    assert p.level == "垃圾时间"
    assert p.confidence == 0.0


# ═══════════════ key_levels ═══════════════════════════


def test_key_levels_ladder_from_hvn_zones(cfg):
    snap = _snap(
        last_price=100.0,
        hvn_nodes=[
            HvnNode(symbol="BTC", tf="30m", rank=1, price=99.0, volume=1000),
            HvnNode(symbol="BTC", tf="30m", rank=2, price=98.0, volume=800),
            HvnNode(symbol="BTC", tf="30m", rank=3, price=97.0, volume=500),
            HvnNode(symbol="BTC", tf="30m", rank=4, price=102.0, volume=600),
            HvnNode(symbol="BTC", tf="30m", rank=5, price=103.5, volume=400),
        ],
        absolute_zones=[
            AbsoluteZone(
                symbol="BTC", tf="30m", start_time=1,
                bottom_price=98.8, top_price=99.2, type="Accumulation",
            ),
        ],
    )
    levels = build_key_levels(snap, cfg)
    # 上方 2 档 (102 / 103.5)；下方 3 档（99、98、97）
    assert levels.r1 is not None
    assert levels.s1 is not None
    assert levels.s1.price < 100.0
    assert levels.r1.price > 100.0
    # S1 来源应该包含 hvn + absolute_zone
    assert "hvn" in levels.s1.sources or "absolute_zone" in levels.s1.sources


def test_key_levels_no_candidates(cfg):
    snap = _snap()
    levels = build_key_levels(snap, cfg)
    # 全空
    assert levels.r1 is None and levels.s1 is None
    assert levels.current_price == 100.0


# ═══════════════ liquidity_map ═══════════════════════════


def test_liquidity_map_above_below_sort(cfg):
    snap = _snap(
        last_price=100.0,
        heatmap=[
            HeatmapBand(symbol="BTC", tf="30m", start_time=1, price=102.0, intensity=0.9, type="Distribution"),
            HeatmapBand(symbol="BTC", tf="30m", start_time=1, price=98.0, intensity=0.7, type="Accumulation"),
        ],
        liquidation_fuel=[
            LiquidationFuelBand(symbol="BTC", tf="30m", bottom=103.0, top=104.0, fuel=0.5),
        ],
    )
    liq = build_liquidity_map(snap, cfg)
    assert len(liq.above_targets) >= 1
    assert len(liq.below_targets) >= 1
    assert liq.nearest_side in ("above", "below")
    assert liq.above_targets[0].intensity >= 0.0


def test_liquidity_map_empty(cfg):
    snap = _snap()
    liq = build_liquidity_map(snap, cfg)
    assert liq.above_targets == []
    assert liq.below_targets == []
    assert liq.nearest_side is None


# ═══════════════ trade_plan ═══════════════════════════


def test_trade_plan_bullish_as_A(cfg):
    snap = _snap(
        last_price=100.0,
        vwap_slope=0.02, fair_value_delta_pct=0.005,
        poc_shift_trend="up", poc_shift_delta_pct=0.01,
        imbalance_green_ratio=0.9, cvd_slope_sign="up", cvd_slope=500,
        nearest_support_price=99.0, nearest_support_distance_pct=0.01,
        resonance_buy_count=3, whale_net_direction="buy",
        current_hour_activity=0.7,
        trend_purity_last=TrendPuritySegment(
            symbol="BTC", tf="30m", start_time=1, end_time=2,
            avg_price=100.0, buy_vol=70, sell_vol=30, total_vol=100, purity=70, type="Accumulation",
        ),
    )
    caps = _caps(snap, cfg)
    phase = build_phase_state(snap, caps, cfg)
    part = build_participation(snap, cfg)
    plans = build_trade_plan(snap, caps, phase, part, cfg)
    assert plans[0].label == "A"
    assert plans[0].action in ("追多", "回踩做多")
    assert plans[0].stars >= 3
    assert plans[0].stop is not None and plans[0].stop < snap.last_price
    assert len(plans[0].take_profit) == 2


def test_trade_plan_veto_triggers_wait(cfg):
    snap = _snap(
        last_price=100.0,
        trend_exhaustion_last=TrendExhaustionPoint(
            symbol="BTC", tf="30m", ts=1, exhaustion=9, type="Distribution"
        ),
        current_hour_activity=0.1,
    )
    caps = _caps(snap, cfg)
    phase = build_phase_state(snap, caps, cfg)
    part = build_participation(snap, cfg)   # hits=0 → 垃圾时间
    plans = build_trade_plan(snap, caps, phase, part, cfg)
    assert len(plans) == 1
    assert plans[0].label == "C"
    assert plans[0].action == "观望"


# ═══════════════ hero ═══════════════════════════


def test_hero_assembly(cfg):
    snap = _snap(last_price=100.0)
    caps = _caps(snap, cfg)
    behavior = build_main_force_radar(snap, caps, cfg)
    phase = build_phase_state(snap, caps, cfg)
    part = build_participation(snap, cfg)
    levels = build_key_levels(snap, cfg)
    liq = build_liquidity_map(snap, cfg)
    plans = build_trade_plan(snap, caps, phase, part, cfg)
    hero = build_hero(
        behavior=behavior, phase=phase, participation=part,
        levels=levels, liquidity=liq, plans=plans,
    )
    assert hero.action_conclusion
    assert hero.main_behavior
    assert isinstance(hero.stars, int) and 0 <= hero.stars <= 5
