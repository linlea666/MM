#!/usr/bin/env python3
"""HFD 稳定性独立监控脚本。

独立进程，不依赖主 API/采集器，避免互相影响。每分钟轮询一次 HFD
的 22 个 indicator（BTC/30m），记录响应时间、HTTP 状态、JSON 字段缺失情况。

输出：
- stdout：每轮打印 PASS/FAIL 统计
- logs/hfd_monitor.jsonl：每次请求一条 JSON 记录
- （可选）连续失败 >= 3 次时触发一条 ERROR 行到 stdout

使用：
    python scripts/hfd_monitor.py                 # 轮询 BTC 30m
    python scripts/hfd_monitor.py --symbols BTC,ETH --tf 30m --interval 60

依赖：项目 backend/ 目录下的 venv；可直接在服务器上 cron/systemd 拉起。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.collector.circuit_breaker import CircuitBreaker  # noqa: E402
from backend.collector.hfd_client import HFD_INDICATORS, HFDClient  # noqa: E402
from backend.collector.rate_limiter import TokenBucket  # noqa: E402
from backend.core.config import load_settings  # noqa: E402


@dataclass
class IndicatorStat:
    ok: int = 0
    fail: int = 0
    avg_ms: float = 0.0
    errors: list[str] = field(default_factory=list)

    def record(self, elapsed_ms: float, err: str | None) -> None:
        if err:
            self.fail += 1
            self.errors.append(err)
        else:
            self.ok += 1
            n = self.ok
            self.avg_ms = ((self.avg_ms * (n - 1)) + elapsed_ms) / n


async def probe_once(
    client: HFDClient,
    symbols: list[str],
    tf: str,
    out_file,
) -> dict[tuple[str, str], IndicatorStat]:
    stats: dict[tuple[str, str], IndicatorStat] = {
        (sym, ind): IndicatorStat() for sym in symbols for ind in HFD_INDICATORS
    }
    tasks = []

    async def _one(sym: str, ind: str) -> None:
        t0 = time.monotonic()
        err: str | None = None
        status: str = "ok"
        try:
            data = await client.fetch(symbol=sym, indicator=ind, tf=tf)
            if not isinstance(data, dict) or not data:
                err = "empty_response"
                status = "empty"
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"[:200]
            status = "fail"
        elapsed_ms = (time.monotonic() - t0) * 1000
        stats[(sym, ind)].record(elapsed_ms, err)
        record = {
            "ts": int(time.time() * 1000),
            "symbol": sym,
            "indicator": ind,
            "tf": tf,
            "elapsed_ms": round(elapsed_ms, 1),
            "status": status,
            "error": err,
        }
        out_file.write(json.dumps(record, ensure_ascii=False) + "\n")
        out_file.flush()

    for sym in symbols:
        for ind in HFD_INDICATORS:
            tasks.append(_one(sym, ind))
    await asyncio.gather(*tasks)
    return stats


def summarize_round(stats: dict[tuple[str, str], IndicatorStat]) -> dict:
    total = sum(s.ok + s.fail for s in stats.values())
    ok = sum(s.ok for s in stats.values())
    fail = sum(s.fail for s in stats.values())
    slow = [(k, s) for k, s in stats.items() if s.ok and s.avg_ms > 3000]
    errs = [
        {"symbol": k[0], "indicator": k[1], "errors": s.errors[:2]}
        for k, s in stats.items()
        if s.fail
    ]
    return {
        "total": total,
        "ok": ok,
        "fail": fail,
        "slow_count": len(slow),
        "errors": errs[:10],
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default="BTC")
    parser.add_argument("--tf", default="30m")
    parser.add_argument("--interval", type=int, default=60, help="秒")
    parser.add_argument("--output", default=str(ROOT / "logs" / "hfd_monitor.jsonl"))
    parser.add_argument("--rounds", type=int, default=0, help="0=无限")
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    settings = load_settings()
    limiter = TokenBucket(rps=settings.collector.global_rps)
    breaker = CircuitBreaker(threshold=3, cooldown_seconds=60.0)
    client = HFDClient(settings, breaker=breaker, limiter=limiter, max_retries=1)
    await client.start()

    round_idx = 0
    consecutive_fails = 0
    print(f"[hfd_monitor] start symbols={symbols} tf={args.tf} interval={args.interval}s output={out_path}")

    try:
        while True:
            round_idx += 1
            t0 = time.monotonic()
            with out_path.open("a", encoding="utf-8") as f:
                stats = await probe_once(client, symbols, args.tf, f)
            summary = summarize_round(stats)
            elapsed = time.monotonic() - t0
            line = (
                f"[hfd_monitor] round={round_idx} "
                f"ok={summary['ok']}/{summary['total']} "
                f"fail={summary['fail']} slow={summary['slow_count']} "
                f"took={elapsed:.1f}s"
            )
            if summary["fail"] == summary["total"]:
                consecutive_fails += 1
                line += f" [TOTAL_DOWN x{consecutive_fails}]"
            elif summary["fail"] > 0:
                consecutive_fails = 0
                line += f" errors={summary['errors'][:3]}"
            else:
                consecutive_fails = 0
            print(line, flush=True)
            if consecutive_fails >= 3:
                print(
                    f"[hfd_monitor][ERROR] HFD 连续 {consecutive_fails} 轮全挂，请人工检查",
                    flush=True,
                )

            if args.rounds and round_idx >= args.rounds:
                break
            await asyncio.sleep(args.interval)
    finally:
        await client.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[hfd_monitor] stop")
