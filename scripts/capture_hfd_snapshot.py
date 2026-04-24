#!/usr/bin/env python3
"""抓取 HFD + 交易所 K 线快照，持久化到 fixture 目录供 E2E 回放测试使用。

用法::

    python scripts/capture_hfd_snapshot.py                   # BTC 30m, 默认输出目录
    python scripts/capture_hfd_snapshot.py --symbol BTC --tf 30m
    python scripts/capture_hfd_snapshot.py --symbol BTC --tf 30m --out backend/tests/fixtures/upstream

输出布局::

    backend/tests/fixtures/upstream/BTC_30m_20260424T160000Z/
      ├── _meta.json                     # symbol/tf/captured_at_ms/anchor_ts/counts
      ├── klines.json                    # Binance K 线原始数组
      └── <indicator>.json               # HFD 22 端点各一份原始响应

设计要点：
- 单币种一次全量，所有端点都抓（包含因 schedule 去重而平时不拉的 6 个：
  fair_value / fvg / imbalance / ob_decay / inst_volume_profile 等）。
- K 线用 Binance 真源，limit=500，和运行时 collector 一致。
- 失败的端点不中断全流程，在最终 summary 里标出。
- 不写数据库、不触发 parser，只保存原始字节 → fixture 永远是"官方响应"而不是"我们解析后的结果"。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.collector.circuit_breaker import CircuitBreaker  # noqa: E402
from backend.collector.exchange_client import ExchangeClient  # noqa: E402
from backend.collector.hfd_client import (  # noqa: E402
    EXPERIMENTAL_INDICATORS,
    HFD_INDICATORS,
    HFDClient,
)
from backend.collector.rate_limiter import TokenBucket  # noqa: E402
from backend.core.config import load_settings  # noqa: E402


def _ts_folder_name(symbol: str, tf: str, ts_ms: int) -> str:
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=UTC)
    return f"{symbol.upper()}_{tf}_{dt.strftime('%Y%m%dT%H%M%SZ')}"


async def _capture_one(
    hfd: HFDClient, symbol: str, tf: str, indicator: str
) -> tuple[str, dict[str, Any] | Exception]:
    try:
        payload = await hfd.fetch(symbol=symbol, indicator=indicator, tf=tf)
        return indicator, payload
    except Exception as e:  # noqa: BLE001
        return indicator, e


def _count_rows(payload: dict[str, Any]) -> int:
    """粗略统计响应行数——取最大的 list 字段长度。"""
    best = 0
    for v in payload.values():
        if isinstance(v, list):
            best = max(best, len(v))
    return best


async def main() -> int:
    parser = argparse.ArgumentParser(description="Capture HFD + Binance snapshot fixtures")
    parser.add_argument("--symbol", default="BTC")
    parser.add_argument("--tf", default="30m")
    parser.add_argument(
        "--out",
        default=str(ROOT / "backend" / "tests" / "fixtures" / "upstream"),
        help="fixture 根目录（自动创建子目录）",
    )
    parser.add_argument(
        "--klines-limit", type=int, default=500, help="K 线抓取条数"
    )
    parser.add_argument(
        "--include-experimental",
        action="store_true",
        default=True,
        help="是否同时抓 EXPERIMENTAL_INDICATORS（默认开）",
    )
    parser.add_argument(
        "--no-experimental",
        dest="include_experimental",
        action="store_false",
        help="只抓主链路 22 个，跳过实验指标",
    )
    args = parser.parse_args()

    symbol = args.symbol.upper()
    tf = args.tf
    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)

    captured_at_ms = int(time.time() * 1000)
    folder = out_root / _ts_folder_name(symbol, tf, captured_at_ms)
    folder.mkdir(parents=True, exist_ok=True)

    print(f"[capture] → {folder}")
    print(f"[capture] symbol={symbol} tf={tf} captured_at={captured_at_ms}")

    settings = load_settings()
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

    anchor_ts: int | None = None
    counts: dict[str, int] = {}
    failures: list[tuple[str, str]] = []

    try:
        # 1) Binance K 线（充当 anchor）
        try:
            klines = await exchange.fetch_klines(
                symbol=symbol, tf=tf, limit=args.klines_limit
            )
            if klines:
                anchor_ts = klines[-1].ts
                (folder / "klines.json").write_text(
                    json.dumps(
                        [
                            {
                                "ts": k.ts,
                                "open": k.open,
                                "high": k.high,
                                "low": k.low,
                                "close": k.close,
                                "volume": k.volume,
                                "source": k.source,
                            }
                            for k in klines
                        ],
                        indent=2,
                    )
                )
                counts["klines"] = len(klines)
                print(f"[capture] klines ok: {len(klines)} bars, anchor_ts={anchor_ts}")
            else:
                failures.append(("klines", "empty"))
                print("[capture] klines 空")
        except Exception as e:  # noqa: BLE001
            failures.append(("klines", str(e)))
            print(f"[capture] klines FAIL: {e}")

        # 2) HFD 指标（主链路 22 + 可选实验 7）
        to_fetch: tuple[str, ...] = HFD_INDICATORS
        if args.include_experimental:
            to_fetch = HFD_INDICATORS + EXPERIMENTAL_INDICATORS
            print(
                f"[capture] 含实验指标: {len(EXPERIMENTAL_INDICATORS)} 个 → "
                f"{', '.join(EXPERIMENTAL_INDICATORS)}"
            )
        results = await asyncio.gather(
            *(_capture_one(hfd, symbol, tf, ind) for ind in to_fetch)
        )
        experimental_set = set(EXPERIMENTAL_INDICATORS)
        for ind, payload in results:
            tag = " [EXP]" if ind in experimental_set else ""
            if isinstance(payload, Exception):
                failures.append((ind, str(payload)))
                print(f"[capture] {ind:30s}{tag} FAIL: {payload}")
                continue
            (folder / f"{ind}.json").write_text(
                json.dumps(payload, indent=2, ensure_ascii=False)
            )
            n = _count_rows(payload)
            counts[ind] = n
            print(f"[capture] {ind:30s}{tag} ok ({n} rows)")
    finally:
        await hfd.close()
        await exchange.close()

    # 3) _meta.json
    meta = {
        "symbol": symbol,
        "tf": tf,
        "captured_at_ms": captured_at_ms,
        "captured_at_iso": datetime.fromtimestamp(
            captured_at_ms / 1000, tz=UTC
        ).isoformat(),
        "anchor_ts": anchor_ts,
        "hfd_indicators": list(HFD_INDICATORS),
        "experimental_indicators": list(EXPERIMENTAL_INDICATORS)
        if args.include_experimental
        else [],
        "counts": counts,
        "failures": {ind: msg for ind, msg in failures},
        "notes": "raw HFD/Binance responses; consumed by tests/test_e2e_replay.py",
    }
    (folder / "_meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False)
    )

    total = len(HFD_INDICATORS) + 1  # +1 = klines
    if args.include_experimental:
        total += len(EXPERIMENTAL_INDICATORS)
    ok = total - len(failures)
    print()
    print(f"[capture] 完成 {ok}/{total} 成功，写入 {folder.relative_to(ROOT)}")
    if failures:
        print(f"[capture] 失败条目（{len(failures)}）：")
        for ind, msg in failures:
            print(f"    - {ind}: {msg[:120]}")

    print(f"[capture] breaker: {breaker.snapshot()}")
    return 0 if ok >= total - 2 else 1  # 最多允许 2 个端点失败


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
