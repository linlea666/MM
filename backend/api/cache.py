"""极简 TTL 缓存（支持 asyncio.Lock 去重并发请求）。

用于 /api/dashboard 等热路径，避免前端多 tab / 快速轮询打爆 RuleRunner。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

T = TypeVar("T")


@dataclass
class _Entry(Generic[T]):
    value: T
    expires_at: float


class TTLCache(Generic[T]):
    """按 str key 缓存，支持 "同一 key 并发请求只跑一次 factory" 的去重。"""

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = ttl_seconds
        self._store: dict[str, _Entry[T]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._meta_lock = asyncio.Lock()

    def peek(self, key: str) -> T | None:
        """不刷新、不计算；仅看当前是否有未过期值（测试 / 监控用）。"""
        entry = self._store.get(key)
        if entry is None or entry.expires_at <= time.monotonic():
            return None
        return entry.value

    async def get_or_compute(
        self, key: str, factory: Callable[[], Awaitable[T]]
    ) -> tuple[T, bool]:
        """返回 (value, from_cache)。"""
        entry = self._store.get(key)
        if entry is not None and entry.expires_at > time.monotonic():
            return entry.value, True

        # 每个 key 一把锁，避免惊群
        async with self._meta_lock:
            lock = self._locks.setdefault(key, asyncio.Lock())

        async with lock:
            # 双重检查
            entry = self._store.get(key)
            if entry is not None and entry.expires_at > time.monotonic():
                return entry.value, True
            value = await factory()
            self._store[key] = _Entry(value=value, expires_at=time.monotonic() + self._ttl)
            return value, False

    def invalidate(self, key: str | None = None) -> None:
        if key is None:
            self._store.clear()
            return
        self._store.pop(key, None)


__all__ = ["TTLCache"]
