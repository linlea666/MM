"""交易所 K 线客户端（Binance 主 / OKX 备）。

用途：
- 为 ``atoms_klines`` 提供权威 K 线（HFD 响应中的 klines 丢弃）
- 支持 failover：Binance 超时/403 → 自动切 OKX
- 支持 symbol 存在性校验（Binance exchangeInfo）
"""

from __future__ import annotations

from typing import Any

import httpx

from backend.core.exceptions import ExchangeError
from backend.core.logging import Tags, get_logger
from backend.models import Kline

logger = get_logger("collector.exchange")

# Binance 与 OKX 的 interval 命名映射
_BINANCE_TF: dict[str, str] = {
    "1m": "1m", "5m": "5m", "15m": "15m",
    "30m": "30m", "1h": "1h", "2h": "2h",
    "4h": "4h", "12h": "12h", "1d": "1d",
}
_OKX_TF: dict[str, str] = {
    "1m": "1m", "5m": "5m", "15m": "15m",
    "30m": "30m", "1h": "1H", "2h": "2H",
    "4h": "4H", "12h": "12H", "1d": "1D",
}


class ExchangeClient:
    """按 ``sources`` 顺序试探的 K 线客户端。"""

    def __init__(
        self,
        *,
        primary: str = "binance",
        fallback: list[str] | None = None,
        timeout: float = 15.0,
    ) -> None:
        self._primary = primary
        self._fallback = list(fallback or ["okx"])
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._symbol_cache: dict[str, bool] = {}  # Binance exchangeInfo 缓存

    async def __aenter__(self) -> "ExchangeClient":
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

    def _sources(self) -> list[str]:
        return [self._primary, *self._fallback]

    # ─── K 线拉取 ───

    async def fetch_klines(
        self,
        *,
        symbol: str,
        tf: str,
        limit: int = 500,
    ) -> list[Kline]:
        """按 primary → fallback 顺序试。返回标准化 Kline。"""
        assert self._client is not None or await self.start() or True
        last_exc: Exception | None = None
        for src in self._sources():
            try:
                if src == "binance":
                    data = await self._binance_klines(symbol, tf, limit)
                elif src == "okx":
                    data = await self._okx_klines(symbol, tf, limit)
                else:
                    continue
                klines = [
                    Kline(
                        symbol=symbol, tf=tf, ts=row[0],
                        open=row[1], high=row[2], low=row[3], close=row[4],
                        volume=row[5], source=src,  # type: ignore[arg-type]
                    )
                    for row in data
                ]
                if src != self._primary:
                    logger.warning(
                        f"K 线切备用源 {src}: {symbol} {tf}",
                        extra={
                            "tags": [Tags.FAILOVER],
                            "context": {"symbol": symbol, "tf": tf, "source": src},
                        },
                    )
                return klines
            except Exception as e:
                last_exc = e
                logger.warning(
                    f"K 线源 {src} 失败: {symbol} {tf} ({e})",
                    extra={
                        "tags": [Tags.FETCH_FAIL],
                        "context": {
                            "symbol": symbol,
                            "tf": tf,
                            "source": src,
                            "error": str(e),
                        },
                    },
                )
        raise ExchangeError(
            f"所有 K 线源失败: {symbol} {tf}",
            detail={"error": str(last_exc)},
        )

    async def _binance_klines(
        self, symbol: str, tf: str, limit: int
    ) -> list[list[float]]:
        if tf not in _BINANCE_TF:
            raise ExchangeError(f"binance 不支持 tf={tf}")
        pair = f"{symbol.upper()}USDT"
        assert self._client is not None
        resp = await self._client.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": pair, "interval": _BINANCE_TF[tf], "limit": limit},
        )
        if resp.status_code != 200:
            raise ExchangeError(
                f"binance {resp.status_code}",
                detail={"body": resp.text[:200]},
            )
        data: list[list[Any]] = resp.json()
        # Binance 返回 12 列，取 openTime/o/h/l/c/v
        return [
            [
                int(row[0]),
                float(row[1]), float(row[2]), float(row[3]),
                float(row[4]), float(row[5]),
            ]
            for row in data
        ]

    async def _okx_klines(
        self, symbol: str, tf: str, limit: int
    ) -> list[list[float]]:
        if tf not in _OKX_TF:
            raise ExchangeError(f"okx 不支持 tf={tf}")
        inst = f"{symbol.upper()}-USDT"
        assert self._client is not None
        resp = await self._client.get(
            "https://www.okx.com/api/v5/market/candles",
            params={"instId": inst, "bar": _OKX_TF[tf], "limit": str(min(limit, 300))},
        )
        if resp.status_code != 200:
            raise ExchangeError(f"okx {resp.status_code}")
        body = resp.json()
        if body.get("code") != "0":
            raise ExchangeError(f"okx code={body.get('code')}", detail=body)
        raw: list[list[str]] = body.get("data", [])
        # OKX 返回：[ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm] 倒序
        rows = [
            [
                int(r[0]),
                float(r[1]), float(r[2]), float(r[3]),
                float(r[4]), float(r[5]),
            ]
            for r in raw
        ]
        rows.sort(key=lambda r: r[0])
        return rows

    # ─── 符号存在性校验（用于 subscription add）───

    async def symbol_exists(self, symbol: str) -> bool:
        """用 Binance exchangeInfo 判断。带内存缓存。"""
        key = symbol.upper()
        if key in self._symbol_cache:
            return self._symbol_cache[key]
        assert self._client is not None or await self.start() or True
        pair = f"{key}USDT"
        try:
            assert self._client is not None
            resp = await self._client.get(
                "https://api.binance.com/api/v3/exchangeInfo",
                params={"symbol": pair},
                timeout=httpx.Timeout(5.0),
            )
            if resp.status_code == 200:
                body = resp.json()
                found = any(s.get("symbol") == pair for s in body.get("symbols", []))
                self._symbol_cache[key] = found
                return found
            # 400 = 不存在
            if resp.status_code == 400:
                self._symbol_cache[key] = False
                return False
        except Exception as e:  # noqa: BLE001
            logger.warning(
                f"binance exchangeInfo 查询失败: {e}",
                extra={
                    "tags": [Tags.FETCH_FAIL],
                    "context": {"symbol": symbol, "error": str(e)},
                },
            )
        # 尝试 OKX 兜底
        try:
            assert self._client is not None
            resp = await self._client.get(
                "https://www.okx.com/api/v5/public/instruments",
                params={"instType": "SPOT", "instId": f"{key}-USDT"},
                timeout=httpx.Timeout(5.0),
            )
            body = resp.json()
            ok = body.get("code") == "0" and body.get("data")
            self._symbol_cache[key] = bool(ok)
            return bool(ok)
        except Exception:
            self._symbol_cache[key] = False
            return False
