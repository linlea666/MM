"""FastAPI 应用入口。

Step 2 新增：启动 HFD / Exchange / Scheduler / Engine / SubscriptionManager，
让后台采集任务跑起来；Step 4 会在此基础上挂载 REST / WS 路由。
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.ai import AIObservationService
from backend.api import (
    ai_router,
    config_router,
    dashboard_router,
    indicators_router,
    logs_router,
    momentum_pulse_router,
    subscriptions_router,
    system_router,
    ws_router,
)
from backend.api.cache import TTLCache
from backend.api.ws_brokers import DashboardBroker, LogBroker
from backend.collector.circuit_breaker import CircuitBreaker
from backend.collector.engine import CollectorEngine
from backend.collector.exchange_client import ExchangeClient
from backend.collector.hfd_client import HFDClient
from backend.collector.rate_limiter import TokenBucket
from backend.collector.scheduler import CollectorScheduler
from backend.collector.subscription_mgr import SubscriptionManager
from backend.core.config import get_settings
from backend.core.exceptions import MMError
from backend.core.logging import (
    Tags,
    set_ws_broadcaster,
    set_ws_main_loop,
    setup_logging,
    shutdown_logging,
)
from backend.core.rules_config import ConfigChangeEvent, RulesConfigService
from backend.core.time_utils import now_ms
from backend.rules import RuleRunner
from backend.storage.db import init_database, shutdown_database
from backend.storage.repositories import (
    AtomRepositories,
    ConfigRepository,
    KlineRepository,
    LogRepository,
    SubscriptionRepository,
)
from backend.storage.repositories.log import register_sqlite_writer

logger = logging.getLogger("api.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings)
    logger.info(
        "MM 启动",
        extra={
            "tags": [Tags.LIFECYCLE],
            "context": {"version": settings.app.version, "env": settings.app.env},
        },
    )

    db = await init_database(settings)
    log_repo = LogRepository(settings)
    await log_repo.initialize()
    register_sqlite_writer(log_repo)

    sub_repo = SubscriptionRepository(db)
    kline_repo = KlineRepository(db)
    atoms = AtomRepositories(db)
    config_repo = ConfigRepository(db)

    # 规则配置服务：合并 default + override，支持热更新
    rules_config_svc = RulesConfigService(settings=settings, repo=config_repo)
    await rules_config_svc.load()

    # 规则引擎 + 大屏 TTL 缓存
    rule_runner = RuleRunner(db, config=rules_config_svc.snapshot())
    dashboard_cache: TTLCache = TTLCache(ttl_seconds=2.0)

    # V1.1 · Phase 9 · AI 观察服务（enabled=false 时用 StubProvider，不会真调 LLM）
    data_dir = settings.config_dir.parent  # backend/ 目录
    ai_service = AIObservationService(
        data_dir=data_dir,
        rules_snapshot=rules_config_svc.snapshot(),
        fallback_api_key=settings.ai.api_key,
        fallback_base_url=settings.ai.base_url,
    )
    await ai_service.startup()
    rule_runner.set_ai_observer(ai_service.observer)

    # WebSocket brokers
    ws_dashboard = DashboardBroker(rule_runner, interval=5.0)
    ws_logs = LogBroker()

    async def _on_rules_change(ev: ConfigChangeEvent) -> None:
        snap = rules_config_svc.snapshot()
        rule_runner._config = snap
        rule_runner._ext._config = snap
        dashboard_cache.invalidate()
        # AI 服务热更新（provider 配置 / 阈值变动）
        try:
            await ai_service.reload(
                rules_snapshot=snap,
                fallback_api_key=settings.ai.api_key,
                fallback_base_url=settings.ai.base_url,
            )
            rule_runner.set_ai_observer(ai_service.observer)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                f"AI 服务热更新失败：{e}", extra={"tags": [Tags.CONFIG, "AI"]}
            )
        # V1.1 · 批量提交时一条日志即可（去抖后的效果）
        if ev.kind == "set_batch":
            logger.info(
                f"规则配置批量变更 keys={ev.batch_keys} → RuleRunner 已热更新 + 快照缓存已清空",
                extra={"tags": [Tags.CONFIG, Tags.RULES]},
            )
        else:
            logger.info(
                f"规则配置变更 key={ev.key} kind={ev.kind} → RuleRunner 已热更新 + 快照缓存已清空",
                extra={"tags": [Tags.CONFIG, Tags.RULES]},
            )

    rules_config_svc.subscribe(_on_rules_change)

    # 采集层组件
    limiter = TokenBucket(rps=settings.collector.global_rps)
    breaker = CircuitBreaker(threshold=3, cooldown_seconds=60.0)
    hfd = HFDClient(settings, breaker=breaker, limiter=limiter)
    exchange = ExchangeClient(
        primary=settings.collector.kline_sources.primary,
        fallback=settings.collector.kline_sources.fallback,
        timeout=settings.collector.request_timeout_seconds,
    )
    await hfd.start()
    await exchange.start()

    engine = CollectorEngine(
        settings=settings,
        hfd=hfd,
        exchange=exchange,
        kline_repo=kline_repo,
        atoms=atoms,
    )
    scheduler = CollectorScheduler(settings=settings, engine=engine)
    sub_mgr = SubscriptionManager(
        repo=sub_repo,
        hfd=hfd,
        exchange=exchange,
        scheduler=scheduler,
        engine=engine,
    )

    # 注入 WS 广播器 + 主事件循环（logging 线程投递用）
    set_ws_broadcaster(ws_logs.broadcast)
    set_ws_main_loop(asyncio.get_running_loop())

    ws_dashboard.start()
    ws_logs.start()

    enable_scheduler = os.environ.get("MM_DISABLE_SCHEDULER", "0") not in ("1", "true", "True")
    if enable_scheduler:
        scheduler.start()
        await sub_mgr.startup(settings.collector.default_symbols)
    else:
        # 测试环境：不启 scheduler，仅保证 DB & 默认订阅
        await sub_repo.ensure_defaults(settings.collector.default_symbols)
        logger.info(
            "已禁用 scheduler（MM_DISABLE_SCHEDULER）",
            extra={"tags": [Tags.LIFECYCLE]},
        )

    # 注入到 app.state
    app.state.settings = settings
    app.state.db = db
    app.state.log_repo = log_repo
    app.state.sub_repo = sub_repo
    app.state.kline_repo = kline_repo
    app.state.atoms = atoms
    app.state.hfd = hfd
    app.state.exchange = exchange
    app.state.engine = engine
    app.state.scheduler = scheduler
    app.state.sub_mgr = sub_mgr
    app.state.breaker = breaker
    app.state.config_repo = config_repo
    app.state.rules_config_svc = rules_config_svc
    app.state.rule_runner = rule_runner
    app.state.dashboard_cache = dashboard_cache
    app.state.ws_dashboard = ws_dashboard
    app.state.ws_logs = ws_logs
    app.state.ai_service = ai_service
    app.state.start_ms = now_ms()

    try:
        yield
    finally:
        logger.info("MM 关闭", extra={"tags": [Tags.LIFECYCLE]})
        set_ws_broadcaster(None)
        set_ws_main_loop(None)
        try:
            await ws_dashboard.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            await ws_logs.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            scheduler.shutdown(wait=False)
        except Exception:  # noqa: BLE001
            pass
        try:
            await ai_service.aclose()
        except Exception:  # noqa: BLE001
            pass
        try:
            await hfd.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            await exchange.close()
        except Exception:  # noqa: BLE001
            pass
        await log_repo.close()
        await shutdown_database()
        shutdown_logging()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="MM Backend",
        version=settings.app.version,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.server.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(MMError)
    async def mm_error_handler(_request, exc: MMError):
        return JSONResponse(status_code=exc.http_status, content=exc.to_dict())

    app.include_router(dashboard_router)
    app.include_router(subscriptions_router)
    app.include_router(system_router)
    app.include_router(config_router)
    app.include_router(logs_router)
    app.include_router(ai_router)
    app.include_router(indicators_router)
    app.include_router(momentum_pulse_router)
    app.include_router(ws_router)

    @app.get("/")
    async def root() -> dict[str, Any]:
        return {
            "name": settings.app.name,
            "version": settings.app.version,
            "env": settings.app.env,
        }

    @app.get("/health")
    async def health() -> dict[str, Any]:
        sub_repo: SubscriptionRepository = app.state.sub_repo
        active = await sub_repo.list_active()
        scheduler: CollectorScheduler = getattr(app.state, "scheduler", None)
        breaker: CircuitBreaker | None = getattr(app.state, "breaker", None)
        return {
            "status": "ok",
            "ts": now_ms(),
            "uptime_seconds": (now_ms() - app.state.start_ms) // 1000,
            "active_symbols": [s.symbol for s in active],
            "scheduler_running": bool(scheduler and scheduler.running),
            "scheduler_jobs": len(scheduler.list_jobs()) if scheduler else 0,
            "circuits": breaker.snapshot() if breaker else [],
        }

    return app


app = create_app()
