"""审计修复回归用例。

本文件只收录「针对审计 P0~P2 修复的定向守门人单测」，每个 case 的 assert
都对应具体 before/after 行为，避免问题再次悄悄回潮。

覆盖的修复：
- P0-1  TrendExhaustionPoint.exhaustion 允许 float（含 schema REAL 列）
- P0-2  score_reversal 方向口径对齐官方文档
        （Distribution→bullish / Accumulation→bearish）
- P0-3  调度层去掉 fair_value/fvg/imbalance/ob_decay 冗余项
- P1-4  SmartMoneySegment.end_time 支持 None（Ongoing 段）
- P1-5  _nearest_levels_and_pierce 连续对切片正确
- P1-6  cvd_converge 走归一化比值 + yaml 阈值
- P1-7  CircuitBreaker 冷却过后半开失败要能再次熔断
- P2-1  trend_exhaustion 近 N 根连续（streak） → reversal scorer 满分档
- P2-2  power_imbalance 连续 N 根同向 → breakout scorer 满分档
- P2-4  breakout.level_pierced 用 pierce_atr_ratio 判擦线
        breakout.ob_decayed 真正读 yaml 的 ob_decay_threshold
- P2-5  reversal.liq_pierce_recover 用 liq_recover_bars 判回收
- P2-6  清理 yaml 未实现项（instability_* / soft 接入）
- P2-7  parsers.shared.merge_result 死代码删除
"""

from __future__ import annotations

import time

import pytest

from backend.collector.circuit_breaker import CircuitBreaker
from backend.collector.parsers.endpoints import (
    parse_smart_money_cost,
    parse_trend_exhaustion,
    parse_trend_purity,
)
from backend.core.config import load_settings
from backend.models import (
    HvnNode,
    Kline,
    LiquiditySweepEvent,
    PowerImbalancePoint,
    SmartMoneySegment,
    TrendExhaustionPoint,
    TrendPuritySegment,
)
from backend.rules.features import FeatureExtractor, FeatureSnapshot
from backend.rules.modules.main_force_radar import build_main_force_radar
from backend.rules.scoring import (
    CapabilityScore,
    score_breakout,
    score_reversal,
)
from backend.storage.repositories import AtomRepositories, KlineRepository

_TF_MS = 30 * 60_000


# ═════════════════ P0-1 TrendExhaustionPoint.exhaustion = float ═════════════════


def test_trend_exhaustion_accepts_fractional() -> None:
    """官方样本 exhaustion 可为 8.5 / 7.2 等小数，早前 int 声明会报错丢数据。"""
    p = TrendExhaustionPoint(
        symbol="BTC", tf="30m", ts=1, exhaustion=8.5, type="Distribution"
    )
    assert p.exhaustion == pytest.approx(8.5)

    # 整数依然合法（向后兼容）。
    p2 = TrendExhaustionPoint(
        symbol="BTC", tf="30m", ts=2, exhaustion=0, type="Accumulation"
    )
    assert p2.exhaustion == 0.0


def test_parse_trend_exhaustion_keeps_fractional_rows() -> None:
    payload = {
        "trend_exhaustion": [
            {"timestamp": 1_760_680_800_000, "exhaustion": 8.5, "type": "Distribution"},
            {"timestamp": 1_760_682_600_000, "exhaustion": 0, "type": "Accumulation"},
        ]
    }
    result = parse_trend_exhaustion("BTC", "30m", payload)
    atoms = result.atoms.get("trend_exhaustion") or []
    assert len(atoms) == 2
    assert atoms[0].exhaustion == pytest.approx(8.5)
    assert atoms[1].exhaustion == 0.0


