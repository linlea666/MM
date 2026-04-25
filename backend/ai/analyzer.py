"""V1.1 · AI 深度分析编排器（DeepAnalyzer · Layer 4）。

设计取舍：
- **不复用 ``AIObserver``**：observer 受节流 / 缓存约束、且不保留 raw_payloads；
  深度分析路径要保证四层都"干净跑一次"，三段原文（system/user/raw）全部留盘。
- **四层串行 + 一次并行**：
    1) ``L1 TrendClassifier`` 与 ``L2 MoneyFlowReader`` 并行（独立可并发）；
    2) ``L3 TradePlanner``：拿到 L1/L2 narrative 后串行（强依赖）；
    3) ``L4 DeepAnalyzer``：再串行，喂入前三层 narrative 产出研报。
- **失败容忍**：任一层失败仍写一份 ``AnalysisReport(status='error', error_reason=...)``，
  原始 prompt 仍然落盘（便于排查）。

线程/并发：``analyze()`` 内部用 asyncio.gather；外层不需要再加锁。
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from backend.ai.agents import (
    AgentResult,
    run_deep_analyze_agent,
    run_money_flow_agent,
    run_trade_plan_agent,
    run_trend_agent,
)
from backend.ai.observer import build_observer_input
from backend.ai.providers.base import LLMProvider
from backend.ai.schemas import (
    AIRawPayloadDump,
    AnalysisReport,
    DeepAnalyzeLayerOut,
    MoneyFlowLayerOut,
    TradePlanLayerOut,
    TrendLayerOut,
)
from backend.ai.storage import AnalysisReportStore
from backend.rules.features import FeatureSnapshot

logger = logging.getLogger("ai.analyzer")


def _build_report_id(symbol: str, tf: str, ts_ms: int) -> str:
    """形如 ``20260425T143058Z-BTC-1h``，URL-safe + 全局唯一（精确到秒）。"""
    dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
    return f"{dt.strftime('%Y%m%dT%H%M%SZ')}-{symbol}-{tf}"


def _payload_dump(r: AgentResult) -> AIRawPayloadDump:
    return AIRawPayloadDump(
        layer=r.layer,
        model=r.model,
        tokens_total=int((r.usage or {}).get("total_tokens", 0)),
        latency_ms=r.latency_ms,
        system_prompt=r.system_prompt,
        user_prompt=r.user_prompt,
        raw_response=r.raw_response,
    )


class DeepAnalyzer:
    """L1+L2+L3+L4 编排 + AnalysisReport 持久化。"""

    def __init__(
        self,
        *,
        provider: LLMProvider,
        report_store: AnalysisReportStore,
        model_tier: str = "flash",
        thinking_enabled: bool = False,
        timeout_s_l1: float = 30.0,
        timeout_s_l2: float = 30.0,
        timeout_s_l3: float = 60.0,
        timeout_s_l4: float = 90.0,
        max_tokens_l4: int = 4096,
    ) -> None:
        self._provider = provider
        self._store = report_store
        self._tier = model_tier
        self._thinking = thinking_enabled
        self._t1 = timeout_s_l1
        self._t2 = timeout_s_l2
        self._t3 = timeout_s_l3
        self._t4 = timeout_s_l4
        self._max_l4 = max_tokens_l4
        self._lock = asyncio.Lock()

    async def analyze(self, snap: FeatureSnapshot) -> AnalysisReport:
        """主入口：跑四层并落盘一条 AnalysisReport。"""
        async with self._lock:  # 同一 analyzer 串行，避免并发烧 token
            return await self._analyze_unsafe(snap)

    async def _analyze_unsafe(self, snap: FeatureSnapshot) -> AnalysisReport:
        ts_ms = int(time.time() * 1000)
        report_id = _build_report_id(snap.symbol, snap.tf, ts_ms)
        payload = build_observer_input(snap)
        data_slice = payload.model_dump_json(indent=2)

        started = time.perf_counter()

        # L1 + L2 并行
        r1, r2 = await asyncio.gather(
            run_trend_agent(
                provider=self._provider,
                payload=payload,
                model_tier=self._tier,
                timeout_s=self._t1,
                thinking_enabled=self._thinking,
            ),
            run_money_flow_agent(
                provider=self._provider,
                payload=payload,
                trend_narrative=None,
                model_tier=self._tier,
                timeout_s=self._t2,
                thinking_enabled=self._thinking,
            ),
        )
        trend_out: TrendLayerOut | None = r1.output  # type: ignore[assignment]
        mf_out: MoneyFlowLayerOut | None = r2.output  # type: ignore[assignment]

        # L3 强制跑（深度分析里用户希望看到完整计划评估）
        r3 = await run_trade_plan_agent(
            provider=self._provider,
            payload=payload,
            trend_narrative=trend_out.narrative if trend_out else None,
            money_flow_narrative=mf_out.narrative if mf_out else None,
            model_tier=self._tier,
            timeout_s=self._t3,
            thinking_enabled=self._thinking,
        )
        plan_out: TradePlanLayerOut | None = r3.output  # type: ignore[assignment]

        # L4 综合
        r4 = await run_deep_analyze_agent(
            provider=self._provider,
            payload=payload,
            trend_narrative=trend_out.narrative if trend_out else None,
            money_flow_narrative=mf_out.narrative if mf_out else None,
            trade_plan_narrative=plan_out.narrative if plan_out else None,
            model_tier=self._tier,
            max_tokens=self._max_l4,
            timeout_s=self._t4,
            thinking_enabled=self._thinking,
        )
        deep_out: DeepAnalyzeLayerOut | None = r4.output  # type: ignore[assignment]

        total_latency_ms = int((time.perf_counter() - started) * 1000)

        # 汇总 token / 错误
        total_tokens = 0
        errors: list[str] = []
        for r in (r1, r2, r3, r4):
            total_tokens += int((r.usage or {}).get("total_tokens", 0))
            if r.error:
                errors.append(f"{r.layer}: {r.error}")

        # 状态判定：只要 L4 出来就算 ok（L1-L3 缺失，L4 仍然能给出"无判定"研报）
        if deep_out is None:
            status: str = "error"
            error_reason = "; ".join(errors) or "deep_analyze 层失败"
            one_line = ""
            report_md = ""
        else:
            status = "ok"
            error_reason = "; ".join(errors) if errors else None
            one_line = deep_out.one_line
            report_md = deep_out.report_md

        report = AnalysisReport(
            id=report_id,
            ts=ts_ms,
            symbol=snap.symbol,
            tf=snap.tf,
            model_tier=self._tier,  # type: ignore[arg-type]
            thinking_enabled=self._thinking,
            status=status,  # type: ignore[arg-type]
            error_reason=error_reason,
            total_tokens=total_tokens,
            total_latency_ms=total_latency_ms,
            one_line=one_line,
            report_md=report_md,
            raw_payloads=[_payload_dump(r) for r in (r1, r2, r3, r4)],
            data_slice=data_slice,
        )

        await self._store.append(report)
        logger.info(
            f"AI deep analyze {snap.symbol}/{snap.tf} status={status} "
            f"latency={total_latency_ms}ms tokens={total_tokens} id={report_id}",
            extra={"tags": ["AI"], "context": {"errors": errors[:3]}},
        )
        return report
