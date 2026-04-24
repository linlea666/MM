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
from backend.rules.features import BandView, ChochLatestView, FeatureSnapshot, SegmentPortrait
from backend.rules.modules import (
    build_dashboard_cards,
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
        # 诱多需要 power_imbalance 同向（sell）且连续放大 —— 对应官方"连续 3 根" 口径。
        power_imbalance_streak=3,
        power_imbalance_streak_side="sell",
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
    # V1.1：远距列表默认结构存在但为空
    assert levels.far_above == []
    assert levels.far_below == []


def test_key_levels_far_range_populated_beyond_ladder(cfg):
    """V1.1：R1-R3 占 3 档后，剩余 distance_pct ∈ [1%, 8%] 的应进入 far_above。"""
    # price=100：上方 101 101.5 102 102.5 103 103.5 104 105 107（够多，R1-R3 只消化 3 档）
    snap = _snap(
        last_price=100.0,
        hvn_nodes=[
            HvnNode(symbol="BTC", tf="30m", rank=1, price=101.0, volume=1000),
            HvnNode(symbol="BTC", tf="30m", rank=2, price=101.6, volume=900),
            HvnNode(symbol="BTC", tf="30m", rank=3, price=102.2, volume=800),
            HvnNode(symbol="BTC", tf="30m", rank=4, price=103.0, volume=700),
            HvnNode(symbol="BTC", tf="30m", rank=5, price=104.5, volume=600),
            HvnNode(symbol="BTC", tf="30m", rank=6, price=106.0, volume=500),
            HvnNode(symbol="BTC", tf="30m", rank=7, price=107.5, volume=400),
            # 下方对照（仅 1 档）
            HvnNode(symbol="BTC", tf="30m", rank=8, price=99.0, volume=900),
        ],
    )
    levels = build_key_levels(snap, cfg)
    # 上方 R1-R3 占位
    assert levels.r1 is not None and levels.r2 is not None and levels.r3 is not None
    # 剩余在 1%-8% 之间的应进入 far_above（如 104.5 / 106.0 / 107.5）
    assert len(levels.far_above) >= 1
    for lv in levels.far_above:
        d = abs(lv.price - 100.0) / 100.0
        assert 0.01 <= d <= 0.08 + 1e-9, f"远距越界：{lv.price}"
    # 远距不得与 R1-R3 价格重复
    ladder_prices = {lv.price for lv in (levels.r1, levels.r2, levels.r3) if lv}
    for lv in levels.far_above:
        assert lv.price not in ladder_prices


def test_key_levels_far_range_capped_by_max_far_count(cfg):
    """V1.1：far_above 最多 max_far_count 条，顺序为距当前价由近→远。"""
    import copy
    cfg2 = copy.deepcopy(cfg)
    cfg2.setdefault("key_levels", {})["max_far_count"] = 2
    # 1%-8% 之间塞多条
    snap = _snap(
        last_price=100.0,
        hvn_nodes=[
            HvnNode(symbol="BTC", tf="30m", rank=i, price=100.0 + 0.5 * i, volume=1000 - 10 * i)
            for i in range(1, 15)
        ],
    )
    levels = build_key_levels(snap, cfg2)
    assert len(levels.far_above) <= 2
    # 由近→远
    if len(levels.far_above) >= 2:
        assert levels.far_above[0].price < levels.far_above[1].price


def test_key_levels_far_range_disabled_when_zero(cfg):
    """V1.1：max_far_count=0 时远距列表必须为空。"""
    import copy
    cfg2 = copy.deepcopy(cfg)
    cfg2.setdefault("key_levels", {})["max_far_count"] = 0
    snap = _snap(
        last_price=100.0,
        hvn_nodes=[
            HvnNode(symbol="BTC", tf="30m", rank=i, price=100.0 + 0.5 * i, volume=1000 - 10 * i)
            for i in range(1, 15)
        ],
    )
    levels = build_key_levels(snap, cfg2)
    assert levels.far_above == []
    assert levels.far_below == []


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


def _cascade_band(**kw) -> BandView:
    base = dict(
        start_time=1_700_000_000_000, avg_price=105.0,
        top_price=106.0, bottom_price=104.0,
        volume=5_000_000.0, type="Distribution",
        side="short_fuel", above_price=True, distance_pct=0.05,
        signal_count=8_000_000,
    )
    base.update(kw)
    return BandView(**base)


def _retail_band(**kw) -> BandView:
    base = dict(
        start_time=1_700_000_000_000, avg_price=97.0,
        top_price=98.0, bottom_price=96.0,
        volume=3_000_000.0, type="Accumulation",
        side="long_fuel", above_price=False, distance_pct=-0.03,
        signal_count=None,
    )
    base.update(kw)
    return BandView(**base)


def test_liquidity_map_cascade_and_retail_bands(cfg):
    """V1.1：💣 爆仓带 + 散户止损带 应参与磁吸合成，source 正确标注。"""
    snap = _snap(
        last_price=100.0,
        cascade_bands=[_cascade_band()],
        retail_stop_bands=[_retail_band()],
    )
    liq = build_liquidity_map(snap, cfg)
    sources = {t.source for t in liq.above_targets} | {t.source for t in liq.below_targets}
    assert "cascade" in sources
    assert "retail" in sources


def test_key_levels_cascade_and_retail_bands_as_sources(cfg):
    """V1.1：💣 / 散户带 应作为关键位来源，出现在 Level.sources 或间接参与合成。"""
    snap = _snap(
        last_price=100.0,
        cascade_bands=[_cascade_band(avg_price=108.0, top_price=109.0, bottom_price=107.0)],
        retail_stop_bands=[_retail_band(avg_price=93.0, top_price=94.0, bottom_price=92.0)],
    )
    levels = build_key_levels(snap, cfg)
    all_sources: set[str] = set()
    for lvl in (levels.r1, levels.r2, levels.r3, levels.s1, levels.s2, levels.s3):
        if lvl is not None:
            all_sources.update(lvl.sources)
    assert {"cascade_band", "retail_band"} & all_sources


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


def test_trade_plan_v11_portrait_tp_and_stop_when_enabled(cfg):
    """V1.1：use_segment_portrait=true 时，T1/T2 优先用 ROI 极限，止损参考 Pain 防线。"""
    import copy

    cfg2 = copy.deepcopy(cfg)
    cfg2.setdefault("trade_plan", {})["use_segment_portrait"] = True
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
        segment_portrait=SegmentPortrait(
            start_time=1, type="Accumulation", status="Ongoing",
            roi_avg_price=100.0,
            roi_limit_avg_price=103.0,
            roi_limit_max_price=107.0,
            pain_max_price=99.5,  # 比 nearest_support=99.0 更严格
            sources=["roi", "pain"],
        ),
    )
    caps = _caps(snap, cfg2)
    phase = build_phase_state(snap, caps, cfg2)
    part = build_participation(snap, cfg2)
    plans = build_trade_plan(snap, caps, phase, part, cfg2)
    plan = plans[0]
    assert plan.take_profit[0] == 103.0
    assert plan.take_profit[1] == 107.0
    # stop 应比最近支撑 99.0 更接近当前价（因 pain_max=99.5 更严格）
    assert plan.stop is not None and plan.stop > 99.0 * (1 - 0.003)


