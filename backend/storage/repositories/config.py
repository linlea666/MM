"""config_overrides / config_audit 表 CRUD。

只管存取与审计，**不做业务合并**（合并逻辑在 ``ConfigService``）。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.core.exceptions import StorageError
from backend.core.time_utils import now_ms

from ..db import Database

logger = logging.getLogger("storage.config")


# ─── 值类型编解码 ─────────────────────────────────────────────

_VALUE_TYPES = ("number", "int", "bool", "string", "array", "object", "null")


def infer_value_type(value: Any) -> str:
    """把 Python 值映射到 value_type 字符串（与 meta.yaml 统一）。"""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (list, tuple)):
        return "array"
    if isinstance(value, dict):
        return "object"
    raise StorageError(f"不支持的 config 值类型: {type(value).__name__}")


def encode_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def decode_value(raw: str) -> Any:
    return json.loads(raw)


# ─── Repository ──────────────────────────────────────────────


class ConfigRepository:
    """config_overrides + config_audit 的唯一访问入口。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ── 查询 ──

    async def get(self, key: str) -> Any | None:
        """读单个 override；不存在返回 None（让调用方走默认值）。"""
        row = await self._db.fetchone(
            "SELECT value FROM config_overrides WHERE key=?",
            (key,),
        )
        if row is None:
            return None
        return decode_value(row["value"])

    async def list_all(self) -> dict[str, Any]:
        """一次性拉所有 override；启动时用于构建内存层。"""
        rows = await self._db.fetchall("SELECT key, value FROM config_overrides")
        return {r["key"]: decode_value(r["value"]) for r in rows}

    async def list_raw(self) -> list[dict[str, Any]]:
        """列出所有 override 的完整元信息（给前端/审计用）。"""
        rows = await self._db.fetchall(
            "SELECT key, value, value_type, updated_at, updated_by, reason "
            "FROM config_overrides ORDER BY key ASC"
        )
        return [
            {
                "key": r["key"],
                "value": decode_value(r["value"]),
                "value_type": r["value_type"],
                "updated_at": r["updated_at"],
                "updated_by": r["updated_by"],
                "reason": r["reason"],
            }
            for r in rows
        ]

    # ── 写入 ──

    async def set(
        self,
        key: str,
        value: Any,
        *,
        updated_by: str,
        reason: str | None = None,
    ) -> None:
        """插入或覆盖一个 override，同时写 audit。"""
        value_type = infer_value_type(value)
        encoded = encode_value(value)
        ts = now_ms()

        async with self._db.transaction() as conn:
            old_row = await conn.execute(
                "SELECT value FROM config_overrides WHERE key=?",
                (key,),
            )
            old = await old_row.fetchone()
            old_value = old["value"] if old else None

            await conn.execute(
                "INSERT INTO config_overrides(key, value, value_type, updated_at, updated_by, reason) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET "
                "  value=excluded.value, value_type=excluded.value_type, "
                "  updated_at=excluded.updated_at, updated_by=excluded.updated_by, "
                "  reason=excluded.reason",
                (key, encoded, value_type, ts, updated_by, reason),
            )
            await conn.execute(
                "INSERT INTO config_audit(key, old_value, new_value, updated_at, updated_by, reason) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (key, old_value, encoded, ts, updated_by, reason),
            )
        logger.info(
            f"配置更新 {key}",
            extra={
                "tags": ["CONFIG"],
                "context": {
                    "key": key,
                    "updated_by": updated_by,
                    "has_previous": old_value is not None,
                },
            },
        )

    async def delete(self, key: str, *, updated_by: str, reason: str | None = None) -> bool:
        """删除 override（相当于"恢复默认"）；写 audit；返回是否真删除了。"""
        ts = now_ms()
        async with self._db.transaction() as conn:
            old_row = await conn.execute(
                "SELECT value FROM config_overrides WHERE key=?",
                (key,),
            )
            old = await old_row.fetchone()
            if old is None:
                return False
            await conn.execute("DELETE FROM config_overrides WHERE key=?", (key,))
            await conn.execute(
                "INSERT INTO config_audit(key, old_value, new_value, updated_at, updated_by, reason) "
                "VALUES (?, ?, NULL, ?, ?, ?)",
                (key, old["value"], ts, updated_by, reason),
            )
        logger.info(
            f"配置恢复默认 {key}",
            extra={
                "tags": ["CONFIG"],
                "context": {"key": key, "updated_by": updated_by},
            },
        )
        return True

    async def clear_all(self, *, updated_by: str, reason: str | None = None) -> int:
        """整体恢复默认；返回被清除的条数。"""
        ts = now_ms()
        removed = 0
        async with self._db.transaction() as conn:
            old_rows = await conn.execute("SELECT key, value FROM config_overrides")
            old = list(await old_rows.fetchall())
            for row in old:
                await conn.execute(
                    "INSERT INTO config_audit(key, old_value, new_value, updated_at, updated_by, reason) "
                    "VALUES (?, ?, NULL, ?, ?, ?)",
                    (row["key"], row["value"], ts, updated_by, reason),
                )
            await conn.execute("DELETE FROM config_overrides")
            removed = len(old)
        logger.info(
            f"配置整体重置 {removed} 项",
            extra={"tags": ["CONFIG"], "context": {"updated_by": updated_by}},
        )
        return removed

    # ── 审计 ──

    async def list_audit(
        self,
        *,
        key: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if key:
            rows = await self._db.fetchall(
                "SELECT id, key, old_value, new_value, updated_at, updated_by, reason "
                "FROM config_audit WHERE key=? "
                "ORDER BY updated_at DESC, id DESC LIMIT ?",
                (key, limit),
            )
        else:
            rows = await self._db.fetchall(
                "SELECT id, key, old_value, new_value, updated_at, updated_by, reason "
                "FROM config_audit ORDER BY updated_at DESC, id DESC LIMIT ?",
                (limit,),
            )
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "id": r["id"],
                    "key": r["key"],
                    "old_value": decode_value(r["old_value"]) if r["old_value"] else None,
                    "new_value": decode_value(r["new_value"]) if r["new_value"] else None,
                    "updated_at": r["updated_at"],
                    "updated_by": r["updated_by"],
                    "reason": r["reason"],
                }
            )
        return out

    async def prune_audit(self, *, older_than_ms: int) -> int:
        cur = await self._db.execute(
            "DELETE FROM config_audit WHERE updated_at < ?",
            (older_than_ms,),
        )
        rowcount = cur.rowcount or 0
        if rowcount:
            logger.info(
                f"审计日志清理 {rowcount} 条",
                extra={"tags": ["CONFIG"], "context": {"older_than_ms": older_than_ms}},
            )
        return rowcount
