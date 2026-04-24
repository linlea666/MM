"""RuleRunner 端到端单测。

策略：
- 用真实 SQLite（pytest 临时目录）+ 直接往 atoms_* / kline_* 写入 seed 数据
- 然后调 RuleRunner.run(symbol, tf) 验证 DashboardSnapshot 结构完整性
- 不依赖网络 / HFD client
"""

from __future__ import annotations

import pytest

from backend.core.config import load_settings
from backend.models import (
    AbsoluteZone,
    CvdPoint,
    HeatmapBand,
    HvnNode,
    ImbalancePoint,
    Kline,
    LiquiditySweepEvent,
    PowerImbalancePoint,
    ResonanceEvent,
    VwapPoint,
)
from backend.rules import NoDataError, RuleRunner
from backend.rules.runner import (
    _build_health,
    _build_timeline,
    _to_capability_dto,
)
from backend.rules.features import FeatureSnapshot
from backend.rules.scoring import score_accumulation
from backend.storage.repositories.atoms import AtomRepositories
from backend.storage.repositories.kline import KlineRepository


@pytest.fixture
def cfg():
    return load_settings().rules_defaults


def _kline_series(symbol: str, tf: str, n: int, start_price: float = 100.0) -> list[Kline]:
    """生成一段平稳上升的 K 线。"""
    out: list[Kline] = []
    for i in range(n):
        ts = 1_700_000_000_000 + i * 60_000
        p = start_price + i * 0.05
        out.append(
            Kline(
                symbol=symbol, tf=tf, ts=ts,
                open=p, high=p + 0.1, low=p - 0.1, close=p + 0.05,
                volume=100.0, source="binance",
            )
        )
    return out


# ─── TimelineEvent ─────────────────────────────


def test_build_timeline_sorts_and_limits():
    snap = FeatureSnapshot(
        symbol="BTC", tf="30m", anchor_ts=1000, last_price=100.0,
        sweep_last=LiquiditySweepEvent(
            symbol="BTC", tf="30m", ts=900, price=100.0, type="bearish_sweep", volume=10,
        ),
        sweep_count_recent=1,
        resonance_recent=[
            ResonanceEvent(symbol="BTC", tf="30m", ts=800, price=99.0, direction="buy", count=2, exchanges=["a", "b"]),
            ResonanceEvent(symbol="BTC", tf="30m", ts=950, price=101.0, direction="sell", count=3, exchanges=["a", "b", "c"]),
        ],
        power_imbalance_last=PowerImbalancePoint(
            symbol="BTC", tf="30m", ts=700, buy_vol=10, sell_vol=4, ratio=2.5,
        ),
        just_broke_resistance=True,
    )
    events = _build_timeline(snap, limit=8)
    # 按 ts 降序
    ts_list = [e.ts for e in events]
    assert ts_list == sorted(ts_list, reverse=True)
    # 覆盖 sweep / resonance / power_imbalance / breakout 各类
    kinds = {e.kind for e in events}
    assert {"sweep", "resonance", "power_imbalance", "breakout"} <= kinds


def test_build_timeline_respects_limit():
    snap = FeatureSnapshot(
        symbol="BTC", tf="30m", anchor_ts=1000, last_price=100.0,
        resonance_recent=[
            ResonanceEvent(symbol="BTC", tf="30m", ts=i, price=100.0,
                           direction="buy", count=1, exchanges=["a"])
            for i in range(20)
        ],
    )
    events = _build_timeline(snap, limit=5)
    assert len(events) == 5


def test_build_timeline_empty_on_quiet_snap():
    snap = FeatureSnapshot(symbol="BTC", tf="30m", anchor_ts=1000, last_price=100.0)
    events = _build_timeline(snap)
    assert events == []


# ─── Health ─────────────────────────────


def test_build_health_fresh():
    snap = FeatureSnapshot(symbol="BTC", tf="30m", anchor_ts=5000, last_price=100.0)
    h = _build_health(snap, now_ms=6000)
    assert h.fresh is True
    assert h.last_collector_ts == 5000
    assert h.stale_seconds == 1
    assert h.warnings == []


