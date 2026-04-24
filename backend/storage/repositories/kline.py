"""K 线 repository（atoms_klines 表）。

K 线是所有指标共享的基础数据，单独一个 repo。
其它原子的 repo 在 Step 2 的 parser 实现时一并完成。
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from backend.models import Kline

from ..db import Database

logger = logging.getLogger("storage.kline")


class KlineRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def upsert(self, kline: Kline) -> None:
        await self._db.execute(
            """
            INSERT INTO atoms_klines(symbol, tf, ts, open, high, low, close, volume, source)
            VALUES (:symbol, :tf, :ts, :open, :high, :low, :close, :volume, :source)
            ON CONFLICT(symbol, tf, ts) DO UPDATE SET
                open=excluded.open,
                high=excluded.high,
                low=excluded.low,
                close=excluded.close,
                volume=excluded.volume,
                source=excluded.source
            """,
            kline.model_dump(),
        )

    async def upsert_many(self, klines: Iterable[Kline]) -> int:
        rows = [k.model_dump() for k in klines]
        if not rows:
            return 0
        await self._db.executemany(
            """
            INSERT INTO atoms_klines(symbol, tf, ts, open, high, low, close, volume, source)
            VALUES (:symbol, :tf, :ts, :open, :high, :low, :close, :volume, :source)
            ON CONFLICT(symbol, tf, ts) DO UPDATE SET
                open=excluded.open,
                high=excluded.high,
                low=excluded.low,
                close=excluded.close,
                volume=excluded.volume,
                source=excluded.source
            """,
            rows,
        )
        return len(rows)

    async def latest(self, symbol: str, tf: str) -> Kline | None:
        row = await self._db.fetchone(
            "SELECT * FROM atoms_klines WHERE symbol=? AND tf=? "
            "ORDER BY ts DESC LIMIT 1",
            (symbol, tf),
        )
        return _row(row) if row else None

    async def fetch_range(
        self,
        symbol: str,
        tf: str,
        *,
        since_ms: int | None = None,
        until_ms: int | None = None,
        limit: int | None = None,
    ) -> list[Kline]:
        sql = "SELECT * FROM atoms_klines WHERE symbol=? AND tf=?"
        params: list = [symbol, tf]
        if since_ms is not None:
            sql += " AND ts >= ?"
            params.append(since_ms)
        if until_ms is not None:
            sql += " AND ts <= ?"
            params.append(until_ms)
        sql += " ORDER BY ts ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        rows = await self._db.fetchall(sql, tuple(params))
        return [_row(r) for r in rows]

    async def count(self, symbol: str, tf: str) -> int:
        n = await self._db.fetch_scalar(
            "SELECT COUNT(1) FROM atoms_klines WHERE symbol=? AND tf=?",
            (symbol, tf),
        )
        return int(n or 0)


def _row(row) -> Kline:
    return Kline(
        symbol=row["symbol"],
        tf=row["tf"],
        ts=row["ts"],
        open=row["open"],
        high=row["high"],
        low=row["low"],
        close=row["close"],
        volume=row["volume"],
        source=row["source"],
    )
