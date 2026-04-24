"""LLM Provider 基类 + 通用响应对象。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class ProviderError(RuntimeError):
    """所有 Provider 调用失败统一抛这个。
    
    包含 ``kind`` 让调用方区分是 "超时/网络/鉴权/解析/额度"，
    方便 observer 层做降级决策（超时可重试、鉴权 / 解析要直接降级）。
    """

    def __init__(
        self,
        kind: Literal["timeout", "network", "auth", "quota", "parse", "unknown"],
        message: str,
        *,
        status: int | None = None,
        raw: str | None = None,
    ) -> None:
        super().__init__(f"[{kind}] {message}")
        self.kind = kind
        self.status = status
        self.raw = raw


@dataclass
class LLMResponse:
    """Provider 统一返回。

    - ``text`` 永远是原始字符串（便于审计）；
    - ``parsed`` 是按 schema 解析后的 Pydantic 对象（失败则抛 ParseError）；
    - ``usage`` 字段来自 provider（OpenAI 兼容里是 usage.prompt_tokens 等）。
    """

    text: str
    parsed: BaseModel | None = None
    usage: dict[str, int] = field(default_factory=dict)
    latency_ms: int = 0
    model: str = ""


class LLMProvider(ABC):
    """LLM Provider 接口。实现方负责：
    1. 建 httpx.AsyncClient 或复用；
    2. 超时 / 重试（基类不干预，避免重试策略耦合）；
    3. 把 OpenAI 兼容 schema 适配到自家 API。
    """

    name: str = "base"
    models: dict[str, str] = {}  # e.g. {"flash": "deepseek-v4-flash", "pro": "deepseek-v4-pro"}

    @abstractmethod
    async def complete_json(
        self,
        *,
        messages: list[dict[str, Any]],
        schema: type[T],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        timeout_s: float = 20.0,
        thinking_enabled: bool = False,
    ) -> LLMResponse:
        """发一次 chat/completions 并用 ``schema`` 解析 JSON。

        约定：
        - ``messages`` 是 OpenAI 标准格式 ``[{"role":"system","content":"..."},...]``；
        - Provider 内部负责开启 json_object 模式或手工提取 JSON；
        - 解析失败 → ``ProviderError("parse", ...)``。
        - ``thinking_enabled``：
          - ``False``（默认）：走标准 json_object 模式，输出稳定；
          - ``True``：开启模型思维链（仅支持的 provider 生效，例如 DeepSeek V4）。
            注意：部分 provider（DeepSeek V4）官方明确"thinking 与 json_object 不可组合"，
            开启后 provider 会自动去掉 ``response_format=json_object`` 并忽略 ``temperature``，
            仅靠 prompt 里的"只输出 JSON"强约束 + 兜底解析。
        """
        ...

    @abstractmethod
    async def ping(self) -> bool:
        """连通性探活，用于 ``POST /api/ai/test``。"""
        ...

    async def aclose(self) -> None:  # noqa: B027 - 子类可选实现
        """关闭底层 httpx 客户端。"""
        return None
