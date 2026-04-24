"""FeatureExtractor 单元测试。

策略：对空 DB 插入已知的原子数据 → 调用 extract → 验派生字段。
覆盖：
- 没数据时返回 None
- K 线 + ATR / vwap / cvd / imbalance 派生
- poc_shift 趋势
- 最近关键位 & 刚穿越
- 共振净方向
- time_heatmap 活跃度
- 稀疏数据（imbalance 全 0）回退到 0/0
"""

from __future__ import annotations

import pytest

from backend.models import (
    AbsoluteZone,
    CvdPoint,
    HeatmapBand,
    HvnNode,
    ImbalancePoint,
    Kline,
    MicroPocSegment,
    OrderBlock,
    PocShiftPoint,
    PowerImbalancePoint,
    ResonanceEvent,
    SmartMoneySegment,
    TimeHeatmapHour,
    TrendExhaustionPoint,
    TrendSaturationStat,
    VwapPoint,
)
from backend.rules.features import FeatureExtractor
from backend.storage.repositories import AtomRepositories, KlineRepository


_TF_MS = 30 * 60_000


# ─── 辅助 ─────────────────────────────────────────────────


def _make_klines(anchor_ts: int, n: int, *, start_price: float = 100.0, step: float = 0.5) -> list[Kline]:
    """构造 n 根单调递增 K 线；最新一根 ts = anchor_ts。"""
    klines: list[Kline] = []
    for i in range(n):
        ts = anchor_ts - (n - 1 - i) * _TF_MS
        price = start_price + i * step
        klines.append(
            Kline(
                symbol="BTC",
                tf="30m",
                ts=ts,
                open=price - 0.1,
                high=price + 0.3,
                low=price - 0.3,
                close=price,
                volume=10.0,
                source="binance",
            )
        )
    return klines


async def _seed_base(db, *, anchor_ts: int, n_klines: int = 30, start_price: float = 100.0, step: float = 0.5) -> list[Kline]:
    klines = _make_klines(anchor_ts, n_klines, start_price=start_price, step=step)
    await KlineRepository(db).upsert_many(klines)
    return klines


# ─── 基础 ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_extract_returns_none_when_no_kline(db, settings):
    ext = FeatureExtractor(db, config=settings.rules_defaults)
    snap = await ext.extract("XYZ", "30m")
    assert snap is None


@pytest.mark.asyncio
async def test_basic_kline_anchor_and_atr(db, settings):
    anchor = 1_700_000_000_000
    klines = await _seed_base(db, anchor_ts=anchor, n_klines=20, start_price=100.0, step=1.0)

    ext = FeatureExtractor(db, config=settings.rules_defaults)
    snap = await ext.extract("BTC", "30m")
    assert snap is not None
    assert snap.anchor_ts == anchor
    assert snap.last_price == klines[-1].close
    # 每根 high-low=0.6
    assert snap.atr is not None
    assert snap.atr == pytest.approx(0.6, abs=0.01)


# ─── VWAP / CVD / Imbalance 派生 ──────────────────────────


@pytest.mark.asyncio
async def test_vwap_slope_and_fair_value_delta(db, settings):
    anchor = 1_700_000_000_000
    await _seed_base(db, anchor_ts=anchor, n_klines=20, start_price=100.0, step=1.0)

    atoms = AtomRepositories(db)
    # vwap 从 90 涨到 110
    for i in range(10):
        await atoms.vwap.upsert(
            VwapPoint(symbol="BTC", tf="30m", ts=anchor - (9 - i) * _TF_MS, vwap=90.0 + i * 2.0)
        )

    ext = FeatureExtractor(db, config=settings.rules_defaults)
    snap = await ext.extract("BTC", "30m")
    assert snap is not None
    assert snap.vwap_last == pytest.approx(108.0)
    # last_price = 119, vwap = 108 → 正背离
    assert snap.fair_value_delta_pct is not None
    assert snap.fair_value_delta_pct > 0
    # slope (108-90)/90 = 0.2
    assert snap.vwap_slope == pytest.approx(0.2, abs=0.01)


