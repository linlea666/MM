"""全局令牌桶限流（异步）。

用途：
- 限制每秒对 HFD 的总并发请求数（global_rps）
- 支持平滑突发（桶容量 = rps）

用法：
    limiter = TokenBucket(rps=5)
    async with limiter:
        await http_get(...)
"""

from __future__ import annotations

import asyncio
import time


class TokenBucket:
    """令牌桶限流器。线程安全（通过 asyncio.Lock）。"""

    def __init__(self, rps: float, burst: float | None = None) -> None:
        if rps <= 0:
            raise ValueError("rps must be > 0")
        self._rps = float(rps)
        self._capacity = float(burst) if burst is not None else float(rps)
        self._tokens = self._capacity
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    @property
    def rps(self) -> float:
        return self._rps

    async def acquire(self, tokens: float = 1.0) -> None:
        if tokens > self._capacity:
            raise ValueError("acquire tokens > capacity")
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self._last
                self._last = now
                self._tokens = min(self._capacity, self._tokens + elapsed * self._rps)
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                need = tokens - self._tokens
                wait = need / self._rps
            await asyncio.sleep(wait)

    async def __aenter__(self) -> "TokenBucket":
        await self.acquire(1.0)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None
