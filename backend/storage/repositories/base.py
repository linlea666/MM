"""原子 repository 的通用基类。

每个原子 repo 只需声明：
- ``TABLE``   表名
- ``MODEL``   对应 Pydantic 模型
- ``PRIMARY`` 主键列名（tuple）
- ``COLUMNS`` 全部列名（按 INSERT 顺序）

通用能力：
- ``upsert``      按主键合并（INSERT ... ON CONFLICT(pk) DO UPDATE）
- ``upsert_many`` 批量合并
- ``replace_for`` 价位/聚合类常用：按某些列（如 symbol, tf）全量替换

复杂查询（如 K 线的 fetch_range）保留在专门子类里。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, ClassVar, Generic, TypeVar

from pydantic import BaseModel

from ..db import Database

M = TypeVar("M", bound=BaseModel)


class AtomRepository(Generic[M]):
    TABLE: ClassVar[str] = ""
    MODEL: ClassVar[type] = BaseModel
    PRIMARY: ClassVar[tuple[str, ...]] = ()
    COLUMNS: ClassVar[tuple[str, ...]] = ()

    def __init__(self, db: Database) -> None:
        self._db = db
        assert self.TABLE, "TABLE must be set"
        assert self.COLUMNS, "COLUMNS must be set"
        assert self.PRIMARY, "PRIMARY must be set"

    # ─── SQL 片段 ───

    @classmethod
    def _insert_sql(cls) -> str:
        cols = ", ".join(cls.COLUMNS)
        placeholders = ", ".join(f":{c}" for c in cls.COLUMNS)
        pk_cols = ", ".join(cls.PRIMARY)
        non_pk = [c for c in cls.COLUMNS if c not in cls.PRIMARY]
        if non_pk:
            updates = ", ".join(f"{c}=excluded.{c}" for c in non_pk)
            conflict = f"ON CONFLICT({pk_cols}) DO UPDATE SET {updates}"
        else:
            conflict = f"ON CONFLICT({pk_cols}) DO NOTHING"
        return f"INSERT INTO {cls.TABLE}({cols}) VALUES ({placeholders}) {conflict}"

    # ─── 写入 ───

    async def upsert(self, model: M) -> None:
        row = self._to_row(model)
        await self._db.execute(self._insert_sql(), row)

    async def upsert_many(self, models: Iterable[M]) -> int:
        rows = [self._to_row(m) for m in models]
        if not rows:
            return 0
        await self._db.executemany(self._insert_sql(), rows)
        return len(rows)

    async def replace_for(
        self,
        scope: dict[str, Any],
        models: Iterable[M],
    ) -> int:
        """按 ``scope`` 条件删光后批量插入（价位/HVN 节点这类全量刷新用）。"""
        rows = [self._to_row(m) for m in models]
        if not scope:
            raise ValueError("scope 不能为空，防止误删全表")
        where = " AND ".join(f"{k}=:{k}" for k in scope.keys())
        async with self._db.transaction() as conn:
            await conn.execute(f"DELETE FROM {self.TABLE} WHERE {where}", scope)
            if rows:
                await conn.executemany(self._insert_sql(), rows)
        return len(rows)

    # ─── 查询 ───

    async def count(self, **filters: Any) -> int:
        sql = f"SELECT COUNT(1) FROM {self.TABLE}"
        params: dict[str, Any] = {}
        if filters:
            where = " AND ".join(f"{k}=:{k}" for k in filters.keys())
            sql += f" WHERE {where}"
            params = filters
        n = await self._db.fetch_scalar(sql, params)
        return int(n or 0)

    async def fetch(
        self,
        *,
        where: dict[str, Any] | None = None,
        order_by: str | None = None,
        limit: int | None = None,
    ) -> list[M]:
        sql = f"SELECT {', '.join(self.COLUMNS)} FROM {self.TABLE}"
        params: dict[str, Any] = {}
        if where:
            clauses = " AND ".join(f"{k}=:{k}" for k in where.keys())
            sql += f" WHERE {clauses}"
            params = dict(where)
        if order_by:
            sql += f" ORDER BY {order_by}"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        rows = await self._db.fetchall(sql, params)
        return [self._from_row(r) for r in rows]

    # ─── 序列化辅助 ───

    @classmethod
    def _to_row(cls, model: M) -> dict[str, Any]:
        data = model.model_dump()
        # 字段名和 COLUMNS 对齐；支持子类在 _transform_write 做额外转换
        row = {col: data.get(col) for col in cls.COLUMNS}
        return cls._transform_write(row, data)

    @classmethod
    def _from_row(cls, row) -> M:
        data = {k: row[k] for k in cls.COLUMNS}
        data = cls._transform_read(data)
        return cls.MODEL(**data)  # type: ignore[return-value]

    # 子类可覆写做字段转换（JSON 编码、字符串 ↔ ms 等）
    @classmethod
    def _transform_write(cls, row: dict[str, Any], model_data: dict[str, Any]) -> dict[str, Any]:
        return row

    @classmethod
    def _transform_read(cls, row: dict[str, Any]) -> dict[str, Any]:
        return row