def test_parse_trend_purity_fixes_total_vol_consistency() -> None:
    payload = {
        "trend_purity": [
            {
                "start_time": 1_760_680_800_000,
                "end_time": None,
                "avg_price": 100.0,
                "buy_vol": 10.0,
                "sell_vol": 15.0,
                "total_vol": 10.0,  # 上游错填（应 >= 25）
                "purity": 40.0,
                "type": "Accumulation",
            }
        ]
    }
    result = parse_trend_purity("BTC", "30m", payload)
    atoms = result.atoms.get("trend_purity") or []
    assert len(atoms) == 1
    assert atoms[0].total_vol == pytest.approx(25.0)


def test_parse_trend_purity_logs_single_aggregated_warning(caplog) -> None:
    payload = {
        "trend_purity": [
            {
                "start_time": 1_760_680_800_000 + i * 1800_000,
                "end_time": None,
                "avg_price": 100.0 + i,
                "buy_vol": 10.0,
                "sell_vol": 20.0,
                "total_vol": 10.0,  # 均触发修复
                "purity": 33.0,
                "type": "Accumulation",
            }
            for i in range(5)
        ]
    }
    with caplog.at_level("WARNING"):
        parse_trend_purity("BTC", "30m", payload)
    msgs = [r.getMessage() for r in caplog.records if "trend_purity.total_vol" in r.getMessage()]
    assert msgs.count("trend_purity.total_vol 上游错填（批次聚合）") == 1


# ═════════════════ P0-2 score_reversal 方向口径 ═════════════════


def _reversal_snap(**overrides) -> FeatureSnapshot:
    base = dict(
        symbol="BTC",
        tf="30m",
        anchor_ts=1_700_000_000_000,
        last_price=100.0,
        atr=0.5,
    )
    base.update(overrides)
    return FeatureSnapshot(**base)


def test_score_reversal_distribution_means_bullish() -> None:
    """docs/upstream-api/endpoints/trend_exhaustion.md 大屏使用：
    Distribution 耗竭 → 派发方能量耗尽 → 底部反转预警 → bullish。"""
    cfg = load_settings().rules_defaults
    snap = _reversal_snap(
        trend_exhaustion_last=TrendExhaustionPoint(
            symbol="BTC", tf="30m", ts=1, exhaustion=8.5, type="Distribution"
        ),
    )
    cap: CapabilityScore = score_reversal(snap, cfg)
    assert cap.direction == "bullish"


def test_score_reversal_accumulation_means_bearish() -> None:
    """Accumulation 耗竭 → 吸筹方能量耗尽 → 顶部反转预警 → bearish。"""
    cfg = load_settings().rules_defaults
    snap = _reversal_snap(
        trend_exhaustion_last=TrendExhaustionPoint(
            symbol="BTC", tf="30m", ts=1, exhaustion=7.2, type="Accumulation"
        ),
    )
    cap: CapabilityScore = score_reversal(snap, cfg)
    assert cap.direction == "bearish"


# ═════════════════ P0-3 调度层剔除冗余项 ═════════════════


def test_scheduler_does_not_double_fetch_series_family() -> None:
    """Series 家族（fair_value/fvg/imbalance）由 liquidity_sweep 同片带出，
    order_blocks 由 trend_price 同片带出。调度表里不应再单独排这 4 个。"""
    settings = load_settings()
    schedule = settings.collector.schedule
    all_scheduled = {
        *schedule.kline_close,
        *schedule.every_5min,
        *schedule.every_30min,
        *schedule.every_1h,
        *schedule.every_4h,
    }

    assert "liquidity_sweep" in all_scheduled
    assert "trend_price" in all_scheduled

    for redundant in ("fair_value", "fvg", "imbalance", "ob_decay"):
        assert redundant not in all_scheduled, (
            f"{redundant} 已被 liquidity_sweep/trend_price 覆盖，不应重复拉取"
        )


# ═════════════════ P1-4 SmartMoneySegment.end_time Optional ═════════════════


def test_smart_money_ongoing_end_time_none() -> None:
    """Ongoing 段 end_time 可能为 None，模型必须放行。"""
    seg = SmartMoneySegment(
        symbol="BTC",
        tf="30m",
        start_time=1,
        end_time=None,
        avg_price=100.0,
        type="Accumulation",
        status="Ongoing",
    )
    assert seg.end_time is None