def test_build_health_stale_tables():
    snap = FeatureSnapshot(
        symbol="BTC", tf="30m", anchor_ts=1000, last_price=100.0,
        stale_tables=["atoms_cvd", "atoms_imbalance"],
    )
    h = _build_health(snap, now_ms=61_000)
    assert h.fresh is False
    assert len(h.warnings) == 2
    assert h.stale_seconds == 60


# ─── capability DTO 转换 ─────────────────────────────


def test_to_capability_dto_translates_fields(cfg):
    snap = FeatureSnapshot(
        symbol="BTC", tf="30m", anchor_ts=1000, last_price=100.0,
        vwap_last=99.0, vwap_slope=0.02,
        imbalance_green_ratio=0.9,
        cvd_slope=500.0, cvd_slope_sign="up",
    )
    cap = score_accumulation(snap, cfg)
    dto = _to_capability_dto(cap)
    assert dto.name == "accumulation"
    assert isinstance(dto.score, int)
    assert 0 <= dto.confidence <= 1
    assert all(isinstance(e, str) for e in dto.evidences)
    assert "band=" in (dto.notes or "")


# ─── 端到端 run() ─────────────────────────────


@pytest.mark.asyncio
async def test_runner_no_data_raises(db, settings):
    runner = RuleRunner(db, config=settings.rules_defaults)
    with pytest.raises(NoDataError):
        await runner.run("BTC", "30m")


@pytest.mark.asyncio
async def test_runner_full_pipeline(db, settings):
    cfg = settings.rules_defaults
    """最小种子：只写 kline + 一点 atoms 让 extractor 能产出 snapshot。"""
    symbol, tf = "BTC", "30m"
    klines = _kline_series(symbol, tf, n=50, start_price=100.0)

    kline_repo = KlineRepository(db)
    await kline_repo.upsert_many(klines)

    atoms = AtomRepositories(db)
    # VWAP 与 K 线同步，保证 extractor 可以算斜率
    await atoms.vwap.upsert_many([
        VwapPoint(symbol=symbol, tf=tf, ts=k.ts, vwap=k.close - 0.02)
        for k in klines
    ])
    # CVD 单调上升
    await atoms.cvd.upsert_many([
        CvdPoint(symbol=symbol, tf=tf, ts=k.ts, value=i * 10.0)
        for i, k in enumerate(klines)
    ])
    await atoms.imbalance.upsert_many([
        ImbalancePoint(symbol=symbol, tf=tf, ts=k.ts, value=1.0)
        for k in klines[-20:]
    ])
    await atoms.hvn_nodes.upsert_many([
        HvnNode(symbol=symbol, tf=tf, rank=1, price=99.5, volume=1000),
        HvnNode(symbol=symbol, tf=tf, rank=2, price=102.5, volume=900),
    ])
    await atoms.absolute_zones.upsert_many([
        AbsoluteZone(
            symbol=symbol, tf=tf, start_time=klines[-1].ts,
            bottom_price=99.3, top_price=99.7, type="Accumulation",
        ),
    ])
    await atoms.heatmap.upsert_many([
        HeatmapBand(
            symbol=symbol, tf=tf, start_time=klines[-1].ts,
            price=103.0, intensity=0.7, type="Distribution",
        ),
    ])

    runner = RuleRunner(db, config=cfg)
    dash = await runner.run(symbol, tf)

    # 顶层字段齐全
    assert dash.symbol == symbol and dash.tf == tf
    assert dash.current_price > 0
    assert dash.timestamp == klines[-1].ts

    # Hero
    assert dash.hero.action_conclusion
    assert 0 <= dash.hero.stars <= 5

    # 行为 / 阶段 / 参与
    assert dash.behavior.main
    assert dash.phase.current
    assert dash.participation.level

    # 关键位能拿到至少一档
    assert dash.levels.s1 is not None or dash.levels.r1 is not None

    # 4 个 capability DTO
    names = {c.name for c in dash.capability_scores}
    assert names == {"accumulation", "distribution", "breakout", "reversal"}

    # Plans 至少 1 条
    assert len(dash.plans) >= 1

    # AI 观察 V1 留空
    assert dash.ai_observations == []

    # Pydantic 序列化校验
    payload = dash.model_dump(mode="json")
    assert payload["symbol"] == symbol
    assert "hero" in payload and "levels" in payload
