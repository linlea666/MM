"""CollectorEngine 集成测试：mock HFD/Exchange，断言写库效果。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from backend.collector.engine import CollectorEngine
from backend.collector.exchange_client import ExchangeClient
from backend.collector.hfd_client import HFDClient
from backend.models import Kline
from backend.storage.repositories import AtomRepositories, KlineRepository

SAMPLES = Path(__file__).resolve().parents[2] / "docs" / "upstream-api" / "samples"


def _load_sample(name: str) -> dict:
    return json.loads((SAMPLES / f"{name}.sample.json").read_text())


@pytest.fixture
def engine(db, settings):
    hfd = AsyncMock(spec=HFDClient)

    async def fake_fetch(*, symbol, indicator, tf):
        return _load_sample(indicator)

    hfd.fetch.side_effect = fake_fetch

    exchange = AsyncMock(spec=ExchangeClient)

    async def fake_klines(*, symbol, tf, limit):
        return [
            Kline(
                symbol=symbol, tf=tf, ts=1_700_000_000_000 + i * 1_800_000,
                open=100 + i, high=101 + i, low=99 + i, close=100.5 + i,
                volume=10.0 + i, source="binance",
            )
            for i in range(5)
        ]

    exchange.fetch_klines.side_effect = fake_klines

    kline_repo = KlineRepository(db)
    atoms = AtomRepositories(db)
    return CollectorEngine(
        settings=settings, hfd=hfd, exchange=exchange,
        kline_repo=kline_repo, atoms=atoms,
    )


@pytest.mark.asyncio
async def test_tick_kline_close_writes_klines_and_atoms(engine, configured_logging, db):
    await engine.tick_kline_close("BTC", "30m")
    # K 线
    n_kline = await db.fetch_scalar(
        "SELECT COUNT(1) FROM atoms_klines WHERE symbol=? AND tf=?", ("BTC", "30m")
    )
    assert n_kline == 5
    # kline_close tier 8 个 indicator 至少产出若干原子；这里检查最少拆出了
    # power_imbalance / trailing_vwap / trend_exhaustion / sweep / resonance 各自表
    for table in (
        "atoms_power_imbalance",
        "atoms_trailing_vwap",
        "atoms_trend_exhaustion",
        "atoms_sweep_events",
        "atoms_resonance_events",
        "atoms_poc_shift",
        "atoms_micro_poc",
        "atoms_cvd",
    ):
        n = await db.fetch_scalar(f"SELECT COUNT(1) FROM {table}")
        assert n > 0, f"{table} 空"


@pytest.mark.asyncio
async def test_tick_periodic_every_30min(engine, configured_logging, db):
    await engine.tick_periodic("BTC", "30m", "every_30min")
    for table in (
        "atoms_smart_money",
        "atoms_order_blocks",
        "atoms_trend_purity",
        "atoms_absolute_zones",
    ):
        n = await db.fetch_scalar(f"SELECT COUNT(1) FROM {table}")
        assert n > 0, f"{table} 空"


@pytest.mark.asyncio
async def test_tick_periodic_every_1h_replace_for_fuel(engine, configured_logging, db):
    """liquidation_fuel 应按 replace_for 做全量覆盖。"""
    await engine.tick_periodic("BTC", "1h", "every_1h")
    n1 = await db.fetch_scalar(
        "SELECT COUNT(1) FROM atoms_liquidation_fuel WHERE symbol=? AND tf=?",
        ("BTC", "1h"),
    )
    assert n1 > 0
    # 再跑一轮，应当仍然是同样数量（覆盖而非追加）
    await engine.tick_periodic("BTC", "1h", "every_1h")
    n2 = await db.fetch_scalar(
        "SELECT COUNT(1) FROM atoms_liquidation_fuel WHERE symbol=? AND tf=?",
        ("BTC", "1h"),
    )
    assert n1 == n2


@pytest.mark.asyncio
async def test_collect_once_covers_all_tiers(engine, configured_logging, db):
    await engine.collect_once("BTC", tfs=["30m"])
    # 至少 10 张 atoms 表有数据
    rows = await db.fetchall(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'atoms_%'"
    )
    tables = [r["name"] for r in rows]
    populated = 0
    for t in tables:
        n = await db.fetch_scalar(f"SELECT COUNT(1) FROM {t}")
        if n and n > 0:
            populated += 1
    assert populated >= 12, f"populated={populated}/{len(tables)}"


@pytest.mark.asyncio
async def test_hfd_failure_does_not_break_batch(engine, configured_logging, db):
    """部分 indicator 失败不影响其它。"""

    original_fetch = engine._hfd.fetch.side_effect

    async def flaky(*, symbol, indicator, tf):
        if indicator == "smart_money_cost":
            raise RuntimeError("boom")
        return await original_fetch(symbol=symbol, indicator=indicator, tf=tf)

    engine._hfd.fetch.side_effect = flaky
    await engine.tick_periodic("BTC", "30m", "every_30min")
    # 除 smart_money 外仍应有写入
    n_sm = await db.fetch_scalar("SELECT COUNT(1) FROM atoms_smart_money")
    assert n_sm == 0
    n_ob = await db.fetch_scalar("SELECT COUNT(1) FROM atoms_order_blocks")
    assert n_ob > 0