def test_parse_smart_money_cost_tolerates_null_end_time() -> None:
    payload = {
        "smart_money_cost": [
            {
                "start_time": 1_700_000_000_000,
                "end_time": None,
                "avg_price": 100.0,
                "type": "Accumulation",
                "status": "Ongoing",
            },
            {
                "start_time": 1_700_001_000_000,
                "avg_price": 120.0,
                "type": "Distribution",
                "status": "Completed",
            },
        ]
    }
    result = parse_smart_money_cost("BTC", "30m", payload)
    segs = result.atoms.get("smart_money") or []
    assert len(segs) == 2
    assert segs[0].end_time is None
    assert segs[1].end_time is None  # 字段缺失 → None


# ═════════════════ P1-5 _nearest_levels_and_pierce 切片 ═════════════════


@pytest.mark.asyncio
async def test_pierce_detection_handles_window_smaller_than_recent(db, settings):
    """K 线比 recent_window 少时，旧切片会产生 (k0, k0) 这种假对、甚至空列表，
    导致 pierce 无法识别。这里塞 2 根构造穿越，校验修复后仍能命中。"""
    anchor = 1_700_000_000_000
    klines = [
        Kline(
            symbol="BTC", tf="30m", ts=anchor - _TF_MS,
            open=99.0, high=99.2, low=98.8, close=99.0, volume=1.0,
        ),
        Kline(
            symbol="BTC", tf="30m", ts=anchor,
            open=99.5, high=101.5, low=99.2, close=101.0, volume=1.0,
        ),
    ]
    await KlineRepository(db).upsert_many(klines)

    atoms = AtomRepositories(db)
    await atoms.hvn_nodes.replace_for(
        {"symbol": "BTC", "tf": "30m"},
        [HvnNode(symbol="BTC", tf="30m", rank=1, price=100.0, volume=1000.0)],
    )

    # 显式把 recent_window 调得比 K 线数大，触发旧切片越界路径
    settings.rules_defaults["global"]["recent_window_bars"] = 50
    ext = FeatureExtractor(db, config=settings.rules_defaults)
    snap = await ext.extract("BTC", "30m")
    assert snap is not None
    # 99 → 101 穿过 100 → 刚穿破阻力位
    assert snap.just_broke_resistance is True


# ═════════════════ P1-6 cvd_converge 归一化 + yaml 阈值 ═════════════════


def _zero_caps() -> dict[str, CapabilityScore]:
    return {
        name: CapabilityScore(name=name, score=0, band="weak")
        for name in ("accumulation", "distribution", "breakout", "reversal")
    }


def _radar_snap(**overrides) -> FeatureSnapshot:
    base = dict(
        symbol="BTC",
        tf="30m",
        anchor_ts=1_700_000_000_000,
        last_price=100.0,
        atr=0.5,
        active_session=True,
    )
    base.update(overrides)
    return FeatureSnapshot(**base)


def test_cvd_converge_ratio_small_triggers_brewing() -> None:
    """归一化 ratio 低于 yaml 阈值 (默认 0.2) 才算收敛。"""
    cfg = load_settings().rules_defaults
    # 构造 vacuum 覆盖现价 + 活跃时段；让 cvd 窗口震荡但净流入接近 0
    from backend.models import VacuumBand

    vac = VacuumBand(symbol="BTC", tf="30m", low=99.5, high=100.5)
    # |slope|/range = 50/1000 = 0.05 < 0.2 → 收敛
    snap = _radar_snap(
        cvd_slope=50.0,
        cvd_range=1000.0,
        cvd_converge_ratio=0.05,
        vacuums=[vac],
    )
    caps = _zero_caps()
    out = build_main_force_radar(snap, caps, cfg=cfg)
    assert any(a.type == "变盘临近" for a in out.alerts)


