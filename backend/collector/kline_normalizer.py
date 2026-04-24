"""K 线归一化与入库。

设计决策（来自 docs/upstream-api/ATOMS.md）：
- HFD 响应中的 klines 字段**丢弃**，用 Binance/OKX 真源
- 这里提供统一入口：从 ExchangeClient 拉 → 存 atoms_klines
"""

from __future__ import annotations

from backend.core.logging import Tags, get_logger
from backend.storage.repositories.kline import KlineRepository

from .exchange_client import ExchangeClient

logger = get_logger("collector.kline")


class KlineNormalizer:
    def __init__(
        self,
        *,
        exchange: ExchangeClient,
        repo: KlineRepository,
    ) -> None:
        self._exchange = exchange
        self._repo = repo

    async def refresh(
        self,
        *,
        symbol: str,
        tf: str,
        limit: int = 500,
    ) -> int:
        """拉一批最新 K 线并入库。返回新写入/覆盖的条数。"""
        klines = await self._exchange.fetch_klines(symbol=symbol, tf=tf, limit=limit)
        if not klines:
            logger.warning(
                f"K 线返回空: {symbol} {tf}",
                extra={"context": {"symbol": symbol, "tf": tf}},
            )
            return 0
        n = await self._repo.upsert_many(klines)
        logger.info(
            f"K 线入库 {symbol} {tf} 条数={n} 最新={klines[-1].ts}",
            extra={
                "tags": [Tags.TICK],
                "context": {
                    "symbol": symbol,
                    "tf": tf,
                    "count": n,
                    "latest_ts": klines[-1].ts,
                    "source": klines[-1].source,
                },
            },
        )
        return n
