"""GET /api/system/health —— 全局系统健康信息。

聚合 scheduler / circuit breaker / 订阅列表 / 启动耗时，给前端顶栏用。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from backend.collector.circuit_breaker import CircuitBreaker
from backend.collector.scheduler import CollectorScheduler
from backend.core.time_utils import now_ms
from backend.storage.repositories import SubscriptionRepository

router = APIRouter(prefix="/api/system", tags=["system"])


class SystemHealth(BaseModel):
    status: str
    ts: int
    uptime_seconds: int
    app_name: str
    app_version: str
    env: str
    active_symbols: list[str]
    inactive_symbols: list[str]
    scheduler_running: bool
    scheduler_jobs: int
    circuits: list[dict[str, Any]]


@router.get("/health", response_model=SystemHealth)
async def system_health(request: Request) -> SystemHealth:
    state = request.app.state
    sub_repo: SubscriptionRepository = state.sub_repo
    scheduler: CollectorScheduler | None = getattr(state, "scheduler", None)
    breaker: CircuitBreaker | None = getattr(state, "breaker", None)

    all_subs = await sub_repo.list_all()
    active = [s.symbol for s in all_subs if s.active]
    inactive = [s.symbol for s in all_subs if not s.active]

    return SystemHealth(
        status="ok",
        ts=now_ms(),
        uptime_seconds=(now_ms() - state.start_ms) // 1000,
        app_name=state.settings.app.name,
        app_version=state.settings.app.version,
        env=state.settings.app.env,
        active_symbols=active,
        inactive_symbols=inactive,
        scheduler_running=bool(scheduler and scheduler.running),
        scheduler_jobs=len(scheduler.list_jobs()) if scheduler else 0,
        circuits=breaker.snapshot() if breaker else [],
    )