def test_cvd_converge_ratio_high_does_not_trigger_brewing() -> None:
    """|slope|/range = 0.8 → 单边明显，不应识别为 brewing。"""
    cfg = load_settings().rules_defaults
    from backend.models import VacuumBand

    snap = _radar_snap(
        cvd_slope=800.0,
        cvd_range=1000.0,
        cvd_converge_ratio=0.8,
        vacuums=[VacuumBand(symbol="BTC", tf="30m", low=99.5, high=100.5)],
    )
    out = build_main_force_radar(snap, _zero_caps(), cfg=cfg)
    assert not any(a.type == "变盘临近" for a in out.alerts)


def test_cvd_converge_threshold_is_yaml_driven() -> None:
    """把 yaml 阈值调到极小（0.001），即使 ratio=0.05 也不再算收敛。"""
    import copy

    cfg = copy.deepcopy(load_settings().rules_defaults)
    cfg["main_force_radar"]["labels"]["brewing"]["cvd_converge_max_ratio"] = 0.001

    from backend.models import VacuumBand

    snap = _radar_snap(
        cvd_slope=50.0,
        cvd_range=1000.0,
        cvd_converge_ratio=0.05,
        vacuums=[VacuumBand(symbol="BTC", tf="30m", low=99.5, high=100.5)],
    )
    out = build_main_force_radar(snap, _zero_caps(), cfg=cfg)
    assert not any(a.type == "变盘临近" for a in out.alerts)


@pytest.mark.asyncio
async def test_feature_extractor_computes_cvd_converge_ratio(db, settings):
    """FeatureExtractor 必须写回 cvd_range / cvd_converge_ratio 字段。"""
    from backend.models import CvdPoint

    anchor = 1_700_000_000_000
    klines = [
        Kline(
            symbol="BTC", tf="30m", ts=anchor - i * _TF_MS,
            open=100, high=100.5, low=99.5, close=100, volume=1.0,
        )
        for i in range(9, -1, -1)
    ]
    await KlineRepository(db).upsert_many(klines)

    atoms = AtomRepositories(db)
    # CVD 大幅震荡但首尾差很小：[0, 500, -500, 400, -400, 300, -300, 200, -200, 50]
    values = [0, 500, -500, 400, -400, 300, -300, 200, -200, 50]
    for i, v in enumerate(values):
        await atoms.cvd.upsert(
            CvdPoint(symbol="BTC", tf="30m", ts=anchor - (9 - i) * _TF_MS, value=float(v))
        )

    ext = FeatureExtractor(db, config=settings.rules_defaults)
    snap = await ext.extract("BTC", "30m")
    assert snap is not None
    assert snap.cvd_slope == pytest.approx(50.0)
    # range = 500 - (-500) = 1000
    assert snap.cvd_range == pytest.approx(1000.0)
    assert snap.cvd_converge_ratio == pytest.approx(50.0 / 1000.0)


# ═════════════════ P1-7 CircuitBreaker 半开再熔断 ═════════════════


def test_circuit_breaker_retrips_after_cooldown_without_success(configured_logging):
    """冷却结束后若没恢复成功，下一次失败必须立刻再次熔断。
    修复前：opened_at != 0 且 failures >= threshold 不再触发 just_tripped，
    导致熔断保护永久失效。"""
    cb = CircuitBreaker(threshold=2, cooldown_seconds=0.05)
    cb.record_failure("hfd", "k", reason="e")
    cb.record_failure("hfd", "k", reason="e")
    assert cb.is_open("hfd", "k") is True

    time.sleep(0.08)
    assert cb.is_open("hfd", "k") is False  # half-open

    # 半开期的首次失败：立即再次熔断。
    tripped = cb.record_failure("hfd", "k", reason="e")
    assert tripped is True
    assert cb.is_open("hfd", "k") is True


