"""订阅 CRUD —— 仅暴露 SubscriptionManager 已有能力。

- GET    /api/subscriptions               列出全部
- POST   /api/subscriptions                新增（校验 binance/hfd）
- PATCH  /api/subscriptions/{symbol}       激活 / 停用
- DELETE /api/subscriptions/{symbol}       移除（数据保留）
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from backend.collector.subscription_mgr import SubscriptionManager
from backend.models import Subscription

from .cache import TTLCache
from .deps import (
    Depends,
    get_dashboard_cache,
    get_sub_mgr,
    normalize_symbol,
)

router = APIRouter(prefix="/api/subscriptions", tags=["subscriptions"])


class SubscriptionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1, max_length=16)
    active: bool | None = Field(
        default=None,
        description="true/false；None 表示按默认（新增即 active=True）",
    )


class SubscriptionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active: bool | None = None
    display_order: int | None = None   # V1 未实现排序修改，预留占位


@router.get("", response_model=list[Subscription])
async def list_subscriptions(
    sub_mgr: SubscriptionManager = Depends(get_sub_mgr),
) -> list[Subscription]:
    return await sub_mgr.list_all()


@router.post("", response_model=Subscription, status_code=201)
async def create_subscription(
    payload: SubscriptionCreate,
    sub_mgr: SubscriptionManager = Depends(get_sub_mgr),
    cache: TTLCache = Depends(get_dashboard_cache),
) -> Subscription:
    symbol = normalize_symbol(payload.symbol)
    sub = await sub_mgr.add(symbol)
    # 如果 payload.active=False，立刻 deactivate
    if payload.active is False:
        sub = await sub_mgr.deactivate(symbol)
    cache.invalidate()   # 订阅列表变动 → dashboard 可能命中新默认币
    return sub


@router.patch("/{symbol}", response_model=Subscription)
async def update_subscription(
    symbol: str,
    payload: SubscriptionUpdate,
    sub_mgr: SubscriptionManager = Depends(get_sub_mgr),
    cache: TTLCache = Depends(get_dashboard_cache),
) -> Subscription:
    s = normalize_symbol(symbol)
    if payload.active is None and payload.display_order is None:
        raise HTTPException(
            status_code=400, detail="至少提供 active / display_order 之一"
        )
    sub: Subscription | None = None
    if payload.active is not None:
        sub = (
            await sub_mgr.activate(s) if payload.active else await sub_mgr.deactivate(s)
        )
    # V1 暂不做 display_order 修改（repo 无接口），显式 400
    if payload.display_order is not None and sub is None:
        raise HTTPException(
            status_code=501, detail="display_order 修改 V1 未实现"
        )
    cache.invalidate(f"{s}|30m")   # 精细化可删；保险起见按 symbol 清 30m 和 1h
    for tf in ("5m", "15m", "30m", "1h", "2h", "4h", "1d"):
        cache.invalidate(f"{s}|{tf}")
    return sub   # type: ignore[return-value]


@router.delete("/{symbol}", status_code=204)
async def delete_subscription(
    symbol: str,
    sub_mgr: SubscriptionManager = Depends(get_sub_mgr),
    cache: TTLCache = Depends(get_dashboard_cache),
) -> Response:
    s = normalize_symbol(symbol)
    await sub_mgr.remove(s)
    for tf in ("5m", "15m", "30m", "1h", "2h", "4h", "1d"):
        cache.invalidate(f"{s}|{tf}")
    return Response(status_code=204)
