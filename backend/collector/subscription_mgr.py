"""订阅管理：添加即常驻 + 手动停用（方案 B）。

生命周期：
    add(symbol)         → 校验 Binance + HFD → DB 写入 active=1 → scheduler 注册 jobs
                          → 触发一次 collect_once（不阻塞返回）
    activate(symbol)    → DB UPDATE active=1 → scheduler 注册 → 触发 collect_once
    deactivate(symbol)  → scheduler 移除 jobs → DB UPDATE active=0 （数据保留）
    remove(symbol)      → scheduler 移除 jobs → DB DELETE row
                          （atom 表数据保留，可手动 TRUNCATE）

校验：
    Binance exchangeInfo（权威）或 OKX instruments（兜底）
    HFD probe smart_money_cost?coin={X}（超时 5s）
"""

from __future__ import annotations

import asyncio

from backend.core.exceptions import (
    HFDError,
    SubscriptionError,
    SymbolAlreadyExistsError,
    SymbolNotFoundError,
)
from backend.core.logging import Tags, get_logger
from backend.models import Subscription
from backend.storage.repositories import SubscriptionRepository

from .engine import CollectorEngine
from .exchange_client import ExchangeClient
from .hfd_client import HFDClient
from .scheduler import CollectorScheduler

logger = get_logger("collector.subscription_mgr")


class SubscriptionManager:
    def __init__(
        self,
        *,
        repo: SubscriptionRepository,
        hfd: HFDClient,
        exchange: ExchangeClient,
        scheduler: CollectorScheduler,
        engine: CollectorEngine,
    ) -> None:
        self._repo = repo
        self._hfd = hfd
        self._exchange = exchange
        self._scheduler = scheduler
        self._engine = engine

    # ─── 启动初始化 ───

    async def startup(self, default_symbols: list[str]) -> list[Subscription]:
        """启动时：确保默认币种存在，为 active=1 的币注册 scheduler jobs，
        并立即触发一次全量采集（避免等下一根 K 线收盘才有数据）。"""
        await self._repo.ensure_defaults(default_symbols)
        active = await self._repo.list_active()
        for sub in active:
            self._scheduler.add_symbol(sub.symbol)
        logger.info(
            f"订阅初始化完成: 激活 {len(active)} 币种",
            extra={
                "tags": [Tags.SUBSCRIPTION],
                "context": {"active_symbols": [s.symbol for s in active]},
            },
        )
        for sub in active:
            asyncio.create_task(self._safe_collect_once(sub.symbol))
        return active

    # ─── CRUD ───

    async def list_all(self) -> list[Subscription]:
        return await self._repo.list_all()

    async def add(self, symbol: str, *, skip_validation: bool = False) -> Subscription:
        symbol = symbol.upper().strip()
        if not symbol.isalnum() or len(symbol) > 16:
            raise SubscriptionError(f"symbol 格式非法: {symbol}")

        existing = await self._repo.get(symbol)
        if existing is not None:
            raise SymbolAlreadyExistsError(f"{symbol} 已存在")

        if not skip_validation:
            await self._validate(symbol)

        sub = await self._repo.add(symbol)
        self._scheduler.add_symbol(symbol)
        logger.info(
            f"新增订阅 {symbol}",
            extra={
                "tags": [Tags.SUBSCRIPTION],
                "context": {"symbol": symbol},
            },
        )
        # 异步触发一次立即采集（不阻塞）
        asyncio.create_task(self._safe_collect_once(symbol))
        return sub

    async def activate(self, symbol: str) -> Subscription:
        symbol = symbol.upper().strip()
        sub = await self._repo.get(symbol)
        if sub is None:
            raise SymbolNotFoundError(f"{symbol} 未订阅")
        if sub.active:
            return sub
        sub = await self._repo.set_active(symbol, active=True)
        self._scheduler.add_symbol(symbol)
        logger.info(
            f"激活订阅 {symbol}",
            extra={
                "tags": [Tags.SUBSCRIPTION],
                "context": {"symbol": symbol},
            },
        )
        asyncio.create_task(self._safe_collect_once(symbol))
        return sub

    async def deactivate(self, symbol: str) -> Subscription:
        symbol = symbol.upper().strip()
        sub = await self._repo.get(symbol)
        if sub is None:
            raise SymbolNotFoundError(f"{symbol} 未订阅")
        if not sub.active:
            return sub
        self._scheduler.remove_symbol(symbol)
        sub = await self._repo.set_active(symbol, active=False)
        logger.info(
            f"停用订阅 {symbol}",
            extra={
                "tags": [Tags.SUBSCRIPTION],
                "context": {"symbol": symbol},
            },
        )
        return sub

    async def remove(self, symbol: str) -> None:
        symbol = symbol.upper().strip()
        sub = await self._repo.get(symbol)
        if sub is None:
            raise SymbolNotFoundError(f"{symbol} 未订阅")
        self._scheduler.remove_symbol(symbol)
        await self._repo.remove(symbol)
        logger.info(
            f"移除订阅 {symbol}",
            extra={
                "tags": [Tags.SUBSCRIPTION],
                "context": {"symbol": symbol},
            },
        )

    # ─── 校验 ───

    async def _validate(self, symbol: str) -> None:
        exists = await self._exchange.symbol_exists(symbol)
        if not exists:
            raise SubscriptionError(
                f"交易所不存在 {symbol}USDT",
                detail={"symbol": symbol, "checked": ["binance", "okx"]},
            )
        try:
            ok = await self._hfd.probe(symbol=symbol)
        except Exception as e:  # noqa: BLE001
            raise SubscriptionError(
                f"HFD probe 异常: {e}", detail={"symbol": symbol}
            ) from e
        if not ok:
            raise SubscriptionError(
                f"HFD 不支持 {symbol}",
                detail={"symbol": symbol, "probe_indicator": "smart_money_cost"},
            )

    # ─── 内部 ───

    async def _safe_collect_once(self, symbol: str) -> None:
        try:
            await self._engine.collect_once(symbol)
        except Exception as e:  # noqa: BLE001
            logger.error(
                f"首次采集失败 {symbol}: {e}",
                extra={
                    "tags": [Tags.TICK, Tags.SUBSCRIPTION],
                    "context": {"symbol": symbol, "error": str(e)},
                },
                exc_info=True,
            )
