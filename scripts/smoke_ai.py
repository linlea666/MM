"""V1.1 · Phase 9 · DeepSeek 端到端冒烟脚本（真 LLM）。

用途：
- 验证 prompt（A 阶段改造后）能让 DeepSeek v4 输出被 Pydantic 严格接受的 JSON；
- 验证 DeepSeekProvider 的 httpx / json_object / usage 解析路径；
- 打印真实 tokens / latency，作为定价基准。

运行：
    export DEEPSEEK_API_KEY="sk-xxx"
    python scripts/smoke_ai.py

也可：
    python scripts/smoke_ai.py --key sk-xxx --skip-pro

注意：
- 本脚本不读任何 yaml / 不写任何文件；key 只走环境变量或 --key 参数；
- 跑完 log 脱敏（key 只显示首尾各 4 位）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.ai.agents import (  # noqa: E402
    run_money_flow_agent,
    run_trade_plan_agent,
    run_trend_agent,
)
from backend.ai.providers import DeepSeekProvider, ProviderError  # noqa: E402
from backend.ai.schemas import AIObserverInput  # noqa: E402


def mask(key: str) -> str:
    if not key or len(key) < 8:
        return "****"
    return f"{key[:4]}…{key[-4:]}"


# ═══ 真实风格的 BTC 快照（构造时模拟当前市场状态） ═══════════════════

def make_fake_btc_input() -> AIObserverInput:
    """构造一个"正常交易日 + 轻微多头偏向"的 BTC 快照，让 LLM 有东西做。

    数据口径贴合 V1.1 AIObserverInput schema，所有字段都在合理范围。
    """
    return AIObserverInput(
        symbol="BTC",
        tf="30m",
        anchor_ts=int(time.time() * 1000),
        last_price=92_350.0,
        atr=420.0,
        # 趋势 / 价值
        vwap_last=92_100.0,
        vwap_slope_pct=0.08,
        fair_value_delta_pct=0.27,
        trend_purity="Bullish",
        # 动能
        cvd_slope=18.2,
        cvd_sign="up",
        cvd_converge_ratio=0.42,
        imbalance_green_ratio=0.58,
        imbalance_red_ratio=0.42,
        poc_shift_trend="up",
        power_imbalance_streak=3,
        power_imbalance_streak_side="buy",
        trend_exhaustion_streak=0,
        trend_exhaustion_streak_type="none",
        # 主力事件
        resonance_buy_count=6,
        resonance_sell_count=2,
        sweep_count_recent=1,
        whale_net_direction="buy",
        # 关键位
        nearest_resistance_price=92_850.0,
        nearest_resistance_distance_pct=0.54,
        nearest_support_price=91_700.0,
        nearest_support_distance_pct=-0.70,
        just_broke_resistance=False,
        just_broke_support=False,
        pierce_atr_ratio=0.6,
        pierce_recovered=True,
        # V1.1 指标视图
        choch_latest_kind="CHoCH",
        choch_latest_direction="bullish",
        choch_latest_distance_pct=0.35,
        choch_latest_bars_since=3,
        cascade_bands_top=[
            {"side": "long_fuel", "avg_price": 91_450.0, "strength": 0.82},
            {"side": "long_fuel", "avg_price": 91_200.0, "strength": 0.71},
            {"side": "short_fuel", "avg_price": 92_900.0, "strength": 0.64},
            {"side": "short_fuel", "avg_price": 93_400.0, "strength": 0.48},
        ],
        retail_stop_bands_top=[
            {"side": "long_fuel", "avg_price": 91_620.0, "strength": 0.55},
            {"side": "short_fuel", "avg_price": 92_780.0, "strength": 0.46},
        ],
        segment_portrait={
            "start_time": int(time.time() * 1000) - 6 * 3600 * 1000,
            "roi_pct": 2.8,
            "roi_remaining_pct": 55.0,
            "pain_drawdown_pct": 4.2,
            "time_elapsed_bars": 12,
            "time_window_expected_bars": 30,
            "dd_tolerance_status": "healthy",
        },
        volume_profile={
            "poc": 92_050.0,
            "va_low": 91_400.0,
            "va_high": 92_750.0,
            "last_price_position": "in_va",
            "top_n": [
                {"price": 92_050.0, "volume_ratio": 1.0},
                {"price": 91_800.0, "volume_ratio": 0.72},
                {"price": 92_400.0, "volume_ratio": 0.58},
            ],
        },
        time_heatmap={
            "current_hour": 15,
            "peak_hours": [14, 15, 16, 21, 22],
            "dead_hours": [3, 4, 5],
            "rank": 3,
            "active": True,
            "current_activity": 0.78,
        },
        trend_saturation_progress=0.42,
        trend_saturation_type="Accumulation",
        stale_tables=[],
    )


# ═══ 每层 runner（带计时 + 错误捕获 + 结果 dump） ═══════════════════

async def run_layer(
    name: str,
    coro,
) -> dict:
    """run coroutine，捕获所有结果，统一输出字段。"""
    started = time.perf_counter()
    print(f"\n── {name} ─────────────────────────────────────")
    try:
        result = await coro
        elapsed = (time.perf_counter() - started) * 1000
        if result.output is None:
            print(f"  ✗ 失败：{result.error}")
            return {"ok": False, "error": result.error, "layer": name}
        print(f"  ✓ 模型：{result.model}")
        print(f"  ✓ 延迟：{result.latency_ms} ms（wall {elapsed:.0f} ms）")
        print(f"  ✓ tokens：{result.usage}")
        print(f"  ✓ parsed JSON（truncated）：")
        dump = result.output.model_dump()
        pretty = json.dumps(dump, ensure_ascii=False, indent=2)
        for line in pretty.split("\n")[:40]:
            print(f"    {line}")
        if len(pretty.split("\n")) > 40:
            print(f"    …({len(pretty.split(chr(10))) - 40} more lines)")
        return {
            "ok": True,
            "layer": name,
            "model": result.model,
            "latency_ms": result.latency_ms,
            "usage": result.usage,
            "output": result.output,
        }
    except ProviderError as e:
        print(f"  ✗ ProviderError[{e.kind}]：{e}")
        if e.raw:
            print(f"    原始响应（前 1500 字符）：\n    {e.raw[:1500]}")
        return {"ok": False, "error": f"[{e.kind}] {e}", "layer": name}
    except Exception as e:
        print(f"  ✗ 未分类异常：{type(e).__name__}: {e}")
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "layer": name}


async def main(args) -> int:
    key = args.key or os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        print("错误：请通过 --key 或 DEEPSEEK_API_KEY 环境变量提供 key。")
        return 2

    tier = (args.tier or "flash").lower()
    if tier not in ("flash", "pro"):
        print(f"错误：--tier 只能是 flash/pro，收到 {tier}")
        return 2

    print(f"DeepSeek Smoke Test  key={mask(key)}  base_url=default")
    print(f"tier={tier}  thinking={args.thinking}  skip_pro={args.skip_pro}")
    print("=" * 72)

    provider = DeepSeekProvider(api_key=key)

    # 根据参数决定三层共用的 tier + thinking
    common_kwargs = {
        "model_tier": tier,
        "thinking_enabled": args.thinking,
        # thinking 开启时延迟显著变长（DeepSeek 实测可到 60s+）
        "timeout_s": 90.0 if args.thinking else (45.0 if tier == "pro" else 20.0),
    }

    # 0. ping
    print("\n── 0. PING（10s timeout）──────────────────────────")
    ok = await provider.ping()
    print(f"  {'✓ 连通正常' if ok else '✗ ping 失败'}")
    if not ok:
        await provider.aclose()
        return 3

    payload = make_fake_btc_input()
    print(f"\n输入快照：symbol={payload.symbol} tf={payload.tf}  "
          f"last_price={payload.last_price}  CHoCH={payload.choch_latest_kind}/{payload.choch_latest_direction}")

    results: list[dict] = []

    # 1. Layer 1
    r1 = await run_layer(
        f"1. TrendClassifier ({tier})",
        run_trend_agent(provider=provider, payload=payload, **common_kwargs),
    )
    results.append(r1)

    # 2. Layer 2（prior = trend narrative）
    trend_narrative = None
    if r1["ok"]:
        trend_narrative = r1["output"].narrative
    r2 = await run_layer(
        f"2. MoneyFlowReader ({tier})",
        run_money_flow_agent(
            provider=provider, payload=payload, trend_narrative=trend_narrative, **common_kwargs
        ),
    )
    results.append(r2)

    # 3. Layer 3（同样用 tier，可跳过）
    if not args.skip_pro:
        mf_narrative = None
        if r2["ok"]:
            mf_narrative = r2["output"].narrative
        r3 = await run_layer(
            f"3. TradePlanner ({tier})",
            run_trade_plan_agent(
                provider=provider,
                payload=payload,
                trend_narrative=trend_narrative,
                money_flow_narrative=mf_narrative,
                **common_kwargs,
            ),
        )
        results.append(r3)

    await provider.aclose()

    # 汇总
    print("\n" + "=" * 72)
    print("汇总：")
    total_tokens = 0
    total_latency = 0
    ok_count = 0
    for r in results:
        status = "✓" if r["ok"] else "✗"
        print(f"  {status} {r['layer']}")
        if r["ok"]:
            ok_count += 1
            total_tokens += r["usage"].get("total_tokens", 0)
            total_latency += r["latency_ms"]
    print(f"\n成功 {ok_count}/{len(results)}  "
          f"总 tokens={total_tokens}  总延迟={total_latency} ms")
    return 0 if ok_count == len(results) else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", type=str, default="", help="DeepSeek API key（优先级高于 env）")
    ap.add_argument("--tier", type=str, default="flash", choices=["flash", "pro"],
                    help="三层统一使用的 model tier（默认 flash）")
    ap.add_argument("--thinking", action="store_true",
                    help="开启 DeepSeek V4 thinking 模式（会关掉 json_object + temperature）")
    ap.add_argument("--skip-pro", action="store_true", help="跳过 L3（省 tokens）")
    args = ap.parse_args()
    sys.exit(asyncio.run(main(args)))
