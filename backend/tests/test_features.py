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
    CascadeBand,
    ChochEvent,
    CvdPoint,
    DdToleranceSegment,
    HeatmapBand,
    HvnNode,
    ImbalancePoint,
    Kline,
    MicroPocSegment,
    OrderBlock,
    PainDrawdownSegment,
    PocShiftPoint,
    PowerImbalancePoint,
    ResonanceEvent,
    RetailStopBand,
    RoiSegment,
    SmartMoneySegment,
    TimeHeatmapHour,
    TimeWindowSegment,
    TrendExhaustionPoint,
    TrendSaturationStat,
    VolumeProfileBucket,
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


# ─── V1.1 · Stage 0：沉睡资产激活 ────────────────────────────


@pytest.mark.asyncio
async def test_time_heatmap_view_peak_and_dead_hours(db, settings):
    """Time Heatmap 派生视图应给出 current_rank / peak_hours / dead_hours。"""
    import datetime as dt

    anchor = int(dt.datetime(2026, 1, 1, 14, 0, tzinfo=dt.UTC).timestamp() * 1000)
    await _seed_base(db, anchor_ts=anchor, n_klines=5)

    atoms = AtomRepositories(db)
    # 构造 peak = [14, 15, 13]（rank 1/2/3）；dead = [3, 4]（最冷）
    totals = [10.0] * 24
    totals[14] = 100.0
    totals[15] = 90.0
    totals[13] = 80.0
    totals[3] = 1.0
    totals[4] = 2.0
    hours = [
        TimeHeatmapHour(symbol="BTC", tf="30m", hour=h, accum=t / 2, dist=t / 2, total=t)
        for h, t in enumerate(totals)
    ]
    await atoms.time_heatmap.replace_for({"symbol": "BTC", "tf": "30m"}, hours)

    ext = FeatureExtractor(db, config=settings.rules_defaults)
    snap = await ext.extract("BTC", "30m")
    view = snap.time_heatmap_view
    assert view is not None
    assert view.current_hour == 14
    assert view.current_rank == 1
    assert view.current_activity == pytest.approx(1.0)
    assert view.is_active_session is True
    assert view.peak_hours[:3] == [14, 15, 13]
    # 最冷两个小时 ranking 上应是 3、4（顺序由实现决定，取集合对比更稳健）
    assert set(view.dead_hours) == {3, 4}


@pytest.mark.asyncio
async def test_time_heatmap_view_none_without_data(db, settings):
    anchor = 1_700_000_000_000
    await _seed_base(db, anchor_ts=anchor, n_klines=5)
    ext = FeatureExtractor(db, config=settings.rules_defaults)
    snap = await ext.extract("BTC", "30m")
    assert snap.time_heatmap_view is None
    # 旧字段保持向后兼容
    assert snap.current_hour_activity == 0.0
    assert snap.active_session is False


@pytest.mark.asyncio
async def test_volume_profile_view_basic(db, settings):
    """筹码分布派生：POC / VA 70% / TopN / last_price 位置。"""
    anchor = 1_700_000_000_000
    # 构造一条递增 K 线，last_price ≈ 102.0（5 根 start=100 step=0.5 → 100/100.5/101/101.5/102）
    await _seed_base(db, anchor_ts=anchor, n_klines=5)

    atoms = AtomRepositories(db)
    # 构造 11 个价格桶，POC 在 101（total 最高），两侧递减，total 合计 100
    # total 分布：[1,2,3,5,8,20,8,5,3,2,1]
    volumes = [1.0, 2.0, 3.0, 5.0, 8.0, 20.0, 8.0, 5.0, 3.0, 2.0, 1.0]
    prices = [99.0 + 0.5 * i for i in range(11)]
    buckets = [
        VolumeProfileBucket(
            symbol="BTC", tf="30m", price=p,
            accum=v * 0.6, dist=v * 0.4, total=v,
        )
        for p, v in zip(prices, volumes)
    ]
    await atoms.volume_profile.replace_for({"symbol": "BTC", "tf": "30m"}, buckets)

    ext = FeatureExtractor(db, config=settings.rules_defaults)
    snap = await ext.extract("BTC", "30m")
    vp = snap.volume_profile
    assert vp is not None
    # POC：101.5（index=5，total=20）
    assert vp.poc_price == pytest.approx(101.5)
    assert vp.poc_total == pytest.approx(20.0)
    # 总量
    assert vp.total_volume == pytest.approx(sum(volumes))
    # VA 覆盖 ≥ 70%
    assert vp.value_area_volume_ratio >= 0.70
    # VA 边界应包 POC
    assert vp.value_area_low <= vp.poc_price <= vp.value_area_high
    # TopN：默认 5，按 total 降序
    assert len(vp.top_nodes) == 5
    assert vp.top_nodes[0].price == pytest.approx(101.5)
    # 最新价 102.0 应落在 VA 内（20 在 101.5，8 在 101/102；VA 一定覆盖到 102）
    assert vp.last_price_position == "in_va"
    # POC 距离：当前价 102，POC 101.5 → 约 -0.49%
    assert vp.poc_distance_pct == pytest.approx((101.5 - 102.0) / 102.0, rel=1e-3)
    # 主动方向：accum/dist = 0.6/0.4 → "buy"
    assert vp.top_nodes[0].dominant_side == "buy"