def test_circuit_breaker_snapshot_open_flag_respects_cooldown(configured_logging):
    """snapshot 里 open 字段口径应与 is_open 一致，冷却过后不应再显示 open。"""
    cb = CircuitBreaker(threshold=1, cooldown_seconds=0.05)
    cb.record_failure("hfd", "k", reason="e")
    snap = [s for s in cb.snapshot() if s["key"] == "k"]
    assert snap and snap[0]["open"] is True

    time.sleep(0.08)
    snap = [s for s in cb.snapshot() if s["key"] == "k"]
    assert snap and snap[0]["open"] is False


# ═════════════════ P0-1 (schema) exhaustion 列支持小数落库 ═════════════════


@pytest.mark.asyncio
async def test_trend_exhaustion_fractional_persists(db):
    """schema 把 exhaustion 改为 REAL 后，小数值应该能原样往返。"""
    atoms = AtomRepositories(db)
    point = TrendExhaustionPoint(
        symbol="BTC", tf="30m", ts=1_700_000_000_000, exhaustion=8.5, type="Distribution"
    )
    await atoms.trend_exhaustion.upsert(point)

    row = await db.fetchone(
        "SELECT exhaustion FROM atoms_trend_exhaustion WHERE symbol=? AND tf=? AND ts=?",
        ("BTC", "30m", 1_700_000_000_000),
    )
    assert row is not None
    assert float(row["exhaustion"]) == pytest.approx(8.5)


@pytest.mark.asyncio
async def test_smart_money_null_end_time_persists(db):
    """Ongoing 段 end_time=None 要能落库并取出来。"""
    atoms = AtomRepositories(db)
    seg = SmartMoneySegment(
        symbol="BTC",
        tf="30m",
        start_time=1_700_000_000_000,
        end_time=None,
        avg_price=100.0,
        type="Accumulation",
        status="Ongoing",
    )
    await atoms.smart_money.upsert(seg)
    row = await db.fetchone(
        "SELECT end_time, status FROM atoms_smart_money WHERE symbol=? AND tf=? AND start_time=?",
        ("BTC", "30m", 1_700_000_000_000),
    )
    assert row is not None
    assert row["end_time"] is None
    assert row["status"] == "Ongoing"


# ═════════════════ P2-1 trend_exhaustion streak → reversal 满分档 ═════════════════


def test_reversal_exhaustion_streak_scores_full() -> None:
    """连续 ≥ consecutive_min 根同 type exhaustion≥alert → exhaustion_high 给满分。"""
    cfg = load_settings().rules_defaults
    te_last = TrendExhaustionPoint(
        symbol="BTC", tf="30m", ts=1, exhaustion=7.0, type="Distribution"
    )
    snap = _reversal_snap(
        trend_exhaustion_last=te_last,
        exhaustion_streak=3,
        exhaustion_streak_type="Distribution",
    )
    cap = score_reversal(snap, cfg)
    # 找到 exhaustion_high 这条 evidence，其 ratio 应为满分。
    e = next(ev for ev in cap.evidence if ev.rule_id == "exhaustion_high")
    assert e.ratio == pytest.approx(1.0)
    assert e.hit is True


def test_reversal_exhaustion_single_bar_not_full() -> None:
    """仅一根 exhaustion 值略低于 alert，streak 不够 → 不给满分。"""
    cfg = load_settings().rules_defaults
    te_last = TrendExhaustionPoint(
        # 3 < alert(5) → ratio=3/5=0.6 非满分
        symbol="BTC", tf="30m", ts=1, exhaustion=3.0, type="Distribution"
    )
    snap = _reversal_snap(
        trend_exhaustion_last=te_last,
        exhaustion_streak=0,
        exhaustion_streak_type="none",
    )
    cap = score_reversal(snap, cfg)
    e = next(ev for ev in cap.evidence if ev.rule_id == "exhaustion_high")
    assert e.ratio < 1.0
    assert e.hit is False


