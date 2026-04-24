"""HFD API 客户端。

- 全局令牌桶限流（RPS 由 config.collector.global_rps 控制）
- 指数退避 + 熔断（连续 3 次失败触发告警）
- 所有请求有完整日志（context: symbol/indicator/tf/status）
- 返回 dict，解析交给 parser
"""

from __future__ import annotations

from typing import Any

import httpx

from backend.core.config import Settings
from backend.core.exceptions import HFDError
from backend.core.logging import Tags, get_logger

from .circuit_breaker import CircuitBreaker
from .rate_limiter import TokenBucket

logger = get_logger("collector.hfd_client")

# HFD 所有有效 indicator 名
HFD_INDICATORS: tuple[str, ...] = (
    "smart_money_cost",
    "liq_heatmap",
    "absolute_zones",
    "fvg",
    "cross_exchange_resonance",
    "fair_value",
    "inst_volume_profile",
    "trend_price",
    "ob_decay",
    "micro_poc",
    "trend_purity",
    "poc_shift",
    "trailing_vwap",
    "trend_saturation",
    "liq_vacuum",
    "imbalance",
    "power_imbalance",
    "trend_exhaustion",
    "liquidation_fuel",
    "hvn_nodes",
    "liquidity_sweep",
    "time_heatmap",
)


class HFDClient:
    """异步 HFD 客户端。由调用方保证 session 生命周期。"""

    def __init__(
        self,
        settings: Settings,
        *,
        breaker: CircuitBreaker | None = None,
        limiter: TokenBucket | None = None,
        max_retries: int = 3,
        base_backoff: float = 1.0,
    ) -> None:
        self._base_url = settings.collector.hfd_base_url
        self._timeout = settings.collector.request_timeout_seconds
        self._limiter = limiter or TokenBucket(rps=settings.collector.global_rps)
        self._breaker = breaker or CircuitBreaker()
        self._max_retries = max_retries
        self._base_backoff = base_backoff
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "HFDClient":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def start(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout),
                headers={"User-Agent": "MM-Collector/0.1"},
            )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def breaker(self) -> CircuitBreaker:
        return self._breaker

    async def fetch(
        self,
        *,
        symbol: str,
        indicator: str,
        tf: str,
    ) -> dict[str, Any]:
        """拉取一个 endpoint。失败时抛 HFDError。"""
        if indicator not in HFD_INDICATORS:
            raise HFDError(f"未知 indicator: {indicator}")
        if self._client is None:
            await self.start()

        key = f"{indicator}:{symbol}:{tf}"
        if self._breaker.is_open("hfd", key):
            raise HFDError(
                f"HFD 熔断中 {key}",
                detail={"symbol": symbol, "indicator": indicator, "tf": tf},
            )

        params = {"coin": symbol, "indicator": indicator, "tf": tf}
        last_exc: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            import asyncio
            import time

            async with self._limiter:
                t0 = time.monotonic()
                try:
                    assert self._client is not None
                    resp = await self._client.get(self._base_url, params=params)
                    elapsed_ms = int((time.monotonic() - t0) * 1000)
                    if resp.status_code != 200:
                        raise HFDError(
                            f"HFD {resp.status_code}",
                            detail={"status": resp.status_code, "url": str(resp.url)},
                        )
                    try:
                        data = resp.json()
                    except Exception as e:
                        raise HFDError(f"HFD 响应 JSON 解析失败: {e}") from e
                    if not isinstance(data, dict):
                        raise HFDError(
                            f"HFD 响应类型异常: {type(data).__name__}",
                            detail={"url": str(resp.url)},
                        )
                    self._breaker.record_success("hfd", key)
                    tags = [Tags.HFD]
                    if elapsed_ms > 3000:
                        tags.append(Tags.SLOW)
                    logger.info(
                        f"HFD OK {indicator} {symbol} {tf} ({elapsed_ms}ms)",
                        extra={
                            "tags": tags,
                            "context": {
                                "symbol": symbol,
                                "indicator": indicator,
                                "tf": tf,
                                "elapsed_ms": elapsed_ms,
                                "attempt": attempt,
                            },
                        },
                    )
                    return data
                except HFDError as e:
                    last_exc = e
                except httpx.HTTPError as e:
                    last_exc = HFDError(f"HFD 网络错误: {e}", detail={"error": str(e)})
                except Exception as e:  # pragma: no cover
                    last_exc = HFDError(f"HFD 未知错误: {e}", detail={"error": str(e)})

            if attempt < self._max_retries:
                wait = self._base_backoff * (2 ** (attempt - 1))
                logger.warning(
                    f"HFD 重试 {indicator} {symbol} {tf} 第 {attempt}/{self._max_retries} 次失败，{wait:.1f}s 后重试",
                    extra={
                        "tags": [Tags.HFD, Tags.FETCH_FAIL],
                        "context": {
                            "symbol": symbol,
                            "indicator": indicator,
                            "tf": tf,
                            "attempt": attempt,
                            "error": str(last_exc),
                        },
                    },
                )
                await asyncio.sleep(wait)

        self._breaker.record_failure(
            "hfd", key, reason=str(last_exc) if last_exc else "unknown"
        )
        logger.error(
            f"HFD 拉取失败 {indicator} {symbol} {tf}",
            extra={
                "tags": [Tags.HFD, Tags.FETCH_FAIL, Tags.URGENT],
                "context": {
                    "symbol": symbol,
                    "indicator": indicator,
                    "tf": tf,
                    "error": str(last_exc),
                },
            },
        )
        assert last_exc is not None
        raise last_exc

    async def probe(self, *, symbol: str, tf: str = "30m") -> bool:
        """试探性调用 smart_money_cost 判断 HFD 是否支持该 symbol。超时 5s 视为不支持。"""
        try:
            async with self._limiter:
                assert self._client is not None or await self.start() or True
                assert self._client is not None
                resp = await self._client.get(
                    self._base_url,
                    params={"coin": symbol, "indicator": "smart_money_cost", "tf": tf},
                    timeout=httpx.Timeout(5.0),
                )
                if resp.status_code != 200:
                    return False
                data = resp.json()
                return isinstance(data, dict)
        except Exception:
            return False
