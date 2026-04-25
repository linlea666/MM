"""V1.1 · Phase 9 · 三层 AI agents。

每个 agent 都是纯函数 + 单次调用：
- 输入：``AIObserverInput`` + 上游层结果（可选）
- 输出：对应 schema 的 Pydantic 实例 + 元信息
- 失败：统一抛 ``ProviderError``，由 observer 捕获降级

agent 不持有 provider；所有 LLM 客户端由 observer 注入，便于单测替换 StubProvider。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from pydantic import BaseModel

from backend.ai.prompts import (
    COMMON_RULES,
    DEEP_ANALYZE_SYSTEM_PROMPT,
    MONEY_FLOW_SYSTEM_PROMPT,
    TRADE_PLAN_SYSTEM_PROMPT,
    TREND_SYSTEM_PROMPT,
    build_user_message,
)
from backend.ai.providers.base import LLMProvider, ProviderError
from backend.ai.schemas import (
    AIObserverInput,
    DeepAnalyzeLayerOut,
    MoneyFlowLayerOut,
    TradePlanLayerOut,
    TrendLayerOut,
)

logger = logging.getLogger("ai.agents")


@dataclass
class AgentResult:
    """agent 运行结果包装，供 observer 聚合。

    V1.1 · ``system_prompt / user_prompt / raw_response`` 用于 AnalysisReport 的
    "AI 交互过程原文"展示（图 5）。三段非空才能给前端做跨模型对照。
    """

    layer: str                        # "trend" / "money_flow" / "trade_plan" / "deep_analyze"
    output: BaseModel | None          # 对应 schema 实例（失败时 None）
    model: str
    usage: dict[str, int]
    latency_ms: int
    error: str | None = None
    system_prompt: str = ""
    user_prompt: str = ""
    raw_response: str = ""


async def run_trend_agent(
    *,
    provider: LLMProvider,
    payload: AIObserverInput,
    model_tier: str = "flash",
    temperature: float = 0.2,
    max_tokens: int = 512,
    timeout_s: float = 20.0,
    thinking_enabled: bool = False,
) -> AgentResult:
    """Layer 1 · 趋势分类。"""
    model_name = provider.models.get(model_tier, model_tier)
    system = f"{COMMON_RULES}\n\n{TREND_SYSTEM_PROMPT}"
    user = build_user_message(layer="Layer 1 · TrendClassifier", payload_json=payload.model_dump_json())
    started = time.perf_counter()
    try:
        resp = await provider.complete_json(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            schema=TrendLayerOut,
            model=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_s=timeout_s,
            thinking_enabled=thinking_enabled,
        )
    except ProviderError as e:
        logger.warning(
            f"trend agent failed: {e}", extra={"tags": ["AI"], "context": {"kind": e.kind}}
        )
        return AgentResult(
            layer="trend",
            output=None,
            model=model_name,
            usage={},
            latency_ms=int((time.perf_counter() - started) * 1000),
            error=str(e),
        )
    return AgentResult(
        layer="trend",
        output=resp.parsed,
        model=resp.model or model_name,
        usage=resp.usage,
        latency_ms=resp.latency_ms,
        system_prompt=resp.system_prompt,
        user_prompt=resp.user_prompt,
        raw_response=resp.text,
    )


async def run_money_flow_agent(
    *,
    provider: LLMProvider,
    payload: AIObserverInput,
    trend_narrative: str | None = None,
    model_tier: str = "flash",
    temperature: float = 0.2,
    max_tokens: int = 700,
    timeout_s: float = 20.0,
    thinking_enabled: bool = False,
) -> AgentResult:
    """Layer 2 · 主力动向。带上游 trend 结论（若有）。"""
    model_name = provider.models.get(model_tier, model_tier)
    system = f"{COMMON_RULES}\n\n{MONEY_FLOW_SYSTEM_PROMPT}"
    prior = {"Layer 1 · TrendClassifier": trend_narrative} if trend_narrative else None
    user = build_user_message(
        layer="Layer 2 · MoneyFlowReader",
        payload_json=payload.model_dump_json(),
        prior_outputs=prior,
    )
    started = time.perf_counter()
    try:
        resp = await provider.complete_json(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            schema=MoneyFlowLayerOut,
            model=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_s=timeout_s,
            thinking_enabled=thinking_enabled,
        )
    except ProviderError as e:
        logger.warning(
            f"money_flow agent failed: {e}",
            extra={"tags": ["AI"], "context": {"kind": e.kind}},
        )
        return AgentResult(
            layer="money_flow",
            output=None,
            model=model_name,
            usage={},
            latency_ms=int((time.perf_counter() - started) * 1000),
            error=str(e),
        )
    return AgentResult(
        layer="money_flow",
        output=resp.parsed,
        model=resp.model or model_name,
        usage=resp.usage,
        latency_ms=resp.latency_ms,
        system_prompt=resp.system_prompt,
        user_prompt=resp.user_prompt,
        raw_response=resp.text,
    )


async def run_trade_plan_agent(
    *,
    provider: LLMProvider,
    payload: AIObserverInput,
    trend_narrative: str | None = None,
    money_flow_narrative: str | None = None,
    model_tier: str = "pro",
    temperature: float = 0.15,
    max_tokens: int = 900,
    timeout_s: float = 45.0,  # pro 模型更慢；实测 25s 不够，>40s 才稳
    thinking_enabled: bool = False,
) -> AgentResult:
    """Layer 3 · 交易计划（Pro，慢且贵）。"""
    model_name = provider.models.get(model_tier, model_tier)
    system = f"{COMMON_RULES}\n\n{TRADE_PLAN_SYSTEM_PROMPT}"
    prior: dict[str, str] = {}
    if trend_narrative:
        prior["Layer 1 · TrendClassifier"] = trend_narrative
    if money_flow_narrative:
        prior["Layer 2 · MoneyFlowReader"] = money_flow_narrative
    user = build_user_message(
        layer="Layer 3 · TradePlanner",
        payload_json=payload.model_dump_json(),
        prior_outputs=prior or None,
    )
    started = time.perf_counter()
    try:
        resp = await provider.complete_json(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            schema=TradePlanLayerOut,
            model=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_s=timeout_s,
            thinking_enabled=thinking_enabled,
        )
    except ProviderError as e:
        logger.warning(
            f"trade_plan agent failed: {e}",
            extra={"tags": ["AI"], "context": {"kind": e.kind}},
        )
        return AgentResult(
            layer="trade_plan",
            output=None,
            model=model_name,
            usage={},
            latency_ms=int((time.perf_counter() - started) * 1000),
            error=str(e),
        )
    return AgentResult(
        layer="trade_plan",
        output=resp.parsed,
        model=resp.model or model_name,
        usage=resp.usage,
        latency_ms=resp.latency_ms,
        system_prompt=resp.system_prompt,
        user_prompt=resp.user_prompt,
        raw_response=resp.text,
    )


async def run_deep_analyze_agent(
    *,
    provider: LLMProvider,
    payload: AIObserverInput,
    trend_narrative: str | None = None,
    money_flow_narrative: str | None = None,
    trade_plan_narrative: str | None = None,
    model_tier: str = "flash",
    temperature: float = 0.25,
    max_tokens: int = 4096,
    timeout_s: float = 90.0,
    thinking_enabled: bool = False,
) -> AgentResult:
    """Layer 4 · 深度研报。

    流程上由 ``analyzer`` 编排：先跑 L1+L2+L3 拿三段 narrative，再喂给本层。
    本层默认 ``flash``（用户选 pro 时整套切 pro），输出长 markdown，token 较多。
    """
    model_name = provider.models.get(model_tier, model_tier)
    system = f"{COMMON_RULES}\n\n{DEEP_ANALYZE_SYSTEM_PROMPT}"
    prior: dict[str, str] = {}
    if trend_narrative:
        prior["Layer 1 · TrendClassifier"] = trend_narrative
    if money_flow_narrative:
        prior["Layer 2 · MoneyFlowReader"] = money_flow_narrative
    if trade_plan_narrative:
        prior["Layer 3 · TradePlanner"] = trade_plan_narrative
    user = build_user_message(
        layer="Layer 4 · DeepAnalyzer",
        payload_json=payload.model_dump_json(),
        prior_outputs=prior or None,
    )
    started = time.perf_counter()
    try:
        resp = await provider.complete_json(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            schema=DeepAnalyzeLayerOut,
            model=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_s=timeout_s,
            thinking_enabled=thinking_enabled,
        )
    except ProviderError as e:
        logger.warning(
            f"deep_analyze agent failed: {e}",
            extra={"tags": ["AI"], "context": {"kind": e.kind}},
        )
        return AgentResult(
            layer="deep_analyze",
            output=None,
            model=model_name,
            usage={},
            latency_ms=int((time.perf_counter() - started) * 1000),
            error=str(e),
            system_prompt=system,
            user_prompt=user,
            raw_response="",
        )
    return AgentResult(
        layer="deep_analyze",
        output=resp.parsed,
        model=resp.model or model_name,
        usage=resp.usage,
        latency_ms=resp.latency_ms,
        system_prompt=resp.system_prompt,
        user_prompt=resp.user_prompt,
        raw_response=resp.text,
    )
