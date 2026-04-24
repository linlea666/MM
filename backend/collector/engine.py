"""采集编排器。

职责：
- 按 tier/tf 并发拉取 HFD indicators
- 调用 parser 解析 → 原子模型
- 根据 parser 声明（upsert / replace_for）写入对应 atom repo
- 统一错误处理、节拍日志

暴露两个 public 方法：
- ``tick_kline_close(symbol, tf)``  K 线收盘后刷新（kline + kline_close tier）
- ``tick_periodic(symbol, tf, tier)`` 周期 tier 刷新
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any

from backend.core.config import Settings
from backend.core.exceptions import HFDError
from backend.core.logging import Tags, get_logger
from backend.storage.repositories import AtomRepositories, KlineRepository

from .exchange_client import ExchangeClient
from .hfd_client import HFDClient
from .kline_normalizer import KlineNormalizer
from .parsers import ParserResult, parse_all

logger = get_logger("collector.engine")


class CollectorEngine:
    def __init__(
        self,
        *,
        settings: Settings,
        hfd: HFDClient,
        exchange: ExchangeClient,
        kline_repo: KlineRepository,
        atoms: AtomRepositories,
    ) -> None:
        self._settings = settings
        self._hfd = hfd
        self._exchange = exchange
        self._atoms = atoms
        self._kline_norm = KlineNormalizer(exchange=exchange, repo=kline_repo)

    # ─── 公共 API（供 scheduler 调用） ───

    async def tick_kline_close(self, symbol: str, tf: str) -> None:
        """K 线收盘触发：先刷 Binance kline，再并发拉 kline_close tier indicators。"""
        try:
            await self._kline_norm.refresh(symbol=symbol, tf=tf, limit=500)
        except Exception as e:  # noqa: BLE001
            logger.error(
                f"K 线刷新失败 {symbol} {tf}: {e}",
                extra={
                    "tags": [Tags.TICK, Tags.FETCH_FAIL],
                    "context": {"symbol": symbol, "tf": tf, "error": str(e)},
                },
                exc_info=True,
            )
        indicators = self._settings.collector.schedule.kline_close
        await self._fetch_persist_batch(symbol, tf, indicators, tier="kline_close")

    async def tick_periodic(self, symbol: str, tf: str, tier: str) -> None:
        indicators = self._get_tier(tier)
        if not indicators:
            return
        await self._fetch_persist_batch(symbol, tf, indicators, tier=tier)

    async def collect_once(self, symbol: str, *, tfs: Iterable[str] | None = None) -> dict:
        """首次添加 / 重新激活时立刻采集一轮（所有 tier）。返回成败统计。"""
        tfs = list(tfs or self._settings.collector.timeframes)
        tasks = []
        for tf in tfs:
            tasks.append(self.tick_kline_close(symbol, tf))
            for tier in ("every_5min", "every_30min", "every_1h", "every_4h"):
                tasks.append(self.tick_periodic(symbol, tf, tier))
        await asyncio.gather(*tasks, return_exceptions=True)
        return {"symbol": symbol, "tfs": tfs}

    # ─── 内部 ───

    def _get_tier(self, tier: str) -> list[str]:
        sched = self._settings.collector.schedule
        mapping = {
            "kline_close": sched.kline_close,
            "every_5min": sched.every_5min,
            "every_30min": sched.every_30min,
            "every_1h": sched.every_1h,
            "every_4h": sched.every_4h,
        }
        return list(mapping.get(tier) or [])

    async def _fetch_persist_batch(
        self,
        symbol: str,
        tf: str,
        indicators: list[str],
        *,
        tier: str,
    ) -> None:
        if not indicators:
            return
        # 并发拉（由令牌桶限流），单个失败不影响其他
        async def _one(ind: str) -> tuple[str, dict | Exception]:
            try:
                payload = await self._hfd.fetch(symbol=symbol, indicator=ind, tf=tf)
                return ind, payload
            except Exception as e:  # noqa: BLE001
                return ind, e

        results = await asyncio.gather(*(_one(ind) for ind in indicators))

        ok = 0
        failed = 0
        total_atoms = 0
        for ind, payload in results:
            if isinstance(payload, Exception):
                failed += 1
                continue
            try:
                parsed = parse_all(symbol=symbol, tf=tf, indicator=ind, payload=payload)
                await self._persist(parsed)
                ok += 1
                total_atoms += parsed.total()
            except Exception as e:  # noqa: BLE001
                failed += 1
                logger.error(
                    f"持久化失败 {ind} {symbol} {tf}: {e}",
                    extra={
                        "tags": [Tags.TICK],
                        "context": {
                            "symbol": symbol,
                            "tf": tf,
                            "indicator": ind,
                            "error": str(e),
                        },
                    },
                    exc_info=True,
                )

        level_tag = [Tags.TICK]
        msg = (
            f"[{tier}] {symbol} {tf} ok={ok}/{len(indicators)} failed={failed} "
            f"atoms={total_atoms}"
        )
        if failed:
            logger.warning(
                msg,
                extra={
                    "tags": level_tag + [Tags.FETCH_FAIL],
                    "context": {
                        "symbol": symbol,
                        "tf": tf,
                        "tier": tier,
                        "ok": ok,
                        "failed": failed,
                        "atoms": total_atoms,
                    },
                },
            )
        else:
            logger.info(
                msg,
                extra={
                    "tags": level_tag,
                    "context": {
                        "symbol": symbol,
                        "tf": tf,
                        "tier": tier,
                        "ok": ok,
                        "atoms": total_atoms,
                    },
                },
            )

    async def _persist(self, parsed: ParserResult) -> None:
        """按 AtomRepositories 字段名分发 upsert / replace_for。"""
        for key, models in parsed.atoms.items():
            repo = getattr(self._atoms, key, None)
            if repo is None:
                logger.debug(f"未知 atom key: {key}")
                continue
            scope = parsed.replace_scopes.get(key)
            if scope is not None:
                await repo.replace_for(scope, models)
            else:
                await repo.upsert_many(models)
