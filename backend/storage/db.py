"""SQLite 异步连接管理 + 模式初始化。

为什么用 aiosqlite：
    FastAPI 是异步的，同步 sqlite3 会阻塞事件循环。aiosqlite 把
    底层调用扔到线程池，不会卡住 API。

为什么用全局单连接：
    SQLite 在 WAL 模式下支持多读单写，单连接 + asyncio.Lock 比
    连接池简单且对自用规模足够。如果未来要多进程部署再考虑切换。
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiosqlite

from backend.core.config import Settings
from backend.core.exceptions import StorageError

logger = logging.getLogger("storage.db")

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


class Database:
    """单连接 SQLite 包装器（含初始化、PRAGMA、锁、便利方法）。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._db_path: Path = settings.resolve_path(settings.database.path)
        self._conn: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()

    @property
    def path(self) -> Path:
        return self._db_path

    async def connect(self) -> None:
        if self._conn is not None:
            return
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(
            str(self._db_path),
            isolation_level=None,  # autocommit 模式（手动管理事务）
        )
        self._conn.row_factory = aiosqlite.Row

        await self._apply_pragmas()
        await self._init_schema()
        logger.info(
            "SQLite 已连接",
            extra={"context": {"db_path": str(self._db_path)}},
        )

    async def close(self) -> None:
        if self._conn is not None:
            try:
                await self._conn.close()
            finally:
                self._conn = None

    async def _apply_pragmas(self) -> None:
        assert self._conn is not None
        cfg = self._settings.database
        if cfg.wal_mode:
            await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute(f"PRAGMA busy_timeout={cfg.busy_timeout_ms}")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        await self._conn.execute("PRAGMA temp_store=MEMORY")

    async def _init_schema(self) -> None:
        if not _SCHEMA_PATH.exists():
            raise StorageError(f"schema.sql 不存在: {_SCHEMA_PATH}")
        ddl = _SCHEMA_PATH.read_text(encoding="utf-8")
        assert self._conn is not None
        try:
            await self._conn.executescript(ddl)
            await self._conn.commit()
        except Exception as e:
            raise StorageError(f"应用 schema 失败: {e}") from e

    # ─── 便利方法 ───

    @asynccontextmanager
    async def transaction(self):
        """提供原子的写入事务。"""
        if self._conn is None:
            raise StorageError("Database 未连接")
        async with self._write_lock:
            await self._conn.execute("BEGIN")
            try:
                yield self._conn
                await self._conn.commit()
            except Exception:
                await self._conn.rollback()
                raise

    async def execute(
        self,
        sql: str,
        params: tuple | dict[str, Any] | None = None,
    ) -> aiosqlite.Cursor:
        if self._conn is None:
            raise StorageError("Database 未连接")
        async with self._write_lock:
            return await self._conn.execute(sql, params or ())

    async def executemany(
        self,
        sql: str,
        seq_params: list[tuple] | list[dict[str, Any]],
    ) -> aiosqlite.Cursor:
        if self._conn is None:
            raise StorageError("Database 未连接")
        async with self._write_lock:
            return await self._conn.executemany(sql, seq_params)

    async def fetchone(
        self,
        sql: str,
        params: tuple | dict[str, Any] | None = None,
    ) -> aiosqlite.Row | None:
        if self._conn is None:
            raise StorageError("Database 未连接")
        async with self._conn.execute(sql, params or ()) as cur:
            return await cur.fetchone()

    async def fetchall(
        self,
        sql: str,
        params: tuple | dict[str, Any] | None = None,
    ) -> list[aiosqlite.Row]:
        if self._conn is None:
            raise StorageError("Database 未连接")
        async with self._conn.execute(sql, params or ()) as cur:
            return list(await cur.fetchall())

    async def fetch_scalar(
        self,
        sql: str,
        params: tuple | dict[str, Any] | None = None,
    ) -> Any:
        row = await self.fetchone(sql, params)
        if row is None:
            return None
        return row[0]

    async def disk_size_bytes(self) -> int:
        try:
            return self._db_path.stat().st_size
        except OSError:
            return 0


# ─── 全局单例 ───

_global_db: Database | None = None


def get_database() -> Database:
    if _global_db is None:
        raise StorageError("Database 尚未初始化，请先调用 init_database()")
    return _global_db


async def init_database(settings: Settings) -> Database:
    global _global_db
    if _global_db is not None:
        return _global_db
    db = Database(settings)
    await db.connect()
    _global_db = db
    return db


async def shutdown_database() -> None:
    global _global_db
    if _global_db is not None:
        await _global_db.close()
        _global_db = None
