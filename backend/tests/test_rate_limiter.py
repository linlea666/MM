"""令牌桶限流测试。"""

from __future__ import annotations

import asyncio
import time

import pytest

from backend.collector.rate_limiter import TokenBucket


@pytest.mark.asyncio
async def test_burst_then_wait():
    bucket = TokenBucket(rps=10, burst=5)
    # 一开始桶满（=burst），连续 5 次应该几乎无延迟
    t0 = time.monotonic()
    for _ in range(5):
        await bucket.acquire()
    assert time.monotonic() - t0 < 0.1

    # 第 6 次要等大约 1/10 秒
    t1 = time.monotonic()
    await bucket.acquire()
    elapsed = time.monotonic() - t1
    assert 0.05 < elapsed < 0.25


@pytest.mark.asyncio
async def test_rejects_too_large():
    bucket = TokenBucket(rps=5)
    with pytest.raises(ValueError):
        await bucket.acquire(100.0)


@pytest.mark.asyncio
async def test_async_ctx():
    bucket = TokenBucket(rps=50)
    async with bucket:
        pass
