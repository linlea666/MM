"""V1.1 · Phase 9 · LLM Provider 抽象层。

``LLMProvider`` 约束三点：
1. 纯异步 ``complete_json(messages, schema)`` 入口；
2. 返回 ``LLMResponse``（含 parsed Pydantic 对象 + tokens + latency）；
3. 实现方要自己处理 OpenAI 兼容 API、重试、超时、连接超时。

内置两个实现：
- ``DeepSeekProvider``  —— 生产默认（openai 兼容 /v1/chat/completions）
- ``StubProvider``      —— 测试 / 无 Key 场景；返回预先构造好的 fixture
"""

from __future__ import annotations

from backend.ai.providers.base import LLMProvider, LLMResponse, ProviderError
from backend.ai.providers.deepseek import DeepSeekProvider
from backend.ai.providers.stub import StubProvider

__all__ = [
    "DeepSeekProvider",
    "LLMProvider",
    "LLMResponse",
    "ProviderError",
    "StubProvider",
]
