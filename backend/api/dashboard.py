"""GET /api/dashboard —— 规则引擎驱动的大屏快照。

- symbol 可省略：取订阅表中第一个 active
- 结果走 2 秒 TTL 缓存，同一 (symbol, tf) 并发只算一次
- 无数据 → 404（NoDataError 经 MMError handler 自动翻译）
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, Response

from backend.collector.subscription_mgr import SubscriptionManager
from backend.core.logging import Tags
from backend.models import DashboardSnapshot
from backend.rules import RuleRunner
from backend.storage.repositories import SubscriptionRepository

from .cache import TTLCache
from .deps import (
    Depends,
    get_dashboard_cache,
    get_rule_runner,
    get_sub_mgr,
    get_sub_repo,
    normalize_symbol,
    normalize_tf,
)

logger = logging.getLogger("api.dashboard")

router = APIRouter(prefix="/api", tags=["dashboard"])


async def _resolve_symbol(
    symbol: str | None,
    sub_repo: SubscriptionRepository,
) -> str:
    if symbol is not None:
        return normalize_symbol(symbol)
    active = await sub_repo.list_active()
    if not active:
        raise HTTPException(
            status_code=404,
            detail="当前没有激活的订阅，请先 POST /api/subscriptions 添加",
        )
    return active[0].symbol   # repo 按 display_order asc 返回


@router.get("/dashboard", response_model=DashboardSnapshot)
async def get_dashboard(
    response: Response,
    symbol: str | None = Query(None, description="币种代码（不传则取第一个 active 订阅）"),
    tf: str = Query("30m", description="周期：5m / 15m / 30m / 1h / 2h / 4h / 1d"),
    runner: RuleRunner = Depends(get_rule_runner),
    cache: TTLCache = Depends(get_dashboard_cache),
    sub_repo: SubscriptionRepository = Depends(get_sub_repo),
    _sub_mgr: SubscriptionManager = Depends(get_sub_mgr),   # 未来扩展预留
) -> DashboardSnapshot:
    resolved_symbol = await _resolve_symbol(symbol, sub_repo)
    resolved_tf = normalize_tf(tf)
    cache_key = f"{resolved_symbol}|{resolved_tf}"

    async def _run() -> DashboardSnapshot:
        return await runner.run(resolved_symbol, resolved_tf)

    snap, from_cache = await cache.get_or_compute(cache_key, _run)
    response.headers["X-MM-Cache"] = "HIT" if from_cache else "MISS"
    response.headers["X-MM-Symbol"] = resolved_symbol
    response.headers["X-MM-TF"] = resolved_tf

    if not from_cache:
        logger.debug(
            "dashboard snapshot generated",
            extra={
                "tags": [Tags.DASHBOARD, Tags.API],
                "context": {
                    "symbol": resolved_symbol, "tf": resolved_tf,
                    "plans": len(snap.plans),
                    "events": len(snap.recent_events),
                },
            },
        )
    return snap