@pytest.mark.asyncio
async def test_cvd_slope_sign(db, settings):
    anchor = 1_700_000_000_000
    await _seed_base(db, anchor_ts=anchor, n_klines=10)

    atoms = AtomRepositories(db)
    for i in range(10):
        await atoms.cvd.upsert(
            CvdPoint(symbol="BTC", tf="30m", ts=anchor - (9 - i) * _TF_MS, value=i * 100.0)
        )

    ext = FeatureExtractor(db, config=settings.rules_defaults)
    snap = await ext.extract("BTC", "30m")
    assert snap.cvd_slope_sign == "up"
    assert snap.cvd_slope == 900.0


@pytest.mark.asyncio
async def test_imbalance_ratio_sparse(db, settings):
    """imbalance 全 0 时 green/red ratio 都是 0（不被稀疏稀释）。"""
    anchor = 1_700_000_000_000
    await _seed_base(db, anchor_ts=anchor, n_klines=30)

    atoms = AtomRepositories(db)
    # 30 根全 0
    for i in range(30):
        await atoms.imbalance.upsert(
            ImbalancePoint(symbol="BTC", tf="30m", ts=anchor - (29 - i) * _TF_MS, value=0.0)
        )

    ext = FeatureExtractor(db, config=settings.rules_defaults)
    snap = await ext.extract("BTC", "30m")
    assert snap.imbalance_green_ratio == 0.0
    assert snap.imbalance_red_ratio == 0.0


@pytest.mark.asyncio
async def test_imbalance_ratio_nonzero_denominator(db, settings):
    """绿/红占比的分母是非零事件总数。"""
    anchor = 1_700_000_000_000
    await _seed_base(db, anchor_ts=anchor, n_klines=30)

    atoms = AtomRepositories(db)
    # 最近 8 根：5 绿 1 红 2 零 → 非零 6，绿 5/6，红 1/6
    values = [0.0] * 22 + [1.0, -1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0]
    for i, v in enumerate(values):
        await atoms.imbalance.upsert(
            ImbalancePoint(symbol="BTC", tf="30m", ts=anchor - (29 - i) * _TF_MS, value=v)
        )

    settings.rules_defaults["global"]["recent_window_bars"] = 8
    ext = FeatureExtractor(db, config=settings.rules_defaults)
    snap = await ext.extract("BTC", "30m")
    assert snap.imbalance_green_ratio == pytest.approx(5 / 6)
    assert snap.imbalance_red_ratio == pytest.approx(1 / 6)


# ─── POC shift / SmartMoney ───────────────────────────────


@pytest.mark.asyncio
async def test_poc_shift_trend_up(db, settings):
    anchor = 1_700_000_000_000
    await _seed_base(db, anchor_ts=anchor, n_klines=10)

    atoms = AtomRepositories(db)
    for i in range(10):
        await atoms.poc_shift.upsert(
            PocShiftPoint(
                symbol="BTC",
                tf="30m",
                ts=anchor - (9 - i) * _TF_MS,
                poc_price=100.0 + i * 1.0,
                volume=5.0,
            )
        )

    ext = FeatureExtractor(db, config=settings.rules_defaults)
    snap = await ext.extract("BTC", "30m")
    assert snap.poc_shift_trend == "up"
    assert snap.poc_shift_delta_pct == pytest.approx(9 / 100, abs=0.001)


