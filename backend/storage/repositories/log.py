"""日志 SQLite 仓库（独立文件，与业务库物理隔离）。

设计要点：
1. 日志库文件单独（settings.database.logs_path，默认 logs/mm-logs.sqlite），
   避免高频 INFO 写入阻塞业务事务。
2. 写入链路（logging 后台线程）：独占一个同步 sqlite3.Connection，
   走 write_payload(payload)。
3. 查询链路（/api/logs）：独占一个 aiosqlite.Connection，走 query/count/cleanup。
4. 启动时调 register_sqlite_writer(repo) 把 writer 注入到 logging 模块。
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from pathlib import Path
from threading import Lock
from typing import Any

import aiosqlite

from backend.core.config import Settings
from backend.core.logging import set_sqlite_writer
from backend.core.time_utils import now_iso, parse_relative
from backend.models import LogEntry

logger = logging.getLogger("storage.log")

_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema_logs.sql"


class LogRepository:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._path: Path = settings.resolve_path(settings.database.logs_path)
        self._async_conn: aiosqlite.Connection | None = None
        self._async_lock = asyncio.Lock()
        self._sync_lock = Lock()
        self._sync_conn: sqlite3.Connection | None = None
        self._initialized = False

    @property
    def path(self) -> Path:
        return self._path

    async def initialize(self) -> None:
        """应用启动时调用一次：确保文件与 schema 存在。"""
        if self._initialized:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(str(self._path), isolation_level=None)
        conn.row_factory = aiosqlite.Row
        cfg = self._settings.database
        if cfg.wal_mode:
            await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute(f"PRAGMA busy_timeout={cfg.busy_timeout_ms}")
        await conn.execute("PRAGMA synchronous=NORMAL")
        await conn.execute("PRAGMA temp_store=MEMORY")
        if not _SCHEMA_PATH.exists():
            raise RuntimeError(f"schema_logs.sql 不存在: {_SCHEMA_PATH}")
        ddl = _SCHEMA_PATH.read_text(encoding="utf-8")
        await conn.executescript(ddl)
        self._async_conn = conn
        self._initialized = True
        logger.info(
            "日志库已连接",
            extra={"context": {"logs_path": str(self._path)}},
        )

    async def close(self) -> None:
        if self._async_conn is not None:
            try:
                await self._async_conn.close()
            finally:
                self._async_conn = None
        self.close_sync()
        self._initialized = False

    # ─── 同步写入（给 logging 后台线程用）───

    def write_payload(self, payload: dict[str, Any]) -> None:
        """logging 后台线程调用。必须线程安全 + 极快返回。"""
        try:
            with self._sync_lock:
                if self._sync_conn is None:
                    Path(self._path).parent.mkdir(parents=True, exist_ok=True)
                    conn = sqlite3.connect(
                        str(self._path),
                        timeout=5.0,
                        check_same_thread=False,
                    )
                    conn.execute("PRAGMA journal_mode=WAL")
                    conn.execute(
                        f"PRAGMA busy_timeout={self._settings.database.busy_timeout_ms}"
                    )
                    conn.execute("PRAGMA synchronous=NORMAL")
                    # 首次创建时兜底建表（主流程 initialize() 一般已建好）
                    if _SCHEMA_PATH.exists():
                        conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
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
            params.append(f'%"symbol": "{symbol}"%')
        if from_ts:
            sql += " AND ts >= ?"
            params.append(from_ts)
        if to_ts:
            sql += " AND ts <= ?"
            params.append(to_ts)
        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = await self._fetchall(sql, tuple(params))
        return [_row_to_entry(r) for r in rows]

    async def count(self) -> int:
        row = await self._fetchone("SELECT COUNT(1) FROM logs")
        if row is None:
            return 0
        return int(row[0] or 0)

    async def counts_by_level_since(self, since_iso: str) -> dict[str, int]:
        """某时间点之后按 level 计数（给 summary API 用）。"""
        rows = await self._fetchall(
            "SELECT level, COUNT(1) AS c FROM logs WHERE ts >= ? GROUP BY level",
            (since_iso,),
        )
        return {r["level"]: int(r["c"]) for r in rows}

    async def top_loggers_since(
        self, since_iso: str, *, top: int = 10
    ) -> list[dict[str, Any]]:
        """某时间点之后按 logger 计数并取 TopN（给 summary API 用）。"""
        rows = await self._fetchall(
            "SELECT logger, COUNT(1) AS c FROM logs WHERE ts >= ? "
            "GROUP BY logger ORDER BY c DESC LIMIT ?",
            (since_iso, top),
        )
        return [{"logger": r["logger"], "count": int(r["c"])} for r in rows]

    async def cleanup_older_than(self, retention: str) -> int:
        """retention 形如 '7d' / '24h'。返回删除的行数。"""
        delta = parse_relative(retention)
        cutoff_ms = int((__import__("time").time() - delta.total_seconds()) * 1000)
        from datetime import UTC, datetime

        cutoff_iso = datetime.fromtimestamp(cutoff_ms / 1000, tz=UTC).isoformat()
        await self._ensure_async_conn()
        assert self._async_conn is not None
        async with self._async_lock:
            cur = await self._async_conn.execute(
                "DELETE FROM logs WHERE ts < ?",
                (cutoff_iso,),
            )
            return cur.rowcount or 0

    # ─── 内部 ───

    async def _ensure_async_conn(self) -> None:
        if self._async_conn is None:
            await self.initialize()

    async def _fetchone(self, sql: str, params: tuple = ()) -> aiosqlite.Row | None:
        await self._ensure_async_conn()
        assert self._async_conn is not None
        async with self._async_conn.execute(sql, params) as cur:
            return await cur.fetchone()

    async def _fetchall(self, sql: str, params: tuple = ()) -> list[aiosqlite.Row]:
        await self._ensure_async_conn()
        assert self._async_conn is not None
        async with self._async_conn.execute(sql, params) as cur:
            return list(await cur.fetchall())


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
