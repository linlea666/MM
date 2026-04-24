"""Stub Provider：单元测试 / 无 Key 场景的 fake LLM。

两种模式：
1. ``fixtures={layer_name: schema_instance}``：按层返回预先构造好的输出；
2. ``generator=callable``：每次调用动态生成；

Stub 不发网络请求，延迟 ``latency_ms=0``，token 虚拟。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel

from backend.ai.providers.base import LLMProvider, LLMResponse, ProviderError, T


class StubProvider(LLMProvider):
    name = "stub"

    def __init__(
        self,
        *,
        fixtures: dict[str, BaseModel] | None = None,
        generator: Callable[[type[BaseModel], dict[str, Any]], Awaitable[BaseModel]] | None = None,
        raise_kind: str | None = None,
    ) -> None:
        """
        Parameters
        ----------
        fixtures : dict[schema_name, instance]
            按 schema 类名查表返回对应 BaseModel。
        generator : async (schema, context) -> BaseModel
            运行时生成；优先级高于 fixtures。
        raise_kind : str
            调试用 —— 设置后每次调用都抛 ProviderError(kind=raise_kind)。
        """
        self._fixtures = fixtures or {}
        self._generator = generator
        self._raise_kind = raise_kind
        self.models = {"flash": "stub-flash", "pro": "stub-pro"}

    async def complete_json(
        self,
        *,
        messages: list[dict[str, Any]],
        schema: type[T],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        timeout_s: float = 20.0,
        thinking_enabled: bool = False,  # noqa: ARG002 - stub 忽略
    ) -> LLMResponse:
        if self._raise_kind:
            raise ProviderError(self._raise_kind, f"stub 强制失败 kind={self._raise_kind}")  # type: ignore[arg-type]

        if self._generator is not None:
            parsed = await self._generator(schema, {"messages": messages, "model": model})
        else:
            key = schema.__name__
            if key not in self._fixtures:
                raise ProviderError(
                    "parse",
                    f"StubProvider 未配置 {key} 的 fixture，可传 fixtures={{'{key}': instance}}",
                )
            parsed = self._fixtures[key]

        if not isinstance(parsed, schema):
            raise ProviderError(
                "parse",
                f"StubProvider fixture 类型错误：期望 {schema.__name__}，实际 {type(parsed).__name__}",
            )

        return LLMResponse(
            text=parsed.model_dump_json(),
            parsed=parsed,
            usage={"prompt_tokens": 800, "completion_tokens": 300, "total_tokens": 1100},
            latency_ms=0,
            model=model,
        )

    async def ping(self) -> bool:
        return self._raise_kind is None
