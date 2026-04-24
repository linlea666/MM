"""WebSocket 广播器。

两类频道：

1. ``DashboardBroker``  每 5 秒调 RuleRunner 产一份快照，按 (symbol, tf) 分组广播。
2. ``LogBroker``        订阅 logging hook，新日志实时扇出给符合过滤条件的客户端。

客户端握手后需要先发一条 ``{"action": "subscribe", ...}``：
- dashboard: ``{"action":"subscribe","symbol":"BTC","tf":"30m"}``
- logs:      ``{"action":"subscribe","levels":["ERROR"],"loggers":["api"]}``（均可选）

心跳：客户端发 ``{"action":"ping"}`` 会收到 ``{"type":"pong"}``。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket

from backend.core.logging import Tags
from backend.rules import NoDataError, RuleRunner

logger = logging.getLogger("api.ws")


# ─── Dashboard Broker ─────────────────────────────────────


@dataclass
class _DashSub:
    ws: WebSocket
    symbol: str | None = None
    tf: str = "30m"
    last_hash: str | None = None


class DashboardBroker:
    """5 秒定时推送大屏快照；对同一 (symbol, tf) 只算一次 runner.run。"""

    def __init__(self, runner: RuleRunner, *, interval: float = 5.0) -> None:
        self._runner = runner
        self._interval = interval
        self._subs: dict[int, _DashSub] = {}
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    # ── lifecycle ──

    def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="ws-dashboard-loop")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        async with self._lock:
            for sub in list(self._subs.values()):
                try:
                    await sub.ws.close(code=1001)
                except Exception:   # noqa: BLE001
                    pass
            self._subs.clear()

    # ── subscription ──

    async def add(self, ws: WebSocket) -> _DashSub:
        sub = _DashSub(ws=ws)
        async with self._lock:
            self._subs[id(ws)] = sub
        return sub

    async def remove(self, ws: WebSocket) -> None:
        async with self._lock:
            self._subs.pop(id(ws), None)

    async def update_subscription(
        self, ws: WebSocket, *, symbol: str | None, tf: str
    ) -> None:
        async with self._lock:
            sub = self._subs.get(id(ws))
            if sub is None:
                return
            sub.symbol = symbol
            sub.tf = tf
            sub.last_hash = None

    # ── push loop ──

    async def _loop(self) -> None:
        logger.info("dashboard broker loop started", extra={"tags": [Tags.API]})
        try:
            while not self._stop.is_set():
                await self._tick()
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
                except asyncio.TimeoutError:
                    pass
        except asyncio.CancelledError:
            pass
        except Exception as e:   # noqa: BLE001
            logger.error(f"dashboard broker loop 异常: {e}", exc_info=True,
                         extra={"tags": [Tags.API, Tags.URGENT]})

    async def _tick(self) -> None:
        async with self._lock:
            targets = list(self._subs.values())
        if not targets:
            return

        # 按 (symbol, tf) 分组，避免同一快照多次计算
        groups: dict[tuple[str | None, str], list[_DashSub]] = {}
        for sub in targets:
            groups.setdefault((sub.symbol, sub.tf), []).append(sub)

        for (symbol, tf), subs in groups.items():
            if symbol is None:
                continue   # 未 subscribe
            try:
                snap = await self._runner.run(symbol, tf)
            except NoDataError:
                await self._push_many(
                    subs, {"type": "error", "code": "NO_DATA",
                           "symbol": symbol, "tf": tf})
                continue
            except Exception as e:   # noqa: BLE001
                logger.warning(f"ws runner {symbol}/{tf} 失败: {e}",
                               extra={"tags": [Tags.API]})
                await self._push_many(
                    subs,
                    {"type": "error", "code": "RUNNER_ERROR",
                     "symbol": symbol, "tf": tf, "message": str(e)},
                )
                continue

            body = snap.model_dump()
            msg = {"type": "snapshot", "symbol": symbol, "tf": tf, "data": body}
            await self._push_many(subs, msg)

    async def _push_many(self, subs: list[_DashSub], payload: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        for sub in subs:
            try:
                await sub.ws.send_json(payload)
            except Exception:   # noqa: BLE001
                dead.append(sub.ws)
        for ws in dead:
            await self.remove(ws)


# ─── Log Broker ────────────────────────────────────────────


@dataclass
class _LogSub:
    ws: WebSocket
    levels: set[str] = field(default_factory=set)   # 空 = 全部
    loggers: list[str] = field(default_factory=list)  # 前缀；空 = 全部
    ready: bool = False   # 客户端首次 subscribe 前不推送，避免和握手消息交织


class LogBroker:
    """日志实时广播。logging 线程调 ``broadcast(payload)`` 即可（线程安全）。"""

    def __init__(self) -> None:
        self._subs: dict[int, _LogSub] = {}
        self._lock = asyncio.Lock()
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=2000)
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._consumer(), name="ws-log-consumer")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        async with self._lock:
            for sub in list(self._subs.values()):
                try:
                    await sub.ws.close(code=1001)
                except Exception:   # noqa: BLE001
                    pass
            self._subs.clear()

    async def add(self, ws: WebSocket) -> _LogSub:
        sub = _LogSub(ws=ws)
        async with self._lock:
            self._subs[id(ws)] = sub
        return sub

    async def remove(self, ws: WebSocket) -> None:
        async with self._lock:
            self._subs.pop(id(ws), None)

    async def update_filter(
        self,
        ws: WebSocket,
        *,
        levels: list[str] | None,
        loggers: list[str] | None,
    ) -> None:
        async with self._lock:
            sub = self._subs.get(id(ws))
            if sub is None:
                return
            sub.levels = set(levels or [])
            sub.loggers = list(loggers or [])
            sub.ready = True

    # ── 入口：logging WebSocketHandler 通过 set_ws_broadcaster 注入 ──

    async def broadcast(self, payload: dict[str, Any]) -> None:
        """**必须保持轻量、不阻塞 logging 线程**。仅入队，真正扇出在 _consumer。"""
        try:
            self._queue.put_nowait(payload)
        except asyncio.QueueFull:
            # 宁可丢少量日志也不阻塞 logging
            pass

    async def _consumer(self) -> None:
        while not self._stop.is_set():
            try:
                payload = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            await self._dispatch(payload)

    async def _dispatch(self, payload: dict[str, Any]) -> None:
        async with self._lock:
            targets = list(self._subs.values())
        if not targets:
            return
        dead: list[WebSocket] = []
        for sub in targets:
            if not sub.ready:
                continue
            if sub.levels and payload.get("level") not in sub.levels:
                continue
            if sub.loggers:
                name = payload.get("logger", "")
                if not any(name.startswith(p) for p in sub.loggers):
                    continue
            try:
                await sub.ws.send_json({"type": "log", "data": payload})
            except Exception:   # noqa: BLE001
                dead.append(sub.ws)
        for ws in dead:
            await self.remove(ws)


__all__ = ["DashboardBroker", "LogBroker"]