@pytest.mark.asyncio
async def test_volume_profile_view_none_without_data(db, settings):
    anchor = 1_700_000_000_000
    await _seed_base(db, anchor_ts=anchor, n_klines=5)
    ext = FeatureExtractor(db, config=settings.rules_defaults)
    snap = await ext.extract("BTC", "30m")
    assert snap.volume_profile is None


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


# ════════════════════════════════════════════════════════════════════
# V1.1 扩展：7 个新指标的数字化视图单测
# ════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_v11_choch_latest_view_distance_and_kind(db, settings):
    """⚡ CHoCH 最新事件 → ChochLatestView：距离、kind、direction 都要正确映射。"""
    anchor = 1_700_000_000_000
    # 构造 last_price ≈ 114（step=0.5, n=30 → last=100 + 14*0.5=107; 用 step=1 更清楚）
    klines = _make_klines(anchor, 30, start_price=100.0, step=1.0)
    await KlineRepository(db).upsert_many(klines)
    last_price = klines[-1].close

    atoms = AtomRepositories(db)
    # 老事件（4 根 K 线之前），再一条最新事件（当前 K 线）
    await atoms.choch_events.upsert_many([
        ChochEvent(
            symbol="BTC", tf="30m",
            ts=anchor - 4 * _TF_MS,
            price=last_price - 3.0,
            level_price=last_price - 2.0,
            origin_ts=anchor - 40 * _TF_MS,
            type="BOS_Bullish",
        ),
        ChochEvent(
            symbol="BTC", tf="30m",
            ts=anchor,
            price=last_price - 0.5,
            level_price=last_price + 5.0,   # 防线在上方 → distance_pct > 0
            origin_ts=anchor - 20 * _TF_MS,
            type="CHoCH_Bearish",
        ),
    ])

    ext = FeatureExtractor(db, config=settings.rules_defaults)
    snap = await ext.extract("BTC", "30m")
    assert len(snap.choch_recent) == 2
    latest = snap.choch_latest
    assert latest is not None
    assert latest.type == "CHoCH_Bearish"
    assert latest.kind == "CHoCH"
    assert latest.direction == "bearish"
    assert latest.is_choch is True
    # 防线在上方：distance_pct 正值，约 5/last_price
    assert latest.distance_pct == pytest.approx(5.0 / last_price, rel=1e-3)
    assert latest.bars_since == 0  # 最新事件 ts 就是 anchor


