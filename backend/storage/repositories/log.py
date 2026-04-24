"""logs 表 CRUD + 接入 logging.SQLiteQueueHandler 的同步 writer。

设计要点：
1. 后台线程通过 ``write_payload(payload)`` 调用同步 sqlite3 写入，
   不能用 aiosqlite（没 event loop）。
2. asyncio API（``query`` / ``cleanup_old``）走主连接的 aiosqlite。
3. 启动时调 ``register_sqlite_writer(repo)`` 把 writer 注入到 logging。
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from threading import Lock
from typing import Any

from backend.core.logging import set_sqlite_writer
from backend.core.time_utils import now_iso, parse_relative
from backend.models import LogEntry

from ..db import Database

logger = logging.getLogger("storage.log")


class LogRepository:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._sync_path = str(db.path)
        self._sync_lock = Lock()
        # 后台线程独占的同步连接（懒初始化）
        self._sync_conn: sqlite3.Connection | None = None

    # ─── 同步写入（给 logging 后台线程用）───

    def write_payload(self, payload: dict[str, Any]) -> None:
        """logging 后台线程调用。必须线程安全 + 极快返回。"""
        try:
            with self._sync_lock:
                if self._sync_conn is None:
                    Path(self._sync_path).parent.mkdir(parents=True, exist_ok=True)
                    conn = sqlite3.connect(
                        self._sync_path,
                        timeout=5.0,
                        check_same_thread=False,  # 主线程也可调 close_sync()
                    )
                    conn.execute("PRAGMA journal_mode=WAL")
                    conn.execute("PRAGMA busy_timeout=5000")
                    conn.execute("PRAGMA synchronous=NORMAL")
                    self._sync_conn = conn
                conn = self._sync_conn
                conn.execute(
                    "INSERT INTO logs(ts, level, logger, message, tags, context, traceback) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        payload.get("ts") or now_iso(),
                        payload.get("level", "INFO"),
                        payload.get("logger", "unknown"),
                        payload.get("message", ""),
                        json.dumps(payload.get("tags") or [], ensure_ascii=False),
                        json.dumps(payload.get("context") or {}, ensure_ascii=False),
                        payload.get("traceback"),
                    ),
                )
                conn.commit()
        except Exception:
            # 后台线程：日志写失败也不能抛
            pass

    def close_sync(self) -> None:
        with self._sync_lock:
            if self._sync_conn is not None:
                try:
                    self._sync_conn.close()
                finally:
                    self._sync_conn = None

    # ─── 异步查询（给 API 用）───

    async def query(
        self,
        *,
        levels: list[str] | None = None,
        loggers_prefix: list[str] | None = None,
        keyword: str | None = None,
        symbol: str | None = None,
        from_ts: str | None = None,
        to_ts: str | None = None,
        limit: int = 300,
        offset: int = 0,
    ) -> list[LogEntry]:
        sql = "SELECT * FROM logs WHERE 1=1"
        params: list[Any] = []
        if levels:
            placeholders = ",".join(["?"] * len(levels))
            sql += f" AND level IN ({placeholders})"
            params.extend(levels)
        if loggers_prefix:
            ors = " OR ".join(["logger LIKE ?"] * len(loggers_prefix))
            sql += f" AND ({ors})"
            params.extend(f"{p}%" for p in loggers_prefix)
        if keyword:
            sql += " AND message LIKE ?"
            params.append(f"%{keyword}%")
        if symbol:
            sql += " AND context LIKE ?"
            # 简单模糊匹配（避免引入 JSON1 扩展）
            params.append(f'%"symbol": "{symbol}"%')
        if from_ts:
            sql += " AND ts >= ?"
            params.append(from_ts)
        if to_ts:
            sql += " AND ts <= ?"
            params.append(to_ts)
        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = await self._db.fetchall(sql, tuple(params))
        return [_row_to_entry(r) for r in rows]

    async def count(self) -> int:
        n = await self._db.fetch_scalar("SELECT COUNT(1) FROM logs")
        return int(n or 0)

    async def cleanup_older_than(self, retention: str) -> int:
        """retention 形如 '7d' / '24h'。返回删除的行数。"""
        delta = parse_relative(retention)
        cutoff_ms = int((__import__("time").time() - delta.total_seconds()) * 1000)
        # ts 是 ISO 字符串，转 ISO 比较
        from datetime import UTC, datetime

        cutoff_iso = datetime.fromtimestamp(cutoff_ms / 1000, tz=UTC).isoformat()
        cur = await self._db.execute(
            "DELETE FROM logs WHERE ts < ?",
            (cutoff_iso,),
        )
        return cur.rowcount or 0


def register_sqlite_writer(repo: LogRepository) -> None:
    """供应用启动时调用，把 LogRepository 注入到 logging 模块。"""
    set_sqlite_writer(repo.write_payload)


def _row_to_entry(row) -> LogEntry:
    return LogEntry(
        id=row["id"],
        ts=row["ts"],
        level=row["level"],
        logger=row["logger"],
        message=row["message"],
        tags=json.loads(row["tags"] or "[]"),
        context=json.loads(row["context"] or "{}"),
        traceback=row["traceback"],
    )
