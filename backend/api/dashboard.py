"""GET /api/dashboard —— 规则引擎驱动的大屏快照。

- symbol 可省略：取订阅表中第一个 active
- 结果走 2 秒 TTL 缓存，同一 (symbol, tf) 并发只算一次
- 无数据 → 404（NoDataError 经 MMError handler 自动翻译）
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query, Response

from backend.collector.subscription_mgr import SubscriptionManager
from backend.core.logging import Tags
from backend.core.timeframes import DEFAULT_TF, SupportedTf
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
    resolve_active_symbol,
)

logger = logging.getLogger("api.dashboard")

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard", response_model=DashboardSnapshot)
async def get_dashboard(
    response: Response,
    symbol: str | None = Query(
        None, description="币种代码（必须在激活订阅列表中；不传则取第一个 active 订阅）"
    ),
    tf: SupportedTf = Query(
        DEFAULT_TF, description="周期：30m / 1h / 4h（V1.1 · 单一真源）"
    ),
    runner: RuleRunner = Depends(get_rule_runner),
    cache: TTLCache = Depends(get_dashboard_cache),
    sub_repo: SubscriptionRepository = Depends(get_sub_repo),
    _sub_mgr: SubscriptionManager = Depends(get_sub_mgr),   # 未来扩展预留
) -> DashboardSnapshot:
    resolved_symbol = await resolve_active_symbol(symbol, sub_repo)
    # FastAPI 已按 Literal 做 422 校验，这里 tf 天然是 SupportedTf，无需二次 normalize
    resolved_tf: str = tf
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