@pytest.mark.asyncio
async def test_feature_extractor_computes_exhaustion_streak(db, settings):
    """FeatureExtractor 应基于最近 exhaustion_window_bars 根算 streak。"""
    atoms = AtomRepositories(db)
    anchor = 1_700_000_000_000
    await KlineRepository(db).upsert_many([
        Kline(
            symbol="BTC", tf="30m", ts=anchor - i * _TF_MS,
            open=100, high=101, low=99, close=100, volume=1.0,
        )
        for i in range(2, -1, -1)
    ])
    # 3 根 exhaustion ≥ 5，同 type=Distribution
    for i in range(3):
        await atoms.trend_exhaustion.upsert(
            TrendExhaustionPoint(
                symbol="BTC", tf="30m",
                ts=anchor - (2 - i) * _TF_MS,
                exhaustion=6.5,
                type="Distribution",
            )
        )
    ext = FeatureExtractor(db, config=settings.rules_defaults)
    snap = await ext.extract("BTC", "30m")
    assert snap is not None
    assert snap.exhaustion_streak == 3
    assert snap.exhaustion_streak_type == "Distribution"


@pytest.mark.asyncio
async def test_feature_extractor_exhaustion_streak_breaks_on_type_change(db, settings):
    """不同 type 打断 streak。"""
    atoms = AtomRepositories(db)
    anchor = 1_700_000_000_000
    await KlineRepository(db).upsert_many([
        Kline(
            symbol="BTC", tf="30m", ts=anchor - i * _TF_MS,
            open=100, high=101, low=99, close=100, volume=1.0,
        )
        for i in range(2, -1, -1)
    ])
    # 最新一根 Accumulation，前两根 Distribution → streak=1 (Accumulation)
    await atoms.trend_exhaustion.upsert(
        TrendExhaustionPoint(
            symbol="BTC", tf="30m", ts=anchor - 2 * _TF_MS, exhaustion=6.0, type="Distribution"
        )
    )
    await atoms.trend_exhaustion.upsert(
        TrendExhaustionPoint(
            symbol="BTC", tf="30m", ts=anchor - _TF_MS, exhaustion=6.0, type="Distribution"
        )
    )
    await atoms.trend_exhaustion.upsert(
        TrendExhaustionPoint(
            symbol="BTC", tf="30m", ts=anchor, exhaustion=6.0, type="Accumulation"
        )
    )
    ext = FeatureExtractor(db, config=settings.rules_defaults)
    snap = await ext.extract("BTC", "30m")
    assert snap is not None
    assert snap.exhaustion_streak == 1
    assert snap.exhaustion_streak_type == "Accumulation"


# ═════════════════ P2-2 power_imbalance streak → breakout 满分档 ═════════════════


def _breakout_snap(**overrides) -> FeatureSnapshot:
    base = dict(
        symbol="BTC", tf="30m", anchor_ts=1_700_000_000_000,
        last_price=100.0, atr=0.5,
    )
    base.update(overrides)
    return FeatureSnapshot(**base)


def test_breakout_power_imbalance_streak_same_side_full() -> None:
    """向上突破 + 连续 3 根 buy 侧 power_imbalance 放大 → 满分。"""
    cfg = load_settings().rules_defaults
    snap = _breakout_snap(
        just_broke_resistance=True,
        pierce_atr_ratio=0.6,  # 足够大
        power_imbalance_last=PowerImbalancePoint(
            symbol="BTC", tf="30m", ts=1, buy_vol=10, sell_vol=2, ratio=5.0
        ),
        power_imbalance_streak=3,
        power_imbalance_streak_side="buy",
    )
    cap = score_breakout(snap, cfg)
    e = next(ev for ev in cap.evidence if ev.rule_id == "power_imbalance")
    assert e.ratio == pytest.approx(1.0)
    assert e.hit is True