@pytest.mark.asyncio
async def test_smart_money_ongoing_picked(db, settings):
    anchor = 1_700_000_000_000
    await _seed_base(db, anchor_ts=anchor, n_klines=5)

    atoms = AtomRepositories(db)
    await atoms.smart_money.upsert(
        SmartMoneySegment(
            symbol="BTC",
            tf="30m",
            start_time=anchor - 20 * _TF_MS,
            end_time=anchor - 10 * _TF_MS,
            avg_price=95.0,
            type="Accumulation",
            status="Completed",
        )
    )
    await atoms.smart_money.upsert(
        SmartMoneySegment(
            symbol="BTC",
            tf="30m",
            start_time=anchor - 5 * _TF_MS,
            end_time=anchor,
            avg_price=100.0,
            type="Accumulation",
            status="Ongoing",
        )
    )

    ext = FeatureExtractor(db, config=settings.rules_defaults)
    snap = await ext.extract("BTC", "30m")
    assert snap.smart_money_ongoing is not None
    assert snap.smart_money_ongoing.status == "Ongoing"
    assert snap.smart_money_ongoing.avg_price == 100.0
    assert len(snap.smart_money_all) == 2


# ─── 关键位 & 穿越 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_nearest_levels_and_pierce(db, settings):
    anchor = 1_700_000_000_000
    # 构造 K 线：前几根 close=99, 最后一根 close=102（穿越了 100）
    klines = _make_klines(anchor, n=10, start_price=95.0, step=0.5)
    # 人工制造穿越：倒数第 3 根 close=99, 倒数第 2 根 close=101
    klines[-3].close = 99.0
    klines[-2].close = 101.0
    klines[-1].close = 102.0
    await KlineRepository(db).upsert_many(klines)

    atoms = AtomRepositories(db)
    # 关键位 100（resistance 变 support）
    await atoms.hvn_nodes.replace_for(
        {"symbol": "BTC", "tf": "30m"},
        [HvnNode(symbol="BTC", tf="30m", rank=1, price=100.0, volume=1000.0)],
    )

    ext = FeatureExtractor(db, config=settings.rules_defaults)
    snap = await ext.extract("BTC", "30m")
    # last_price=102 → 100 变 support
    assert snap.nearest_support_price == 100.0
    # 刚穿越 resistance（99 → 101 穿过 100）
    assert snap.just_broke_resistance is True


# ─── 共振 / sweep ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_whale_net_direction(db, settings):
    anchor = 1_700_000_000_000
    await _seed_base(db, anchor_ts=anchor, n_klines=20)

    atoms = AtomRepositories(db)
    # 最近 8 根内 3 次 buy + 0 次 sell
    for i in range(3):
        await atoms.resonance_events.upsert(
            ResonanceEvent(
                symbol="BTC",
                tf="30m",
                ts=anchor - (i + 1) * _TF_MS,
                price=100.0,
                direction="buy",
                count=3,
                exchanges=["binance", "okx", "bybit"],
            )
        )

    settings.rules_defaults["global"]["recent_window_bars"] = 8
    ext = FeatureExtractor(db, config=settings.rules_defaults)
    snap = await ext.extract("BTC", "30m")
    assert snap.resonance_count_recent == 3
    assert snap.resonance_buy_count == 3
    assert snap.resonance_sell_count == 0
    assert snap.whale_net_direction == "buy"


# ─── 时间活跃度 ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_time_heatmap_active_session(db, settings):
    import datetime as dt

    anchor = int(dt.datetime(2026, 1, 1, 14, 0, tzinfo=dt.UTC).timestamp() * 1000)
    await _seed_base(db, anchor_ts=anchor, n_klines=5)

    atoms = AtomRepositories(db)
    hours = []
    for h in range(24):
        # hour 14 最活跃，其他低
        total = 100.0 if h == 14 else 10.0
        hours.append(
            TimeHeatmapHour(
                symbol="BTC", tf="30m", hour=h, accum=total / 2, dist=total / 2, total=total
            )
        )
    await atoms.time_heatmap.replace_for({"symbol": "BTC", "tf": "30m"}, hours)

    ext = FeatureExtractor(db, config=settings.rules_defaults)
    snap = await ext.extract("BTC", "30m")
    assert snap.active_session is True
    assert snap.current_hour_activity == pytest.approx(1.0)


