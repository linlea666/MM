"""DeepSeek Provider（openai 兼容 /v1/chat/completions）。

DeepSeek v4 API 接口：https://platform.deepseek.com/api-docs
- base_url 默认 ``https://api.deepseek.com``
- 模型：deepseek-v4-flash（Layer 1/2 默认）/ deepseek-v4-pro（Layer 3 升级）
- 支持 response_format={"type":"json_object"}，但仍需在 prompt 里强约束 schema

设计取舍：
- 单次调用 ``timeout_s=20s``，不重试（由 observer 层决定降级策略）；
- api_key 通过构造参数传入，provider 本身不读 env / 不读 yaml（避免横向耦合）；
- http client 懒创建 + 复用；observer.close() 时调用 aclose()。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from backend.ai.providers.base import LLMProvider, LLMResponse, ProviderError, T

logger = logging.getLogger("ai.provider.deepseek")


class DeepSeekProvider(LLMProvider):
    name = "deepseek"
    DEFAULT_BASE_URL = "https://api.deepseek.com"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None = None,
        flash_model: str = "deepseek-v4-flash",
        pro_model: str = "deepseek-v4-pro",
        proxy: str | None = None,
    ) -> None:
        if not api_key:
            raise ProviderError("auth", "deepseek api_key 为空，无法初始化")
        self._api_key = api_key
        self._base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self.models = {"flash": flash_model, "pro": pro_model}
        self._proxy = proxy
        self._client: httpx.AsyncClient | None = None

    # ── 内部 httpx client 懒创建 ─────────────────────────────

    def _client_lazy(self) -> httpx.AsyncClient:
        """懒创建并复用 httpx client。

        **注意**：client 级的 timeout 只在第一次创建时生效，若复用会"锁死"
        那次的 timeout。因此本 provider 不在 client 级设 timeout，改为
        每次 ``client.post(..., timeout=...)`` 传参，让 flash/pro 各自用
        自己的 ``timeout_s`` —— 否则 pro 请求会错误地继承 flash 的 20s。
        """
        if self._client is not None and not self._client.is_closed:
            return self._client
        kwargs: dict[str, Any] = {
            "base_url": self._base_url,
            # 设一个宽松兜底（不会生效到请求上，因为请求层会 override）
            "timeout": httpx.Timeout(60.0, connect=5.0),
            "headers": {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        }
        if self._proxy:
            kwargs["proxy"] = self._proxy
        self._client = httpx.AsyncClient(**kwargs)
        return self._client

    # ── 公共 API ────────────────────────────────────────────

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
        client = self._client_lazy()
        # DeepSeek V4 官方规则："thinking 与 response_format=json_object 不可组合"。
        # - thinking 关（默认）：启用 json_object + temperature，输出稳定可直接 parse。
        # - thinking 开：去掉 json_object 与 temperature，靠 prompt "只输出 JSON"
        #   强约束 + _parse_strict_json 的大括号兜底完成解析；同时 max_tokens 放大，
        #   因为 thinking 会先产出大段推理占用 token 预算。
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        if thinking_enabled:
            payload["thinking"] = {"type": "enabled"}
            # thinking 模式下 reasoning_content 本身就会吃掉几百上千 token；
            # 再加上 narrative + evidences[] 的输出 token，最低也要 4096 起。
            # 实测 L2 MoneyFlowReader 给 2048 时，reasoning 占满 content 字段空白。
            payload["max_tokens"] = max(max_tokens, 4096)
        else:
            payload["thinking"] = {"type": "disabled"}
            payload["response_format"] = {"type": "json_object"}
            payload["temperature"] = temperature
            payload["max_tokens"] = max_tokens
        started = time.perf_counter()
        try:
            # per-request timeout：必须在这里传，client 级 timeout 是兜底，
            # 一次创建就锁死，不能靠它区分 flash/pro。
            resp = await client.post(
                "/v1/chat/completions",
                json=payload,
                timeout=httpx.Timeout(timeout_s, connect=5.0),
            )
        except httpx.TimeoutException as e:
            raise ProviderError("timeout", f"deepseek 请求超时: {e}") from e
        except httpx.HTTPError as e:
            raise ProviderError("network", f"deepseek 网络错误: {e}") from e

        latency_ms = int((time.perf_counter() - started) * 1000)

        if resp.status_code == 401:
            raise ProviderError("auth", "deepseek 鉴权失败（api_key 无效）", status=401)
        if resp.status_code == 402 or resp.status_code == 429:
            raise ProviderError(
                "quota",
                f"deepseek 额度 / 频率限制（HTTP {resp.status_code}）",
                status=resp.status_code,
                raw=resp.text[:500],
            )
        if resp.status_code >= 400:
            raise ProviderError(
                "network",
                f"deepseek HTTP {resp.status_code}",
                status=resp.status_code,
                raw=resp.text[:500],
            )

        try:
            data = resp.json()
            choice = data["choices"][0]
            msg = choice["message"]
            finish_reason = choice.get("finish_reason", "")
            text = msg.get("content") or ""
            # DeepSeek V4 thinking 模式：推理段在 reasoning_content，最终答案在 content。
            # 实测：
            #   - 非 thinking（json_object）：content 一定是 JSON；
            #   - thinking=enabled：content 通常是 JSON（末尾），但偶尔模型
            #     把 JSON 留在 reasoning_content 里。
            # 兜底：content 为空 / 不含 "{" 时，回退到 reasoning_content。
            if not text or "{" not in text:
                rc = msg.get("reasoning_content") or ""
                if rc and "{" in rc:
                    logger.info(
                        "deepseek thinking mode: fallback to reasoning_content for JSON",
                        extra={"tags": ["AI"]},
                    )
                    text = rc
            usage = data.get("usage") or {}
        except (KeyError, IndexError, ValueError) as e:
            raise ProviderError(
                "parse", f"deepseek 响应结构异常: {e}", raw=resp.text[:1500]
            ) from e

        if not text:
            # 典型场景：thinking=true + max_tokens 被 reasoning 全吃光 → content 空
            hint = ""
            if thinking_enabled and finish_reason == "length":
                hint = "（疑似 max_tokens 被 reasoning 吃光；已内部放大到 4096，若仍失败请考虑关 thinking）"
            raise ProviderError(
                "parse",
                f"deepseek 响应 content 与 reasoning_content 均为空 finish={finish_reason}{hint}",
                raw=resp.text[:1500],
            )

        try:
            parsed = _parse_strict_json(text, schema)
        except ProviderError as pe:
            # 解析失败时把原始 content 带上，便于排查（thinking 模式尤其常见）
            logger.warning(
                f"deepseek JSON parse failed (thinking={thinking_enabled}, model={model}): "
                f"first 800 chars of text={text[:800]!r}",
                extra={"tags": ["AI"]},
            )
            raise pe

        return LLMResponse(
            text=text,
            parsed=parsed,
            usage={
                "prompt_tokens": int(usage.get("prompt_tokens", 0)),
                "completion_tokens": int(usage.get("completion_tokens", 0)),
                "total_tokens": int(usage.get("total_tokens", 0)),
            },
            latency_ms=latency_ms,
            model=model,
        )

    async def ping(self) -> bool:
        """发送一次极小调用（flash + 1 token）验证鉴权与连通。"""
        try:
            client = self._client_lazy()
            resp = await client.post(
                "/v1/chat/completions",
                json={
                    "model": self.models["flash"],
                    "messages": [
                        {"role": "system", "content": "reply 'ok' in json: {\"ok\":true}"},
                        {"role": "user", "content": "ping"},
                    ],
                    "temperature": 0.0,
                    "max_tokens": 8,
                    "response_format": {"type": "json_object"},
                    "thinking": {"type": "disabled"},
                },
                timeout=httpx.Timeout(10.0, connect=5.0),
            )
            return resp.status_code == 200
        except Exception as e:
            logger.warning(f"deepseek ping failed: {e}", extra={"tags": ["AI"]})
            return False

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None


def _parse_strict_json(text: str, schema: type[T]) -> T:
    """严格按 schema 解析，允许 LLM 前后包裹 ``\`\`\`json`` 等噪声。

    兜底策略：
    1. 直接 json.loads；
    2. 截取最外层大括号；
    3. Pydantic 验证。
    """
    raw = text.strip()
    if raw.startswith("```"):
        # 剥 code fence
        lines = raw.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines).strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            raise ProviderError("parse", "LLM 输出不含 JSON 对象", raw=text[:500])
        try:
            data = json.loads(raw[start : end + 1])
        except json.JSONDecodeError as e:
            raise ProviderError("parse", f"JSON 解析失败: {e}", raw=text[:500]) from e

    if not isinstance(data, dict):
        raise ProviderError("parse", "LLM 顶层不是 object", raw=text[:500])

    try:
        return schema.model_validate(data)
    except ValidationError as e:
        raise ProviderError(
            "parse", f"schema 验证失败: {e.error_count()} errors", raw=text[:500]
        ) from e