def test_breakout_power_imbalance_single_not_full() -> None:
    """只有 1 根 ratio 轻度放大、streak < 3 → 非满分。"""
    cfg = load_settings().rules_defaults
    snap = _breakout_snap(
        just_broke_resistance=True,
        pierce_atr_ratio=0.6,
        power_imbalance_last=PowerImbalancePoint(
            # 1.0 < min_r=1.5 → ratio_above(1,1.5)=0.667 非满分
            symbol="BTC", tf="30m", ts=1, buy_vol=10, sell_vol=9, ratio=1.0
        ),
        power_imbalance_streak=1,
        power_imbalance_streak_side="buy",
    )
    cap = score_breakout(snap, cfg)
    e = next(ev for ev in cap.evidence if ev.rule_id == "power_imbalance")
    assert e.ratio < 1.0
    assert e.hit is False


# ═════════════════ P2-4 pierce_atr_mult / ob_decay_threshold 生效 ═════════════════


def test_breakout_pierce_below_atr_mult_is_brush() -> None:
    """穿越幅度 < atr_mult × ATR → 仅擦线，不视为 hit。"""
    cfg = load_settings().rules_defaults
    # default atr_mult=0.3，ATR=1 → 阈值 0.3；这里 0.1 < 0.3
    snap = _breakout_snap(
        just_broke_resistance=True,
        atr=1.0,
        pierce_atr_ratio=0.1,
    )
    cap = score_breakout(snap, cfg)
    e = next(ev for ev in cap.evidence if ev.rule_id == "level_pierced")
    assert e.hit is False
    assert "擦线" in (e.note or "")


def test_breakout_pierce_above_threshold_passes() -> None:
    """穿越幅度 ≥ atr_mult × ATR → hit。"""
    cfg = load_settings().rules_defaults
    snap = _breakout_snap(
        just_broke_resistance=True,
        atr=1.0,
        pierce_atr_ratio=0.5,
    )
    cap = score_breakout(snap, cfg)
    e = next(ev for ev in cap.evidence if ev.rule_id == "level_pierced")
    assert e.hit is True
    assert e.ratio > 0


def test_breakout_ob_decay_threshold_drives_ratio() -> None:
    """把 yaml ob_decay_threshold 调到 0.3（→ purity 满分线 30），
    同一 purity=40 应从默认 0.6 阈值的 0.67 分 → 0.3 阈值的满分。"""
    import copy

    cfg_lo = copy.deepcopy(load_settings().rules_defaults)
    cfg_lo["capabilities"]["breakout"]["thresholds"]["ob_decay_threshold"] = 0.3
    snap = _breakout_snap(
        just_broke_resistance=True,
        atr=1.0,
        pierce_atr_ratio=0.6,
        trend_purity_last=TrendPuritySegment(
            symbol="BTC", tf="30m",
            start_time=1, end_time=2,
            avg_price=100.0,
            buy_vol=60.0, sell_vol=40.0, total_vol=100.0,
            purity=40.0, type="Accumulation",
        ),
    )
    cap_lo = score_breakout(snap, cfg_lo)
    e_lo = next(ev for ev in cap_lo.evidence if ev.rule_id == "ob_decayed")
    assert e_lo.ratio == pytest.approx(1.0)

    cfg_hi = load_settings().rules_defaults  # threshold=0.6 默认
    cap_hi = score_breakout(snap, cfg_hi)
    e_hi = next(ev for ev in cap_hi.evidence if ev.rule_id == "ob_decayed")
    assert e_hi.ratio == pytest.approx(40.0 / 60.0)


# ═════════════════ P2-5 liq_recover_bars 真正生效 ═════════════════


def test_reversal_pierce_recovered_full_credit() -> None:
    """特征层已判回收 → liq_pierce_recover 满分。"""
    cfg = load_settings().rules_defaults
    snap = _reversal_snap(
        just_broke_resistance=True,
        sweep_last=LiquiditySweepEvent(
            symbol="BTC", tf="30m", ts=1, price=105.0,
            type="bearish_sweep", volume=10.0,
        ),
        pierce_recovered=True,
    )
    cap = score_reversal(snap, cfg)
    e = next(ev for ev in cap.evidence if ev.rule_id == "liq_pierce_recover")
    assert e.ratio == pytest.approx(1.0)
    assert e.hit is True


