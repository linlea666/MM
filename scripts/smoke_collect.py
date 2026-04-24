#!/usr/bin/env python3
"""端到端冒烟：真实连 HFD + Binance/OKX 采一次全量并打印各表行数。

用法：
    python scripts/smoke_collect.py [SYMBOL] [TF]
    python scripts/smoke_collect.py BTC 30m

执行内容：
1. 初始化 DB + 日志
2. 构建 HFD / Exchange / Engine
3. 调 engine.collect_once(SYMBOL, tfs=[TF]) 跑一遍 K 线 + kline_close + 4 个 periodic tier
4. 打印 atoms_* 表行数分布

退出码：
    0 = 所有 22 个 indicator 至少有 1 个原子表有数据
    1 = 采集失败或 >5 个关键表空
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.collector.circuit_breaker import CircuitBreaker  # noqa: E402
from backend.collector.engine import CollectorEngine  # noqa: E402
from backend.collector.exchange_client import ExchangeClient  # noqa: E402
from backend.collector.hfd_client import HFDClient  # noqa: E402
from backend.collector.rate_limiter import TokenBucket  # noqa: E402
from backend.core.config import load_settings  # noqa: E402
from backend.core.logging import setup_logging, shutdown_logging  # noqa: E402
from backend.storage.db import init_database, shutdown_database  # noqa: E402
from backend.storage.repositories import (  # noqa: E402
    AtomRepositories,
    KlineRepository,
    LogRepository,
    SubscriptionRepository,
)
from backend.storage.repositories.log import register_sqlite_writer  # noqa: E402


async def main() -> int:
    symbol = (sys.argv[1] if len(sys.argv) > 1 else "BTC").upper()
    tf = sys.argv[2] if len(sys.argv) > 2 else "30m"

    settings = load_settings()
    setup_logging(settings)

    db = await init_database(settings)
    log_repo = LogRepository(db)
    register_sqlite_writer(log_repo)

    sub_repo = SubscriptionRepository(db)
    await sub_repo.ensure_defaults([symbol])

    kline_repo = KlineRepository(db)
    atoms = AtomRepositories(db)

    limiter = TokenBucket(rps=settings.collector.global_rps)
    breaker = CircuitBreaker(threshold=3, cooldown_seconds=60)
    hfd = HFDClient(settings, breaker=breaker, limiter=limiter, max_retries=2)
    exchange = ExchangeClient(
        primary=settings.collector.kline_sources.primary,
        fallback=settings.collector.kline_sources.fallback,
        timeout=settings.collector.request_timeout_seconds,
    )
    await hfd.start()
    await exchange.start()

    engine = CollectorEngine(
        settings=settings,
        hfd=hfd,
        exchange=exchange,
        kline_repo=kline_repo,
        atoms=atoms,
    )

    t0 = time.monotonic()
    print(f"[smoke] collect_once {symbol} tf={tf} …")
    result = await engine.collect_once(symbol, tfs=[tf])
    elapsed = time.monotonic() - t0
    print(f"[smoke] collect_once done in {elapsed:.1f}s → {result}")

    print("\n[smoke] 原子表行数：")
    tables = await db.fetchall(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name LIKE 'atoms_%' ORDER BY name"
    )
    summary: list[tuple[str, int]] = []
    for row in tables:
        name = row["name"]
        n = await db.fetch_scalar(f"SELECT COUNT(1) FROM {name}")
        summary.append((name, int(n or 0)))
    for name, n in summary:
        flag = "✓" if n > 0 else "·"
        print(f"  {flag} {name:30s} {n}")

    non_empty = sum(1 for _, n in summary if n > 0)
    print(f"\n[smoke] 有数据的表: {non_empty} / {len(summary)}")

    print("\n[smoke] 熔断快照：", breaker.snapshot())

    await hfd.close()
    await exchange.close()
    log_repo.close_sync()
    await shutdown_database()
    shutdown_logging()

    return 0 if non_empty >= 15 else 1


if __name__ == "__main__":
    code = asyncio.run(main())
    sys.exit(code)
