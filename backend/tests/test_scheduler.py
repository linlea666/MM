"""Scheduler 单元测试（不真正执行 cron，只验证 add/remove 行为）。"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.collector.engine import CollectorEngine
from backend.collector.scheduler import (
    CollectorScheduler,
    _kline_close_trigger,
    _periodic_trigger,
)


def test_kline_close_trigger_covers_all_timeframes():
    for tf in ("30m", "1h", "2h", "4h", "12h", "1d"):
        assert _kline_close_trigger(tf, 5) is not None


def test_periodic_trigger_covers_tiers():
    for tier in ("every_5min", "every_30min", "every_1h", "every_4h"):
        assert _periodic_trigger(tier) is not None


def test_periodic_trigger_rejects_unknown():
    with pytest.raises(ValueError):
        _periodic_trigger("every_1000s")


def test_add_remove_symbol_roundtrip(settings):
    engine = AsyncMock(spec=CollectorEngine)
    sched = CollectorScheduler(settings=settings, engine=engine)
    sched.start()
    try:
        added = sched.add_symbol("BTC")
        # 3 tf × 5 tier（kline_close + every_5min + every_30min + every_1h + every_4h）= 15
        assert len(added) == len(settings.collector.timeframes) * 5
        jobs = sched.list_jobs()
        assert len(jobs) == len(added)
        # 重复 add 不会重复创建
        again = sched.add_symbol("BTC")
        assert again == []

        # 再加一个币
        sched.add_symbol("ETH")
        assert len(sched.list_jobs()) == 2 * len(settings.collector.timeframes) * 5

        # 移除 BTC 只应移除 BTC 的 job
        removed = sched.remove_symbol("BTC")
        assert removed == len(settings.collector.timeframes) * 5
        remaining = sched.list_jobs()
        assert all("BTC" not in j["id"].split(":") for j in remaining)
    finally:
        sched.shutdown(wait=False)


def test_job_id_is_normalized_upper(settings):
    engine = AsyncMock(spec=CollectorEngine)
    sched = CollectorScheduler(settings=settings, engine=engine)
    sched.start()
    try:
        sched.add_symbol("eth")
        jobs = sched.list_jobs()
        assert all(":ETH:" in j["id"] for j in jobs)
    finally:
        sched.shutdown(wait=False)
