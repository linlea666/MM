"""V1.1 · Phase 9 · AI 观察层（统一模型架构）。

三层 pipeline：
    Layer 1 · TrendClassifier   —— 趋势分类（方向/阶段/强度）
    Layer 2 · MoneyFlowReader   —— 主力动向（bands/VP/timeHeatmap/whale）
    Layer 3 · TradePlanner      —— 交易计划（仅高置信或手动触发）

V1.1 说明：三层共用 ``ai.model_tier``（flash/pro）+ ``ai.thinking_enabled``
决定的同一模型；L3 仍然有阈值 gate（``auto_trend_confidence`` 等），
但不再硬编码"L3 必须 pro"。

默认 provider: deepseek（openai 兼容）。StubProvider 用于本地测试 / 单元测试。

模块结构：
    schemas.py   —— 所有 Pydantic 输入/输出契约
    providers/   —— LLM 客户端抽象（base / deepseek / stub）
    agents/      —— 三层 agent（封装 prompt + provider 调用 + 结果解析）
    prompts/     —— 纯文本 prompt 模板
    observer.py  —— 编排（触发/冷却/缓存/升级 + 与 RuleRunner 异步协作）
    storage.py   —— 内存环形 + jsonl 落盘
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# ────────────────────────────────────────────────────────────
# 循环依赖警戒：
# - ``backend.models`` → ``backend.ai.schemas`` （纯 Pydantic，无副作用 OK）
# - ``backend.ai.observer / service`` → ``backend.rules.features`` → ``backend.models``
# 为避免 ``import backend.ai.schemas`` 触发 observer 间接引用 models 的循环，
# 本 __init__ 只 eager 暴露 **纯数据类 & 轻量 helper**，重逻辑走懒加载（``__getattr__``）。
# ────────────────────────────────────────────────────────────

from backend.ai.config import AIRuntimeConfig, build_from_rules, mask_secret
from backend.ai.schemas import (
    AIObserverFeed,
    AIObserverFeedItem,
    AIObserverInput,
    AIObserverSummary,
    MoneyFlowLayerOut,
    TradePlanLayerOut,
    TrendLayerOut,
)

if TYPE_CHECKING:  # 仅供静态类型使用，不触发运行时导入
    from backend.ai.observer import AIObserver, ObserverSettings  # noqa: F401
    from backend.ai.service import AIObservationService  # noqa: F401

__all__ = [
    "AIObservationService",
    "AIObserver",
    "AIObserverFeed",
    "AIObserverFeedItem",
    "AIObserverInput",
    "AIObserverSummary",
    "AIRuntimeConfig",
    "MoneyFlowLayerOut",
    "ObserverSettings",
    "TradePlanLayerOut",
    "TrendLayerOut",
    "build_from_rules",
    "mask_secret",
]


def __getattr__(name: str):  # PEP 562 懒加载
    if name in {"AIObserver", "ObserverSettings"}:
        from backend.ai import observer as _obs
        return getattr(_obs, name)
    if name == "AIObservationService":
        from backend.ai import service as _svc
        return _svc.AIObservationService
    raise AttributeError(f"module 'backend.ai' has no attribute {name!r}")
