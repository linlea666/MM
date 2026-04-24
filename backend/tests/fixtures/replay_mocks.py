"""E2E 回放用的 fixture Mock Client。

用法::

    from backend.tests.fixtures.replay_mocks import (
        FixtureHFDClient, FixtureExchangeClient, load_snapshot_meta,
    )

    snap_dir = Path("backend/tests/fixtures/upstream/BTC_30m_20260424T160000Z")
    meta = load_snapshot_meta(snap_dir)
    hfd = FixtureHFDClient(snap_dir)
    exchange = FixtureExchangeClient(snap_dir)

设计要点：
- `FixtureHFDClient.fetch` 签名与 ``HFDClient.fetch`` 完全一致，调用时读
  ``<snap_dir>/<indicator>.json`` 原样返回；文件缺失时抛 ``HFDError``。
- `FixtureExchangeClient.fetch_klines` 读 ``klines.json`` 反序列化成 ``Kline``。
- 都不走网络、不计算延迟，适合 pytest 跑。
- 通过 ``spec=HFDClient`` 的 ``AsyncMock`` 方式可以替换，但这里用类实现更贴近真实，
  可以直接放进 ``CollectorEngine(hfd=FixtureHFDClient(...), exchange=...)``。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.core.exceptions import ExchangeError, HFDError
from backend.models import Kline


def load_snapshot_meta(snap_dir: Path) -> dict[str, Any]:
    meta_file = snap_dir / "_meta.json"
    if not meta_file.exists():
        raise FileNotFoundError(
            f"snapshot _meta.json 不存在: {meta_file}. "
            "先跑 `python scripts/capture_hfd_snapshot.py` 生成快照。"
        )
    return json.loads(meta_file.read_text(encoding="utf-8"))


def discover_snapshots(
    root: Path, *, symbol: str | None = None, tf: str | None = None
) -> list[Path]:
    """返回 ``root`` 下所有 snapshot 子目录，可选按 symbol/tf 过滤。按名称降序。"""
    if not root.exists():
        return []
    out: list[Path] = []
    for p in root.iterdir():
        if not p.is_dir():
            continue
        if not (p / "_meta.json").exists():
            continue
        if symbol or tf:
            try:
                meta = load_snapshot_meta(p)
            except FileNotFoundError:
                continue
            if symbol and meta.get("symbol") != symbol.upper():
                continue
            if tf and meta.get("tf") != tf:
                continue
        out.append(p)
    # 目录名里带 ISO 时间戳，lex 降序 == 时间倒序
    out.sort(key=lambda p: p.name, reverse=True)
    return out


class FixtureHFDClient:
    """基于本地 JSON 文件的 HFDClient stub。

    - 只读对应 ``<snap_dir>/<indicator>.json``
    - 不限流、不熔断、不重试、不网络
    """

    def __init__(self, snap_dir: Path) -> None:
        self._dir = snap_dir
        self._cache: dict[str, dict[str, Any]] = {}

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def __aenter__(self) -> "FixtureHFDClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def fetch(
        self, *, symbol: str, indicator: str, tf: str
    ) -> dict[str, Any]:
        key = f"{indicator}"
        if key in self._cache:
            return self._cache[key]
        path = self._dir / f"{indicator}.json"
        if not path.exists():
            raise HFDError(
                f"fixture 缺失: {path.name}",
                detail={"indicator": indicator, "symbol": symbol, "tf": tf},
            )
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise HFDError(
                f"fixture JSON 解析失败: {path.name}: {e}",
                detail={"indicator": indicator},
            ) from e
        if not isinstance(data, dict):
            raise HFDError(
                f"fixture 顶层非 dict: {path.name}",
                detail={"indicator": indicator},
            )
        self._cache[key] = data
        return data

    async def probe(self, *, symbol: str, tf: str = "30m") -> bool:
        return (self._dir / "smart_money_cost.json").exists()


class FixtureExchangeClient:
    """基于本地 JSON 的 ExchangeClient stub。"""

    def __init__(self, snap_dir: Path) -> None:
        self._dir = snap_dir
        self._klines_cache: list[Kline] | None = None

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def __aenter__(self) -> "FixtureExchangeClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    def _load_klines(self, symbol: str, tf: str) -> list[Kline]:
        if self._klines_cache is not None:
            return self._klines_cache
        path = self._dir / "klines.json"
        if not path.exists():
            raise ExchangeError(
                f"fixture klines.json 缺失: {path}",
                detail={"symbol": symbol, "tf": tf},
            )
        raw = json.loads(path.read_text(encoding="utf-8"))
        klines = [
            Kline(
                symbol=symbol,
                tf=tf,
                ts=int(r["ts"]),
                open=float(r["open"]),
                high=float(r["high"]),
                low=float(r["low"]),
                close=float(r["close"]),
                volume=float(r["volume"]),
                source=r.get("source") or "binance",
            )
            for r in raw
        ]
        self._klines_cache = klines
        return klines

    async def fetch_klines(
        self, *, symbol: str, tf: str, limit: int = 500
    ) -> list[Kline]:
        klines = self._load_klines(symbol, tf)
        return klines[-limit:] if limit and limit > 0 else klines

    async def symbol_exists(self, symbol: str) -> bool:
        return True


__all__ = [
    "FixtureExchangeClient",
    "FixtureHFDClient",
    "discover_snapshots",
    "load_snapshot_meta",
]
