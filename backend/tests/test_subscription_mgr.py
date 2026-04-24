"""SubscriptionManager 测试：mock HFD probe + Exchange exists。"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from backend.collector.engine import CollectorEngine
from backend.collector.exchange_client import ExchangeClient
from backend.collector.hfd_client import HFDClient
from backend.collector.scheduler import CollectorScheduler
from backend.collector.subscription_mgr import SubscriptionManager
from backend.core.exceptions import (
    SubscriptionError,
    SymbolAlreadyExistsError,
    SymbolNotFoundError,
)
from backend.storage.repositories import SubscriptionRepository


@pytest.fixture
def sub_mgr(db, settings):
    hfd = AsyncMock(spec=HFDClient)
    hfd.probe = AsyncMock(return_value=True)
    exchange = AsyncMock(spec=ExchangeClient)
    exchange.symbol_exists = AsyncMock(return_value=True)
    engine = AsyncMock(spec=CollectorEngine)
    engine.collect_once = AsyncMock(return_value={"symbol": "X", "tfs": []})
    scheduler = CollectorScheduler(settings=settings, engine=engine)
    repo = SubscriptionRepository(db)
    mgr = SubscriptionManager(
        repo=repo, hfd=hfd, exchange=exchange,
        scheduler=scheduler, engine=engine,
    )
    return mgr, scheduler, repo, hfd, exchange, engine


@pytest.mark.asyncio
async def test_startup_seeds_and_activates(sub_mgr, configured_logging):
    mgr, scheduler, repo, *_ = sub_mgr
    scheduler.start()
    try:
        active = await mgr.startup(["BTC", "ETH"])
        assert {s.symbol for s in active} == {"BTC", "ETH"}
        jobs = scheduler.list_jobs()
        # 每币 15 job
        assert len(jobs) == 2 * 15
    finally:
        scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_add_triggers_collect_once(sub_mgr, configured_logging):
    mgr, scheduler, repo, hfd, exchange, engine = sub_mgr
    scheduler.start()
    try:
        sub = await mgr.add("SOL")
        assert sub.symbol == "SOL"
        assert sub.active
        # 异步任务可能还没跑，等一拍
        await asyncio.sleep(0.05)
        engine.collect_once.assert_awaited()
        exchange.symbol_exists.assert_awaited_once()
        hfd.probe.assert_awaited_once()
        assert len(scheduler.list_jobs()) == 15
    finally:
        scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_add_rejects_duplicate(sub_mgr, configured_logging):
    mgr, scheduler, *_ = sub_mgr
    scheduler.start()
    try:
        await mgr.add("SOL")
        with pytest.raises(SymbolAlreadyExistsError):
            await mgr.add("SOL")
    finally:
        scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_add_rejects_unknown_symbol(sub_mgr, configured_logging):
    mgr, scheduler, _repo, _hfd, exchange, _engine = sub_mgr
    exchange.symbol_exists = AsyncMock(return_value=False)
    scheduler.start()
    try:
        with pytest.raises(SubscriptionError):
            await mgr.add("ZZZZZ")
    finally:
        scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_deactivate_removes_jobs(sub_mgr, configured_logging):
    mgr, scheduler, repo, *_ = sub_mgr
    scheduler.start()
    try:
        await mgr.add("SOL")
        assert len(scheduler.list_jobs()) == 15
        await mgr.deactivate("SOL")
        assert len(scheduler.list_jobs()) == 0
        sub = await repo.get("SOL")
        assert sub is not None and sub.active is False
    finally:
        scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_activate_restores_jobs(sub_mgr, configured_logging):
    mgr, scheduler, *_ = sub_mgr
    scheduler.start()
    try:
        await mgr.add("SOL")
        await mgr.deactivate("SOL")
        assert len(scheduler.list_jobs()) == 0
        await mgr.activate("SOL")
        assert len(scheduler.list_jobs()) == 15
    finally:
        scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_remove_clears_both_db_and_jobs(sub_mgr, configured_logging):
    mgr, scheduler, repo, *_ = sub_mgr
    scheduler.start()
    try:
        await mgr.add("SOL")
        await mgr.remove("SOL")
        assert await repo.get("SOL") is None
        assert len(scheduler.list_jobs()) == 0
    finally:
        scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_activate_unknown_raises(sub_mgr, configured_logging):
    mgr, scheduler, *_ = sub_mgr
    scheduler.start()
    try:
        with pytest.raises(SymbolNotFoundError):
            await mgr.activate("NOPE")
    finally:
        scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_invalid_symbol_format_rejected(sub_mgr, configured_logging):
    mgr, scheduler, *_ = sub_mgr
    scheduler.start()
    try:
        with pytest.raises(SubscriptionError):
            await mgr.add("BT-C")
        with pytest.raises(SubscriptionError):
            await mgr.add("")
    finally:
        scheduler.shutdown(wait=False)
