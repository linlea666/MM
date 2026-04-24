"""V1.1 · Phase 9 · AI 观察 REST 接口。

路由总览::

    GET  /api/ai/status                运行时状态（provider / 配置概要，secret 已 mask）
    POST /api/ai/test                  探活（调用 provider.ping）
    GET  /api/ai/observations          列出最近 N 条 feed
    GET  /api/ai/observations/latest   最新一条 feed item + summary
    POST /api/ai/observations/run      强制触发一次观察（body: symbol, tf, force_trade_plan）

所有响应里的 api_key 均以 mask 形态暴露；审计日志记录 provider/trigger 但不记录模型原文。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from backend.ai.observer import build_summary
from backend.ai.service import AIObservationService
from backend.api.deps import get_sub_repo, resolve_active_symbol
from backend.core.exceptions import NoDataError
from backend.core.logging import Tags
from backend.core.timeframes import DEFAULT_TF, SupportedTf
from backend.rules import RuleRunner
from backend.storage.repositories import SubscriptionRepository

logger = logging.getLogger("api.ai")

router = APIRouter(prefix="/api/ai", tags=["ai"])


# ─── 依赖 ────────────────────────────────────────────────

def _ai_service(request: Request) -> AIObservationService:
    svc: AIObservationService | None = getattr(request.app.state, "ai_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="AI 服务未初始化")
    return svc


def _runner(request: Request) -> RuleRunner:
    return request.app.state.rule_runner


# ─── 请求模型 ────────────────────────────────────────────

class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str | None = Field(default=None, max_length=16)
    tf: SupportedTf = Field(default=DEFAULT_TF)  # type: ignore[valid-type]
    force_trade_plan: bool = Field(
        default=False,
        description="强制跑 Layer 3 交易计划（用 ai.model_tier 指定的同一模型）",
    )


# ─── 端点 ────────────────────────────────────────────────

@router.get("/status")
async def get_ai_status(
    svc: AIObservationService = Depends(_ai_service),
) -> dict[str, Any]:
    """返回当前 AI 配置（api_key 已 mask）+ 运行统计。"""
    store = svc.store
    latest = await store.latest()
    return {
        "config": svc.config.to_audit_dict(),
        "provider_kind": svc.provider.name,
        "history_size": store.size(),
        "has_latest": latest is not None,
        "latest_ts": latest.ts if latest is not None else None,
        "latest_anchor_ts": latest.anchor_ts if latest is not None else None,
    }


@router.post("/test")
async def test_ai_connection(
    svc: AIObservationService = Depends(_ai_service),
) -> dict[str, Any]:
    """探活：调 provider.ping；不消耗 observer 额度。"""
    cfg = svc.config
    if not cfg.enabled:
        return {
            "ok": False,
            "reason": "AI 未启用（ai.enabled=false）",
            "provider": svc.provider.name,
        }
    ok = False
    err: str | None = None
    try:
        ok = await svc.provider.ping()
    except Exception as e:  # noqa: BLE001
        err = str(e)
    logger.info(
        f"/api/ai/test ok={ok} provider={svc.provider.name}",
        extra={"tags": [Tags.API, "AI"], "context": cfg.to_audit_dict()},
    )
    # V1.1 · 暴露当前生效的 tier / thinking，便于前端「诊断抽屉」直观展示
    effective_model = cfg.pro_model if cfg.model_tier == "pro" else cfg.flash_model
    return {
        "ok": ok,
        "provider": svc.provider.name,
        "model_tier": cfg.model_tier,
        "effective_model": effective_model,
        "thinking_enabled": cfg.thinking_enabled,
        "flash_model": cfg.flash_model,
        "pro_model": cfg.pro_model,
        "base_url": cfg.base_url,
        "error": err,
    }


@router.get("/observations")
async def list_observations(
    svc: AIObservationService = Depends(_ai_service),
    limit: int = Query(default=20, ge=1, le=200),
) -> dict[str, Any]:
    """最近 N 条完整 feed item（含 trend/money_flow/trade_plan 明细）。"""
    items = await svc.store.list(limit=limit)
    return {
        "items": [it.model_dump() for it in items],
        "size": svc.store.size(),
        "limit": limit,
    }


@router.get("/observations/latest")
async def get_latest_observation(
    svc: AIObservationService = Depends(_ai_service),
) -> dict[str, Any]:
    """拿最新一条 item + summary。若无则 404，方便前端决定是否渲染。"""
    item = await svc.store.latest()
    if item is None:
        raise HTTPException(status_code=404, detail="暂无 AI 观察记录")
    return {
        "item": item.model_dump(),
        "summary": build_summary(item).model_dump(),
    }


@router.post("/observations/run")
async def run_observation(
    payload: RunRequest,
    request: Request,
    svc: AIObservationService = Depends(_ai_service),
    sub_repo: SubscriptionRepository = Depends(get_sub_repo),
) -> dict[str, Any]:
    """用户手动触发一次观察。

    - 绕过节流（``force=True``），但仍受 ``ai.enabled`` 限制；
    - ``force_trade_plan=True`` 时强制跑 Layer 3（使用 ``ai.model_tier`` 指定的模型）；
    - 同步等待结果：
        * flash 非 thinking：~10–20 s
        * flash + thinking 或 pro：~30–60 s
        * pro + thinking：60–120 s（thinking 最慢）。
    """
    if not svc.config.enabled:
        raise HTTPException(status_code=400, detail="AI 未启用（ai.enabled=false）")

    symbol = await resolve_active_symbol(payload.symbol, sub_repo)
    runner = _runner(request)

    try:
        snap = await runner._ext.extract(symbol, payload.tf)
    except NoDataError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    if snap is None:
        raise HTTPException(
            status_code=404, detail=f"{symbol}/{payload.tf} 无可用 FeatureSnapshot"
        )

    try:
        item = await svc.observer.run(
            snap,
            trigger="manual",
            force_trade_plan=payload.force_trade_plan,
            force=True,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception(f"/api/ai/observations/run 失败: {e}")
        raise HTTPException(status_code=500, detail=f"AI 观察失败: {e}") from e

    logger.info(
        f"/api/ai/observations/run ok symbol={symbol} tf={payload.tf} "
        f"force_trade_plan={payload.force_trade_plan}",
        extra={
            "tags": [Tags.API, "AI"],
            "context": {
                "symbol": symbol,
                "tf": payload.tf,
                "trigger": item.trigger,
                "errors": item.errors,
            },
        },
    )
    return {
        "item": item.model_dump(),
        "summary": build_summary(item).model_dump(),
    }
