"""subscriptions 表 CRUD（添加即常驻方案，详见 MASTER-PLAN.md §3）。"""

from __future__ import annotations

import logging

from backend.core.exceptions import (
    SubscriptionError,
    SymbolAlreadyExistsError,
    SymbolNotFoundError,
)
from backend.core.time_utils import now_ms
from backend.models import Subscription

from ..db import Database

logger = logging.getLogger("storage.subscription")


def _normalize(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    if not s:
        raise SubscriptionError("symbol 不能为空")
    if not s.isalnum():
        raise SubscriptionError("symbol 只能包含字母数字")
    if len(s) > 16:
        raise SubscriptionError("symbol 长度超限（≤ 16）")
    return s


def _row_to_model(row) -> Subscription:
    return Subscription(
        symbol=row["symbol"],
        display_order=row["display_order"],
        active=bool(row["active"]),
        added_at=row["added_at"],
        last_viewed_at=row["last_viewed_at"],
    )


class SubscriptionRepository:
    """方案 B：添加即 active=1，可手动停用，可移除。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ─── 查询 ───

    async def list_all(self) -> list[Subscription]:
        rows = await self._db.fetchall(
            "SELECT * FROM subscriptions ORDER BY display_order ASC, added_at ASC"
        )
        return [_row_to_model(r) for r in rows]

    async def list_active(self) -> list[Subscription]:
        rows = await self._db.fetchall(
            "SELECT * FROM subscriptions WHERE active=1 "
            "ORDER BY display_order ASC, added_at ASC"
        )
        return [_row_to_model(r) for r in rows]

    async def get(self, symbol: str) -> Subscription | None:
        symbol = _normalize(symbol)
        row = await self._db.fetchone(
            "SELECT * FROM subscriptions WHERE symbol=?",
            (symbol,),
        )
        return _row_to_model(row) if row else None

    async def count(self) -> int:
        n = await self._db.fetch_scalar("SELECT COUNT(1) FROM subscriptions")
        return int(n or 0)

    # ─── 写入 ───

    async def add(self, symbol: str, *, display_order: int | None = None) -> Subscription:
        symbol = _normalize(symbol)
        existing = await self.get(symbol)
        if existing is not None:
            raise SymbolAlreadyExistsError(f"{symbol} 已存在")

        if display_order is None:
            display_order = (await self.count())  # 追加到末尾

        added_at = now_ms()
        await self._db.execute(
            "INSERT INTO subscriptions(symbol, display_order, active, added_at) "
            "VALUES (?, ?, 1, ?)",
            (symbol, display_order, added_at),
        )
        logger.info(
            f"添加币种 {symbol}",
            extra={"tags": ["LIFECYCLE"], "context": {"symbol": symbol}},
        )
        sub = await self.get(symbol)
        assert sub is not None
        return sub

    async def remove(self, symbol: str) -> None:
        symbol = _normalize(symbol)
        existing = await self.get(symbol)
        if existing is None:
            raise SymbolNotFoundError(f"{symbol} 不存在")
        await self._db.execute(
            "DELETE FROM subscriptions WHERE symbol=?",
            (symbol,),
        )
        logger.info(
            f"移除币种 {symbol}",
            extra={"tags": ["LIFECYCLE"], "context": {"symbol": symbol}},
        )

    async def set_active(self, symbol: str, active: bool) -> Subscription:
        symbol = _normalize(symbol)
        existing = await self.get(symbol)
        if existing is None:
            raise SymbolNotFoundError(f"{symbol} 不存在")
        await self._db.execute(
            "UPDATE subscriptions SET active=? WHERE symbol=?",
            (1 if active else 0, symbol),
        )
        logger.info(
            f"币种 {symbol} {'激活' if active else '停用'}",
            extra={
                "tags": ["LIFECYCLE"],
                "context": {"symbol": symbol, "active": active},
            },
        )
        sub = await self.get(symbol)
        assert sub is not None
        return sub

    async def touch_viewed(self, symbol: str) -> None:
        symbol = _normalize(symbol)
        await self._db.execute(
            "UPDATE subscriptions SET last_viewed_at=? WHERE symbol=?",
            (now_ms(), symbol),
        )

    async def reorder(self, ordering: list[str]) -> None:
        norm = [_normalize(s) for s in ordering]
        async with self._db.transaction() as conn:
            for idx, sym in enumerate(norm):
                await conn.execute(
                    "UPDATE subscriptions SET display_order=? WHERE symbol=?",
                    (idx, sym),
                )

    # ─── 启动初始化 ───

    async def ensure_defaults(self, default_symbols: list[str]) -> list[Subscription]:
        """首次启动：若表空，按 default_symbols 顺序插入；否则原样返回。"""
        existing = await self.list_all()
        if existing:
            return existing
        results: list[Subscription] = []
        for idx, raw_sym in enumerate(default_symbols):
            sub = await self.add(raw_sym, display_order=idx)
            results.append(sub)
        logger.info(
            f"subscriptions 初始化完成: {[s.symbol for s in results]}",
            extra={"tags": ["LIFECYCLE"]},
        )
        return results
