"""日志体系：四路输出（Console / File / SQLite / WebSocket）。

设计要点：
1. 文本格式（Console / File）对齐约束 §5：
   `[%(asctime)s] [%(levelname)s] %(name)s: %(message)s`
2. 结构化 JSON（SQLite / WS）字段：
   ts / level / logger / message / tags / context / traceback
3. SQLite 入库通过异步队列，避免阻塞业务线程。
4. WebSocket 推送通过可插拔回调（默认 no-op，Step 4 注入真实广播）。
5. 业务代码通过 `logging.getLogger("collector.hfd_client")` 取 logger，
   通过 `extra={"tags": [...], "context": {...}}` 附加结构化字段。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Thread
from typing import Any

from .config import LoggingConfig, Settings

# ─── 公共类型 ───
WsBroadcaster = Callable[[dict[str, Any]], Awaitable[None]]
SqliteWriter = Callable[[dict[str, Any]], None]

# 默认值（Step 4 注入真实广播器和 SQLite 写入器）
_ws_broadcaster: WsBroadcaster | None = None
_sqlite_writer: SqliteWriter | None = None
_ws_main_loop: asyncio.AbstractEventLoop | None = None


def set_ws_broadcaster(fn: WsBroadcaster | None) -> None:
    """供 Step 4 的 API 层注入 WebSocket 广播实现。"""
    global _ws_broadcaster
    _ws_broadcaster = fn


def set_ws_main_loop(loop: asyncio.AbstractEventLoop | None) -> None:
    """供 lifespan 注入主事件循环（供 logging 后台线程跨线程投递 WS 广播）。"""
    global _ws_main_loop
    _ws_main_loop = loop


def set_sqlite_writer(fn: SqliteWriter | None) -> None:
    """供 storage.repositories.log 注入真实写入器。"""
    global _sqlite_writer
    _sqlite_writer = fn


# ─── 结构化 JSON 格式化器 ───
class StructuredFormatter(logging.Formatter):
    """生成结构化 JSON。给 SQLite / WS 用。"""

    def format(self, record: logging.LogRecord) -> str:
        payload = build_payload(record)
        return json.dumps(payload, ensure_ascii=False)


def build_payload(record: logging.LogRecord) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
        "level": record.levelname,
        "logger": record.name,
        "message": record.getMessage(),
        "tags": list(getattr(record, "tags", []) or []),
        "context": dict(getattr(record, "context", {}) or {}),
    }
    if record.exc_info:
        payload["traceback"] = logging.Formatter().formatException(record.exc_info)
    return payload


# ─── SQLite Handler（异步队列）───
class SQLiteQueueHandler(logging.Handler):
    """日志先入队列，由单独后台线程批量写 SQLite，避免阻塞业务。"""

    def __init__(self, max_queue: int = 10_000) -> None:
        super().__init__()
        self.queue: Queue[dict[str, Any]] = Queue(maxsize=max_queue)
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, name="log-sqlite-writer", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    def emit(self, record: logging.LogRecord) -> None:
        try:
            payload = build_payload(record)
            try:
                self.queue.put_nowait(payload)
            except Exception:
                # 队列满 → 丢弃最早，保留最新
                try:
                    self.queue.get_nowait()
                except Empty:
                    pass
                self.queue.put_nowait(payload)
        except Exception:
            self.handleError(record)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                payload = self.queue.get(timeout=0.5)
            except Empty:
                continue
            writer = _sqlite_writer
            if writer is None:
                continue
            try:
                writer(payload)
            except Exception:
                # 不能让 writer 异常中断后台线程
                pass


# ─── WebSocket Handler ───
class WebSocketHandler(logging.Handler):
    """把日志广播给所有订阅 /ws/logs 的客户端。"""

    def emit(self, record: logging.LogRecord) -> None:
        broadcaster = _ws_broadcaster
        if broadcaster is None:
            return
        try:
            payload = build_payload(record)
            loop = _ws_main_loop
            if loop is None:
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    return
            if loop.is_closed():
                return
            try:
                asyncio.run_coroutine_threadsafe(broadcaster(payload), loop)
            except RuntimeError:
                pass
        except Exception:
            self.handleError(record)


# ─── 全局单例：保留对 SQLite handler 的引用以便关闭 ───
_sqlite_handler: SQLiteQueueHandler | None = None


def get_sqlite_handler() -> SQLiteQueueHandler | None:
    return _sqlite_handler


# ─── 入口 ───
def setup_logging(settings: Settings) -> None:
    """应用启动时调用一次。重复调用会先清空已有 handler。"""
    global _sqlite_handler

    log_cfg: LoggingConfig = settings.logging
    root = logging.getLogger()
    root.setLevel(log_cfg.level)

    # 清空已有 handler（重启 / 测试用）
    for h in list(root.handlers):
        root.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass

    # 关闭已有的 SQLite handler 后台线程
    if _sqlite_handler is not None:
        _sqlite_handler.stop()
        _sqlite_handler = None

    text_fmt = logging.Formatter(fmt=log_cfg.format, datefmt=log_cfg.datefmt)
    json_fmt = StructuredFormatter()

    # 1) Console
    if log_cfg.console:
        console = logging.StreamHandler()
        console.setFormatter(text_fmt)
        console.setLevel(log_cfg.level)
        root.addHandler(console)

    # 2) File
    if log_cfg.file.enabled:
        file_path = settings.resolve_path(log_cfg.file.path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            file_path,
            maxBytes=log_cfg.file.max_size_mb * 1024 * 1024,
            backupCount=log_cfg.file.backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(text_fmt)
        file_handler.setLevel(log_cfg.level)
        root.addHandler(file_handler)

    # 3) SQLite（异步队列）
    if log_cfg.sqlite.enabled:
        sqlite_handler = SQLiteQueueHandler()
        sqlite_handler.setFormatter(json_fmt)
        sqlite_handler.setLevel(log_cfg.sqlite.min_level)
        sqlite_handler.start()
        root.addHandler(sqlite_handler)
        _sqlite_handler = sqlite_handler

    # 4) WebSocket
    if log_cfg.ws.enabled:
        ws_handler = WebSocketHandler()
        ws_handler.setFormatter(json_fmt)
        ws_handler.setLevel(log_cfg.level)
        root.addHandler(ws_handler)


def shutdown_logging() -> None:
    """优雅关闭（应用退出时调用）。"""
    global _sqlite_handler
    if _sqlite_handler is not None:
        _sqlite_handler.stop()
        _sqlite_handler = None
    logging.shutdown()


# ─── 业务侧便利函数 ───
def get_logger(name: str) -> logging.Logger:
    """约定模块命名：collector.hfd_client / rules.arbitrator / api.ws ..."""
    return logging.getLogger(name)


def log_with_context(
    logger: logging.Logger,
    level: int,
    message: str,
    *,
    tags: list[str] | None = None,
    context: dict[str, Any] | None = None,
    exc_info: bool = False,
) -> None:
    """统一带结构化字段的日志写入。"""
    extra: dict[str, Any] = {}
    if tags:
        extra["tags"] = tags
    if context:
        extra["context"] = context
    logger.log(level, message, extra=extra, exc_info=exc_info)


# 导出给业务模块用的常量（约定 tag 命名）
class Tags:
    URGENT = "URGENT"
    AI = "AI"
    CONFLICT = "CONFLICT"
    HFD = "HFD"
    FAILOVER = "FAILOVER"
    FETCH_FAIL = "FETCH_FAIL"
    CIRCUIT = "CIRCUIT"
    PHASE = "PHASE"
    LIFECYCLE = "LIFECYCLE"
    SLOW = "SLOW"
    REVIEW = "REVIEW"
    TICK = "TICK"
    SUBSCRIPTION = "SUBSCRIPTION"
    SCHED = "SCHED"
    PARSE_WARN = "PARSE_WARN"
    CONFIG = "CONFIG"
    RULES = "RULES"
    API = "API"
    DASHBOARD = "DASHBOARD"


__all__ = [
    "Tags",
    "build_payload",
    "get_logger",
    "get_sqlite_handler",
    "log_with_context",
    "set_sqlite_writer",
    "set_ws_broadcaster",
    "set_ws_main_loop",
    "setup_logging",
    "shutdown_logging",
]
