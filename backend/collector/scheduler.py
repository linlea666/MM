"""APScheduler 封装：按订阅动态管理 (symbol, tf, tier) 任务。

任务 ID 规则：
  collector:{tier}:{symbol}:{tf}
  tier ∈ {kline_close, every_5min, every_30min, every_1h, every_4h}

TF 对齐：
  - kline_close  : cron 对齐到每根 K 线收盘后 N 秒
  - every_5min   : cron 每 5 分钟
  - every_30min  : cron 每半点
  - every_1h     : cron 整点
  - every_4h     : cron 整点 % 4

注：trend_saturation 只和 symbol 绑定（tf 无意义，由 HFD 自身维度决定），
但我们为一致性仍按 (symbol, tf) 触发——HFD 会返回相同数据 upsert 一次，代价可忽略。
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.core.config import Settings
from backend.core.logging import Tags, get_logger
from backend.core.time_utils import tf_to_ms

from .engine import CollectorEngine

logger = get_logger("collector.scheduler")


_TIERS = ("kline_close", "every_5min", "every_30min", "every_1h", "every_4h")


def _kline_close_trigger(tf: str, delay_seconds: int = 5) -> CronTrigger:
    """按 tf 产生 cron 触发器，时间偏移 delay_seconds（UTC）。"""
    step_ms = tf_to_ms(tf)
    if step_ms < 60_000:  # < 1m
        raise ValueError(f"不支持亚分钟级 tf: {tf}")
    minutes_per_tf = step_ms // 60_000
    if tf.endswith("m"):
        expr = f"*/{minutes_per_tf}"
        return CronTrigger(minute=expr, second=delay_seconds)
    if tf.endswith("h"):
        hours = minutes_per_tf // 60
        return CronTrigger(hour=f"*/{hours}", minute=0, second=delay_seconds)
    if tf == "1d":
        return CronTrigger(hour=0, minute=0, second=delay_seconds)
    raise ValueError(f"不支持 tf: {tf}")


def _periodic_trigger(tier: str) -> CronTrigger:
    if tier == "every_5min":
        return CronTrigger(minute="*/5", second=2)
    if tier == "every_30min":
        return CronTrigger(minute="*/30", second=3)
    if tier == "every_1h":
        return CronTrigger(minute=0, second=4)
    if tier == "every_4h":
        return CronTrigger(hour="*/4", minute=0, second=10)
    raise ValueError(f"未知 tier: {tier}")


class CollectorScheduler:
    def __init__(self, *, settings: Settings, engine: CollectorEngine) -> None:
        self._settings = settings
        self._engine = engine
        self._scheduler = AsyncIOScheduler(timezone="UTC")

    @property
    def running(self) -> bool:
        return self._scheduler.running

    def start(self) -> None:
        if not self._scheduler.running:
            self._scheduler.start()
            logger.info(
                "APScheduler 启动",
                extra={"tags": [Tags.SCHED], "context": {}},
            )

    def shutdown(self, wait: bool = True) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=wait)
            logger.info(
                "APScheduler 停止",
                extra={"tags": [Tags.SCHED], "context": {}},
            )

    # ─── 动态管理 ───

    def add_symbol(self, symbol: str) -> list[str]:
        """为一个 symbol 注册它在所有 tier × tf 下的 job。返回 job_id 列表。"""
        symbol = symbol.upper()
        tfs = self._settings.collector.timeframes
        delay = self._settings.collector.schedule_delay_seconds
        added: list[str] = []

        for tf in tfs:
            jid = self._job_id("kline_close", symbol, tf)
            if self._scheduler.get_job(jid) is None:
                self._scheduler.add_job(
                    self._wrap(self._engine.tick_kline_close, symbol, tf),
                    trigger=_kline_close_trigger(tf, delay),
                    id=jid,
                    max_instances=1,
                    coalesce=True,
                    misfire_grace_time=60,
                )
                added.append(jid)

        for tier in ("every_5min", "every_30min", "every_1h", "every_4h"):
            if not self._settings.collector.schedule.__getattribute__(tier):
                continue
            for tf in tfs:
                jid = self._job_id(tier, symbol, tf)
                if self._scheduler.get_job(jid) is None:
                    self._scheduler.add_job(
                        self._wrap_periodic(symbol, tf, tier),
                        trigger=_periodic_trigger(tier),
                        id=jid,
                        max_instances=1,
                        coalesce=True,
                        misfire_grace_time=120,
                    )
                    added.append(jid)

        logger.info(
            f"注册采集任务 {symbol} × {len(tfs)} tfs × {len(_TIERS)} tiers → 新增 {len(added)}",
            extra={
                "tags": [Tags.SCHED, Tags.SUBSCRIPTION],
                "context": {"symbol": symbol, "added_jobs": len(added), "tfs": tfs},
            },
        )
        return added

    def remove_symbol(self, symbol: str) -> int:
        """移除某 symbol 的所有 job。"""
        symbol = symbol.upper()
        removed = 0
        for job in list(self._scheduler.get_jobs()):
            parts = job.id.split(":")
            if len(parts) >= 4 and parts[0] == "collector" and parts[2] == symbol:
                self._scheduler.remove_job(job.id)
                removed += 1
        logger.info(
            f"移除采集任务 {symbol} → 移除 {removed}",
            extra={
                "tags": [Tags.SCHED, Tags.SUBSCRIPTION],
                "context": {"symbol": symbol, "removed_jobs": removed},
            },
        )
        return removed

    def list_jobs(self) -> list[dict]:
        out = []
        for job in self._scheduler.get_jobs():
            out.append(
                {
                    "id": job.id,
                    "trigger": str(job.trigger),
                    "next_run_time": (
                        job.next_run_time.isoformat()
                        if job.next_run_time else None
                    ),
                }
            )
        return out

    # ─── 内部辅助 ───

    @staticmethod
    def _job_id(tier: str, symbol: str, tf: str) -> str:
        return f"collector:{tier}:{symbol}:{tf}"

    def _wrap(
        self,
        fn: Callable[[str, str], Coroutine[Any, Any, Any]],
        symbol: str,
        tf: str,
    ):
        async def _run():
            try:
                await fn(symbol, tf)
            except Exception as e:  # noqa: BLE001
                logger.error(
                    f"scheduler 任务失败 {symbol} {tf}: {e}",
                    extra={
                        "tags": [Tags.SCHED],
                        "context": {"symbol": symbol, "tf": tf, "error": str(e)},
                    },
                    exc_info=True,
                )
        return _run

    def _wrap_periodic(self, symbol: str, tf: str, tier: str):
        async def _run():
            try:
                await self._engine.tick_periodic(symbol, tf, tier)
            except Exception as e:  # noqa: BLE001
                logger.error(
                    f"scheduler periodic 失败 {symbol} {tf} {tier}: {e}",
                    extra={
                        "tags": [Tags.SCHED],
                        "context": {
                            "symbol": symbol,
                            "tf": tf,
                            "tier": tier,
                            "error": str(e),
                        },
                    },
                    exc_info=True,
                )
        return _run