@pytest.mark.asyncio
async def test_v11_cascade_bands_topn_and_side_mapping(db, settings):
    """💣 爆仓带 TopN：每侧最多 N 条，按 signal_count DESC 排；side 映射正确。"""
    anchor = 1_700_000_000_000
    await _seed_base(db, anchor_ts=anchor, n_klines=5, start_price=100.0, step=1.0)
    last_price = 100.0 + 4 * 1.0  # 104

    atoms = AtomRepositories(db)
    # Accumulation 下方 3 条，signal_count 不同
    # Distribution 上方 3 条
    bands = [
        CascadeBand(symbol="BTC", tf="30m", start_time=anchor - 5 * _TF_MS,
                    bottom_price=98, top_price=100, avg_price=99,
                    volume=5.0, signal_count=10, type="Accumulation"),
        CascadeBand(symbol="BTC", tf="30m", start_time=anchor - 4 * _TF_MS,
                    bottom_price=95, top_price=97, avg_price=96,
                    volume=3.0, signal_count=5, type="Accumulation"),
        CascadeBand(symbol="BTC", tf="30m", start_time=anchor - 3 * _TF_MS,
                    bottom_price=92, top_price=94, avg_price=93,
                    volume=1.0, signal_count=2, type="Accumulation"),
        CascadeBand(symbol="BTC", tf="30m", start_time=anchor - 2 * _TF_MS,
                    bottom_price=108, top_price=110, avg_price=109,
                    volume=6.0, signal_count=8, type="Distribution"),
        CascadeBand(symbol="BTC", tf="30m", start_time=anchor - 1 * _TF_MS,
                    bottom_price=112, top_price=114, avg_price=113,
                    volume=4.0, signal_count=4, type="Distribution"),
        CascadeBand(symbol="BTC", tf="30m", start_time=anchor,
                    bottom_price=116, top_price=118, avg_price=117,
                    volume=2.0, signal_count=1, type="Distribution"),
    ]
    await atoms.cascade_bands.replace_for({"symbol": "BTC", "tf": "30m"}, bands)

    # TopN=2 → 每侧 2 条，共 4 条
    settings.rules_defaults["global"]["band_topn"] = 2
    ext = FeatureExtractor(db, config=settings.rules_defaults)
    snap = await ext.extract("BTC", "30m")

    views = snap.cascade_bands
    assert len(views) == 4  # 2 + 2
    longs = [v for v in views if v.side == "long_fuel"]
    shorts = [v for v in views if v.side == "short_fuel"]
    assert len(longs) == 2 and len(shorts) == 2
    # Accumulation → long_fuel，signal_count DESC 前 2：10, 5
    assert [v.signal_count for v in longs] == [10, 5]
    # Distribution → short_fuel，signal_count DESC 前 2：8, 4
    assert [v.signal_count for v in shorts] == [8, 4]
    # above_price 检查：long_fuel 在下方（<104），short_fuel 在上方（>104）
    assert all(v.above_price is False for v in longs)
    assert all(v.above_price is True for v in shorts)
    # distance_pct 带正负
    assert all(v.distance_pct < 0 for v in longs)
    assert all(v.distance_pct > 0 for v in shorts)


@pytest.mark.asyncio
async def test_v11_retail_stop_bands_volume_ordering(db, settings):
    """散户止损带 TopN：按 volume DESC（颜色深浅）排；signal_count 应为 None。"""
    anchor = 1_700_000_000_000
    await _seed_base(db, anchor_ts=anchor, n_klines=5, start_price=100.0, step=1.0)

    atoms = AtomRepositories(db)
    bands = [
        RetailStopBand(symbol="BTC", tf="30m", start_time=anchor - 3 * _TF_MS,
                       bottom_price=95, top_price=97, avg_price=96,
                       volume=2.0, type="Accumulation"),
        RetailStopBand(symbol="BTC", tf="30m", start_time=anchor - 2 * _TF_MS,
                       bottom_price=92, top_price=94, avg_price=93,
                       volume=8.0, type="Accumulation"),
        RetailStopBand(symbol="BTC", tf="30m", start_time=anchor - 1 * _TF_MS,
                       bottom_price=108, top_price=110, avg_price=109,
                       volume=5.0, type="Distribution"),
    ]
    await atoms.retail_stop_bands.replace_for({"symbol": "BTC", "tf": "30m"}, bands)

    settings.rules_defaults["global"]["band_topn"] = 5
    ext = FeatureExtractor(db, config=settings.rules_defaults)
    snap = await ext.extract("BTC", "30m")

    views = snap.retail_stop_bands
    longs = [v for v in views if v.side == "long_fuel"]
    shorts = [v for v in views if v.side == "short_fuel"]
    # volume DESC：深色带排前面
    assert [v.volume for v in longs] == [8.0, 2.0]
    assert [v.volume for v in shorts] == [5.0]
    # retail 视图无 signal_count
    assert all(v.signal_count is None for v in views)