def test_reversal_pierce_not_recovered_half_credit() -> None:
    """刺穿成立但未回收 → 给 0.5 分（hit=False）。"""
    cfg = load_settings().rules_defaults
    snap = _reversal_snap(
        just_broke_resistance=True,
        sweep_last=LiquiditySweepEvent(
            symbol="BTC", tf="30m", ts=1, price=105.0,
            type="bearish_sweep", volume=10.0,
        ),
        pierce_recovered=False,
    )
    cap = score_reversal(snap, cfg)
    e = next(ev for ev in cap.evidence if ev.rule_id == "liq_pierce_recover")
    assert e.ratio == pytest.approx(0.5)
    assert e.hit is False


@pytest.mark.asyncio
async def test_pierce_recovered_detected_within_window(db, settings):
    """上刺后 1 根内收盘回到针尖以下 → pierce_recovered=True。"""
    atoms = AtomRepositories(db)
    anchor = 1_700_000_000_000
    # 5 根 K 线：第 3 根上冲到 105 触发上刺（sweep.price=104），第 4 根收回到 103
    klines = [
        Kline(symbol="BTC", tf="30m", ts=anchor - 4 * _TF_MS,
              open=100, high=101, low=99, close=100, volume=1.0),
        Kline(symbol="BTC", tf="30m", ts=anchor - 3 * _TF_MS,
              open=100, high=102, low=99, close=101, volume=1.0),
        Kline(symbol="BTC", tf="30m", ts=anchor - 2 * _TF_MS,
              open=101, high=105, low=101, close=104.5, volume=2.0),  # sweep bar
        Kline(symbol="BTC", tf="30m", ts=anchor - _TF_MS,
              open=104, high=104, low=102, close=103.0, volume=1.5),  # 收回
        Kline(symbol="BTC", tf="30m", ts=anchor,
              open=103, high=104, low=102, close=103.5, volume=1.0),
    ]
    await KlineRepository(db).upsert_many(klines)
    # bearish_sweep 于第 3 根：price=104（针被扫）
    await atoms.sweep_events.upsert(
        LiquiditySweepEvent(
            symbol="BTC", tf="30m", ts=anchor - 2 * _TF_MS,
            price=104.0, type="bearish_sweep", volume=2.0,
        )
    )
    ext = FeatureExtractor(db, config=settings.rules_defaults)
    snap = await ext.extract("BTC", "30m")
    assert snap is not None
    assert snap.pierce_recovered is True


# ═════════════════ P2-6 instability / soft 清理 ═════════════════


def test_rules_defaults_dropped_unimplemented_instability_keys() -> None:
    """确保 yaml 不再暗示已实现 phase 翻转计数器。"""
    cfg = load_settings().rules_defaults
    phase = cfg.get("phase_state_machine", {})
    assert "instability_flip_window_bars" not in phase
    assert "instability_max_flips" not in phase


def test_rules_defaults_removed_dead_soft_blocks() -> None:
    """accumulate / distribute 没有 alert 映射，其 soft 块不生效 → yaml 应清理。"""
    cfg = load_settings().rules_defaults
    labels = cfg.get("main_force_radar", {}).get("labels", {})
    for lab in ("accumulate", "distribute"):
        assert "soft" not in (labels.get(lab) or {}), (
            f"{lab}.soft 尚未接入实现，应从 yaml 移除"
        )


# ═════════════════ P2-7 merge_result 死代码移除 ═════════════════


def test_parsers_shared_no_merge_result_symbol() -> None:
    """移除死代码后 shared.py 不再对外暴露 merge_result。"""
    from backend.collector.parsers import shared

    assert not hasattr(shared, "merge_result")