# ─── Trend exhaustion / saturation / 杂项 ────────────────


@pytest.mark.asyncio
async def test_trend_exhaustion_and_saturation_last(db, settings):
    anchor = 1_700_000_000_000
    await _seed_base(db, anchor_ts=anchor, n_klines=5)

    atoms = AtomRepositories(db)
    await atoms.trend_exhaustion.upsert(
        TrendExhaustionPoint(
            symbol="BTC", tf="30m", ts=anchor, exhaustion=8, type="Distribution"
        )
    )
    await atoms.trend_saturation.upsert(
        TrendSaturationStat(
            symbol="BTC",
            tf="30m",
            type="Distribution",
            start_time=anchor - 100 * _TF_MS,
            avg_vol=100.0,
            current_vol=95.0,
            progress=95.0,
        )
    )

    ext = FeatureExtractor(db, config=settings.rules_defaults)
    snap = await ext.extract("BTC", "30m")
    assert snap.trend_exhaustion_last is not None
    assert snap.trend_exhaustion_last.exhaustion == 8
    assert snap.trend_saturation is not None
    assert snap.trend_saturation.progress == 95.0


@pytest.mark.asyncio
async def test_power_imbalance_picks_nonzero(db, settings):
    anchor = 1_700_000_000_000
    await _seed_base(db, anchor_ts=anchor, n_klines=5)

    atoms = AtomRepositories(db)
    # 最新一根 ratio=0，但倒数第 2 根 ratio=2.5
    await atoms.power_imbalance.upsert(
        PowerImbalancePoint(
            symbol="BTC", tf="30m", ts=anchor - _TF_MS, buy_vol=10, sell_vol=4, ratio=2.5
        )
    )
    await atoms.power_imbalance.upsert(
        PowerImbalancePoint(symbol="BTC", tf="30m", ts=anchor, buy_vol=0, sell_vol=0, ratio=0.0)
    )

    ext = FeatureExtractor(db, config=settings.rules_defaults)
    snap = await ext.extract("BTC", "30m")
    assert snap.power_imbalance_last is not None
    assert snap.power_imbalance_last.ratio == 2.5


# ─── 聚合列表 & stale ─────────────────────────────────────


@pytest.mark.asyncio
async def test_stale_tables_flag(db, settings):
    anchor = 1_700_000_000_000
    await _seed_base(db, anchor_ts=anchor, n_klines=5)
    # 只有 K 线，vwap/cvd/imbalance/poc 都没数据

    ext = FeatureExtractor(db, config=settings.rules_defaults)
    snap = await ext.extract("BTC", "30m")
    assert "atoms_vwap" in snap.stale_tables
    assert "atoms_cvd" in snap.stale_tables
    assert "atoms_imbalance" in snap.stale_tables
    assert "atoms_poc_shift" in snap.stale_tables


@pytest.mark.asyncio
async def test_absolute_zones_and_heatmap_loaded(db, settings):
    anchor = 1_700_000_000_000
    await _seed_base(db, anchor_ts=anchor, n_klines=5)

    atoms = AtomRepositories(db)
    await atoms.absolute_zones.upsert_many(
        [
            AbsoluteZone(
                symbol="BTC",
                tf="30m",
                start_time=anchor - 5 * _TF_MS,
                bottom_price=99,
                top_price=101,
                type="Accumulation",
            ),
        ]
    )
    await atoms.heatmap.replace_for(
        {"symbol": "BTC", "tf": "30m"},
        [
            HeatmapBand(
                symbol="BTC",
                tf="30m",
                start_time=anchor,
                price=110.0,
                intensity=0.8,
                type="Distribution",
            ),
        ],
    )

    ext = FeatureExtractor(db, config=settings.rules_defaults)
    snap = await ext.extract("BTC", "30m")
    assert len(snap.absolute_zones) == 1
    assert len(snap.heatmap) == 1
    assert snap.heatmap[0].intensity == 0.8
