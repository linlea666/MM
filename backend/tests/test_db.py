"""验证 SQLite 初始化、PRAGMA、原子表 upsert。"""

from __future__ import annotations

from backend.models import Kline
from backend.storage.db import Database
from backend.storage.repositories import KlineRepository, SubscriptionRepository


async def test_schema_applied(db: Database) -> None:
    rows = await db.fetchall(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    names = {r["name"] for r in rows}

    expected_atoms = {
        "atoms_klines", "atoms_cvd", "atoms_imbalance", "atoms_inst_vol",
        "atoms_vwap", "atoms_poc_shift", "atoms_trailing_vwap",
        "atoms_power_imbalance", "atoms_trend_exhaustion",
        "atoms_smart_money", "atoms_order_blocks", "atoms_absolute_zones",
        "atoms_micro_poc", "atoms_trend_purity",
        "atoms_resonance_events", "atoms_sweep_events",
        "atoms_heatmap", "atoms_vacuum", "atoms_liquidation_fuel",
        "atoms_hvn_nodes", "atoms_volume_profile",
        "atoms_time_heatmap", "atoms_trend_saturation",
    }
    assert expected_atoms.issubset(names), f"缺表: {expected_atoms - names}"
    assert {"subscriptions", "schema_meta", "dashboard_snapshots"} <= names
    assert "logs" not in names, "logs 表应已迁出主库到 mm-logs.sqlite"


async def test_pragma_wal_mode(db: Database) -> None:
    val = await db.fetch_scalar("PRAGMA journal_mode")
    assert str(val).lower() == "wal"


async def test_schema_meta_version(db: Database) -> None:
    v = await db.fetch_scalar("SELECT value FROM schema_meta WHERE key='schema_version'")
    # v3: atoms_trend_exhaustion.exhaustion -> REAL + atoms_smart_money.end_time 允许 NULL
    # v4: V1.1 扩展 7 张原子表（choch_events / roi_segments / pain_drawdown /
    #     time_windows / dd_tolerance / cascade_bands / retail_stop_bands）
    assert v == "4"


async def test_kline_upsert_overrides(db: Database) -> None:
    repo = KlineRepository(db)
    k1 = Kline(
        symbol="BTC", tf="30m", ts=1700000000000,
        open=60000, high=60500, low=59800, close=60200, volume=10,
    )
    await repo.upsert(k1)
    assert await repo.count("BTC", "30m") == 1

    k2 = Kline(
        symbol="BTC", tf="30m", ts=1700000000000,
        open=60000, high=60800, low=59700, close=60500, volume=20,
    )
    await repo.upsert(k2)
    assert await repo.count("BTC", "30m") == 1

    latest = await repo.latest("BTC", "30m")
    assert latest is not None
    assert latest.close == 60500
    assert latest.volume == 20


async def test_kline_upsert_many(db: Database) -> None:
    repo = KlineRepository(db)
    klines = [
        Kline(symbol="BTC", tf="1h", ts=1700000000000 + i * 3600_000,
              open=60000 + i, high=60100 + i, low=59900 + i,
              close=60050 + i, volume=10 + i)
        for i in range(5)
    ]
    n = await repo.upsert_many(klines)
    assert n == 5
    assert await repo.count("BTC", "1h") == 5
    rng = await repo.fetch_range("BTC", "1h")
    assert [k.close for k in rng] == [60050 + i for i in range(5)]


async def test_subscription_init_default(db: Database) -> None:
    repo = SubscriptionRepository(db)
    seeded = await repo.ensure_defaults(["BTC"])
    assert [s.symbol for s in seeded] == ["BTC"]
    again = await repo.ensure_defaults(["BTC", "ETH"])  # 不应再插入
    assert [s.symbol for s in again] == ["BTC"]


async def test_subscription_add_dedupe_and_remove(db: Database) -> None:
    from backend.core.exceptions import (
        SymbolAlreadyExistsError,
        SymbolNotFoundError,
    )

    repo = SubscriptionRepository(db)
    await repo.add("BTC")
    await repo.add("eth")  # 自动大写
    all_subs = await repo.list_all()
    assert [s.symbol for s in all_subs] == ["BTC", "ETH"]
    assert all(s.active for s in all_subs)

    try:
        await repo.add("BTC")
        raise AssertionError("应该抛 SymbolAlreadyExistsError")
    except SymbolAlreadyExistsError:
        pass

    await repo.set_active("ETH", False)
    eth = await repo.get("ETH")
    assert eth is not None and eth.active is False
    actives = await repo.list_active()
    assert [s.symbol for s in actives] == ["BTC"]

    await repo.remove("ETH")
    assert await repo.get("ETH") is None

    try:
        await repo.remove("DOGE")
        raise AssertionError("应该抛 SymbolNotFoundError")
    except SymbolNotFoundError:
        pass


async def test_subscription_normalize_rejects_invalid(db: Database) -> None:
    from backend.core.exceptions import SubscriptionError

    repo = SubscriptionRepository(db)
    for bad in ["", "  ", "BTC-USD", "B" * 17]:
        try:
            await repo.add(bad)
            raise AssertionError(f"{bad!r} 不应被接受")
        except SubscriptionError:
            pass