@pytest.mark.asyncio
async def test_v11_segment_portrait_best_effort_partial(db, settings):
    """波段四维画像 best_effort：ROI + Pain 有、Time 与 DdTolerance 缺 → sources 只有 2 维。"""
    anchor = 1_700_000_000_000
    await _seed_base(db, anchor_ts=anchor, n_klines=5, start_price=100.0, step=1.0)

    atoms = AtomRepositories(db)
    start_time = anchor - 10 * _TF_MS
    await atoms.roi_segments.upsert(
        RoiSegment(
            symbol="BTC", tf="30m",
            start_time=start_time, end_time=anchor,
            avg_price=100.0, limit_avg_price=108.0, limit_max_price=115.0,
            type="Accumulation", status="Ongoing",
        )
    )
    await atoms.pain_drawdown.upsert(
        PainDrawdownSegment(
            symbol="BTC", tf="30m",
            start_time=start_time, end_time=anchor,
            avg_price=100.0, pain_avg_price=96.0, pain_max_price=92.0,
            type="Accumulation", status="Ongoing",
        )
    )

    ext = FeatureExtractor(db, config=settings.rules_defaults)
    snap = await ext.extract("BTC", "30m")

    portrait = snap.segment_portrait
    assert portrait is not None
    assert portrait.sources == ["roi", "pain"]
    assert portrait.status == "Ongoing"
    assert portrait.type == "Accumulation"
    assert portrait.roi_limit_max_price == pytest.approx(115.0)
    assert portrait.pain_max_price == pytest.approx(92.0)
    # Time / DdTolerance 维度缺失 → 对应字段 None / 0
    assert portrait.time_max_ts is None
    assert portrait.bars_to_max is None
    assert portrait.dd_limit_pct is None
    assert portrait.dd_pierce_count == 0


@pytest.mark.asyncio
async def test_v11_segment_portrait_full_four_dimensions(db, settings):
    """波段四维画像全维度：ROI + Pain + Time + DdTolerance。"""
    anchor = 1_700_000_000_000
    await _seed_base(db, anchor_ts=anchor, n_klines=5, start_price=100.0, step=1.0)

    atoms = AtomRepositories(db)
    start_time = anchor - 10 * _TF_MS
    await atoms.roi_segments.upsert(
        RoiSegment(
            symbol="BTC", tf="30m",
            start_time=start_time, end_time=anchor,
            avg_price=100.0, limit_avg_price=108.0, limit_max_price=115.0,
            type="Distribution", status="Ongoing",
        )
    )
    await atoms.pain_drawdown.upsert(
        PainDrawdownSegment(
            symbol="BTC", tf="30m",
            start_time=start_time, end_time=anchor,
            avg_price=100.0, pain_avg_price=104.0, pain_max_price=108.0,
            type="Distribution", status="Ongoing",
        )
    )
    # Time：死亡线在未来 4 根 K 线处，avg 在未来 2 根
    avg_ts = anchor + 2 * _TF_MS
    max_ts = anchor + 4 * _TF_MS
    await atoms.time_windows.upsert(
        TimeWindowSegment(
            symbol="BTC", tf="30m",
            start_time=start_time, end_time=anchor,
            last_update_time=anchor,
            avg_price=100.0,
            limit_avg_time=avg_ts, limit_max_time=max_ts,
            type="Distribution", status="Ongoing",
        )
    )
    await atoms.dd_tolerance.upsert(
        DdToleranceSegment(
            symbol="BTC", tf="30m",
            id=42,
            start_time=start_time, end_time=anchor,
            limit_pct=0.035,
            status="Ongoing",
            trailing_line=[
                [anchor - 3 * _TF_MS, 98.5],
                [anchor - 1 * _TF_MS, 99.5],
                [anchor, 100.2],          # 最新一点
            ],
            pierces=[[anchor - 20 * _TF_MS, 95.0]],
        )
    )

    ext = FeatureExtractor(db, config=settings.rules_defaults)
    snap = await ext.extract("BTC", "30m")

    portrait = snap.segment_portrait
    assert portrait is not None
    assert set(portrait.sources) == {"roi", "pain", "time", "dd_tolerance"}
    assert portrait.roi_limit_max_price == pytest.approx(115.0)
    assert portrait.pain_max_price == pytest.approx(108.0)
    assert portrait.time_avg_ts == avg_ts
    assert portrait.time_max_ts == max_ts
    assert portrait.bars_to_avg == 2
    assert portrait.bars_to_max == 4
    assert portrait.dd_limit_pct == pytest.approx(0.035)
    # trailing_line 的最新点（ts=anchor）→ price=100.2
    assert portrait.dd_trailing_current == pytest.approx(100.2)
    assert portrait.dd_pierce_count == 1
