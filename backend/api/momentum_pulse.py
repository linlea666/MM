"""V1.1 · Step 7 · 多 TF 动能能量柱 + 目标投影 REST。

设计：前端「Multi-TF 三色灯带」需要在不切主大屏 tf 的情况下、一次拿到多个 tf 的
``momentum_pulse`` + ``target_projection``。

- 走 ``FeatureExtractor.extract`` 而不是完整 ``RuleRunner.run``：
  避免每个 tf 都跑一遍 6 个 module + 4 个 capability 的开销，把多 tf 总延迟控制在 < 80ms（30m + 1h + 4h）。
- 多 tf 并发拉（``asyncio.gather``），SQLite 单连接也能受益（IO 不抢 GIL）。
- 缓存：复用 dashboard_cache 的 TTL（2s），key 形如 `mp|{symbol}|{tf}`。

不做的事：
- ❌ 不复用 /api/dashboard 的整张快照（体积太大、信息冗余）。
- ❌ 不在这里渲染卡片（直接返回 view，前端按 view 重新渲染）。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.deps import (
    get_dashboard_cache,
    get_rule_runner,
    get_sub_repo,
    resolve_active_symbol,
)
from backend.core.logging import Tags
from backend.core.timeframes import SUPPORTED_TFS, SupportedTf
from backend.rules import RuleRunner
from backend.storage.repositories import SubscriptionRepository

from .cache import TTLCache

logger = logging.getLogger("api.momentum_pulse")

router = APIRouter(prefix="/api", tags=["momentum_pulse"])


def _parse_tfs(raw: str | None) -> list[SupportedTf]:
    """将 "30m,1h,4h" 解析为白名单内的 tf 列表，去重保序。

    None / 空字符串 → 默认全量 ``SUPPORTED_TFS``。
    任何越界或非法 tf → 422，提示用户用白名单。
    """
    if not raw:
        return list(SUPPORTED_TFS)
    out: list[SupportedTf] = []
    seen: set[str] = set()
    for part in raw.split(","):
        tf = part.strip().lower()
        if not tf:
            continue
        if tf in seen:
            continue
        if tf not in SUPPORTED_TFS:
            raise HTTPException(
                status_code=422,
                detail=f"tf 不在白名单 {list(SUPPORTED_TFS)}: {tf}",
            )
        seen.add(tf)
        out.append(tf)  # type: ignore[arg-type]
    if not out:
        return list(SUPPORTED_TFS)
    return out


async def _fetch_one(
    runner: RuleRunner,
    cache: TTLCache,
    symbol: str,
    tf: str,
) -> dict[str, Any]:
    """单个 tf 的 view 拉取，2s TTL。"""
    cache_key = f"mp|{symbol}|{tf}"

    async def _run() -> dict[str, Any]:
        snap = await runner._ext.extract(symbol, tf)
        if snap is None:
            return {
                "tf": tf,
                "anchor_ts": None,
                "current_price": None,
                "momentum_pulse": None,
                "target_projection": None,
                "stale_tables": [],
                "available": False,
            }
        return {
            "tf": tf,
            "anchor_ts": snap.anchor_ts,
            "current_price": snap.last_price,
            "momentum_pulse": (
                snap.momentum_pulse.model_dump()
                if snap.momentum_pulse is not None else None
            ),
            "target_projection": (
                snap.target_projection.model_dump()
                if snap.target_projection is not None else None
            ),
            "stale_tables": list(snap.stale_tables),
            "available": True,
        }

    value, _from_cache = await cache.get_or_compute(cache_key, _run)
    return value


@router.get("/momentum_pulse")
async def get_momentum_pulse_multi(
    symbol: str | None = Query(
        None, description="币种代码（不传则取首个 active 订阅）"
    ),
    tfs: str | None = Query(
        None,
        description=(
            "逗号分隔 tf 列表（白名单 30m/1h/4h），不传默认全量。"
            "示例：tfs=30m,1h"
        ),
    ),
    runner: RuleRunner = Depends(get_rule_runner),
    cache: TTLCache = Depends(get_dashboard_cache),
    sub_repo: SubscriptionRepository = Depends(get_sub_repo),
) -> dict[str, Any]:
    """多 tf 并发返回 ``momentum_pulse`` + ``target_projection`` 视图。"""
    resolved_symbol = await resolve_active_symbol(symbol, sub_repo)
    tf_list = _parse_tfs(tfs)

    t0 = time.perf_counter()
    results = await asyncio.gather(
        *(_fetch_one(runner, cache, resolved_symbol, tf) for tf in tf_list),
        return_exceptions=True,
    )
    items: list[dict[str, Any]] = []
    for tf, r in zip(tf_list, results):
        if isinstance(r, Exception):
            logger.warning(
                f"momentum_pulse extract failed {resolved_symbol}/{tf}: {r}",
                extra={"tags": [Tags.DASHBOARD, Tags.API],
                       "context": {"symbol": resolved_symbol, "tf": tf}},
            )
            items.append({
                "tf": tf,
                "anchor_ts": None,
                "current_price": None,
                "momentum_pulse": None,
                "target_projection": None,
                "stale_tables": [],
                "available": False,
                "error": str(r),
            })
        else:
            items.append(r)
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    logger.debug(
        "momentum_pulse multi-tf done",
        extra={
            "tags": [Tags.DASHBOARD, Tags.API],
            "context": {
                "symbol": resolved_symbol,
                "tfs": tf_list,
                "elapsed_ms": elapsed_ms,
            },
        },
    )
    return {
        "symbol": resolved_symbol,
        "items": items,
    }


__all__ = ["router"]