def test_trade_plan_v11_veto_time_exhausted(cfg):
    """V1.1：veto.time_exhausted=true 且 bars_to_max ≤ 0 → 强制观望。"""
    import copy

    cfg2 = copy.deepcopy(cfg)
    cfg2.setdefault("trade_plan", {}).setdefault("veto", {})["time_exhausted"] = True
    snap = _snap(
        last_price=100.0,
        current_hour_activity=0.5,
        segment_portrait=SegmentPortrait(
            bars_to_max=-2, bars_to_avg=-3, sources=["time"],
        ),
    )
    caps = _caps(snap, cfg2)
    phase = build_phase_state(snap, caps, cfg2)
    part = build_participation(snap, cfg2)
    plans = build_trade_plan(snap, caps, phase, part, cfg2)
    # veto 触发：至少应追加 C 观望情景
    assert any(p.label == "C" and p.action == "观望" for p in plans)


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


def test_hero_lightning_badge_on_choch(cfg):
    """V1.1：最近 N 根内命中 ⚡ CHoCH → hero.market_structure 带 ⚡ 角标。"""
    snap = _snap(last_price=100.0)
    caps = _caps(snap, cfg)
    behavior = build_main_force_radar(snap, caps, cfg)
    phase = build_phase_state(snap, caps, cfg)
    part = build_participation(snap, cfg)
    levels = build_key_levels(snap, cfg)
    liq = build_liquidity_map(snap, cfg)
    plans = build_trade_plan(snap, caps, phase, part, cfg)
    choch = ChochLatestView(
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
    hero = build_hero(
        behavior=behavior, phase=phase, participation=part,
        levels=levels, liquidity=liq, plans=plans,
        choch_latest=choch, choch_alert_bars=3,
    )
    assert "⚡" in hero.market_structure
    assert "CHoCH" in hero.market_structure


# ═══════════════ V1.1 · 数字化白话卡 cards ═══════════════════════════


def test_cards_empty_when_no_views(cfg):
    """无 view 数据时，cards 仍然结构完整但全空（安全默认）。"""
    snap = _snap(last_price=100.0)
    cards = build_dashboard_cards(snap, cfg)
    assert cards.choch_latest is None
    assert cards.choch_recent == []
    assert cards.cascade_long_fuel == []
    assert cards.cascade_short_fuel == []
    assert cards.retail_long_fuel == []
    assert cards.retail_short_fuel == []
    assert cards.segment is None


def test_cards_choch_hint_and_mapping(cfg):
    """⚡ CHoCH 卡：字段 1:1 透出 + 白话口诀含价格、方向、距今根数。"""
    choch = ChochLatestView(
        ts=1_700_000_000_000,
        price=100.0,
        level_price=99_000.0,
        origin_ts=1_699_000_000_000,
        type="CHoCH_Bullish",
        kind="CHoCH",
        direction="bullish",
        is_choch=True,
        distance_pct=-0.01,
        bars_since=3,
    )
    snap = _snap(last_price=100.0, choch_latest=choch, choch_recent=[choch])
    cards = build_dashboard_cards(snap, cfg)
    assert cards.choch_latest is not None
    assert cards.choch_latest.level_price == 99_000.0
    assert cards.choch_latest.kind == "CHoCH"
    assert cards.choch_latest.direction == "bullish"
    assert "⚡" in cards.choch_latest.hint
    assert "99,000" in cards.choch_latest.hint
    assert "3 根前" in cards.choch_latest.hint
    assert len(cards.choch_recent) == 1


def test_cards_bands_split_by_side_and_intensity(cfg):
    """💣 / 散户带：按 side 分多空两列，intensity 在组内做归一化 ∈ [0, 1]。"""
    snap = _snap(
        last_price=100.0,
        cascade_bands=[
            _cascade_band(avg_price=108.0, side="short_fuel", above_price=True,
                          signal_count=8_000_000),
            _cascade_band(avg_price=95.0, side="long_fuel", above_price=False,
                          signal_count=2_000_000),
        ],
        retail_stop_bands=[
            _retail_band(avg_price=110.0, side="short_fuel", above_price=True,
                         volume=5_000_000.0),
            _retail_band(avg_price=92.0, side="long_fuel", above_price=False,
                         volume=1_000_000.0),
        ],
    )
    cards = build_dashboard_cards(snap, cfg)

    assert len(cards.cascade_long_fuel) == 1
    assert len(cards.cascade_short_fuel) == 1
    assert len(cards.retail_long_fuel) == 1
    assert len(cards.retail_short_fuel) == 1

    # 强度归一化：cascade 的 short_fuel 是组内最大，应 == 1.0
    assert cards.cascade_short_fuel[0].intensity == 1.0
    assert 0.0 <= cards.cascade_long_fuel[0].intensity < 1.0
    # retail 同理
    assert cards.retail_short_fuel[0].intensity == 1.0
    assert 0.0 <= cards.retail_long_fuel[0].intensity < 1.0

    # strength_label 白话：cascade 带 💣，retail 不带
    assert "💣" in cards.cascade_short_fuel[0].strength_label
    assert "💣" not in cards.retail_short_fuel[0].strength_label


def test_cards_segment_hint_combines_tp_moat_time(cfg):
    """波段画像卡：hint 同时带 🎯 T1/T2、🛡️ 护城河、⏰ 死亡线倒计时。"""
    snap = _snap(
        last_price=100.0,
        segment_portrait=SegmentPortrait(
            start_time=1, type="Accumulation", status="Ongoing",
            roi_avg_price=100.0,
            roi_limit_avg_price=103.0,
            roi_limit_max_price=107.0,
            pain_max_price=99.5,
            bars_to_max=3, bars_to_avg=1,
            dd_trailing_current=98.2,
            dd_pierce_count=1,
            sources=["roi", "pain", "time", "dd_tolerance"],
        ),
    )
    cards = build_dashboard_cards(snap, cfg)
    assert cards.segment is not None
    hint = cards.segment.hint
    assert "🎯" in hint and "T1 103.00" in hint and "T2 107.00" in hint
    assert "🛡️" in hint and "98.20" in hint and "📌×1" in hint
    assert "⏰" in hint and "3 根" in hint
    assert "💧" in hint
    assert cards.segment.sources == ["roi", "pain", "time", "dd_tolerance"]
