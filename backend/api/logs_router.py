"""日志查询 API —— 前端日志面板数据源。

端点::

    GET /api/logs                   分页查询（支持多条件过滤）
    GET /api/logs/summary           近 1h / 24h 级别计数 + top loggers
    GET /api/logs/meta              level / tag / 常见 logger 前缀（给前端下拉）

只读；写入仍由 logging SQLite handler 异步完成。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Query, Request

from backend.core.logging import Tags
from backend.models import LogEntry
from backend.storage.repositories import LogRepository

router = APIRouter(prefix="/api/logs", tags=["logs"])


LOG_LEVELS: list[str] = ["DEBUG", "INFO", "WARNING", "ERROR"]
KNOWN_TAGS: list[str] = sorted({
    getattr(Tags, name) for name in dir(Tags) if not name.startswith("_") and name.isupper()
})
KNOWN_LOGGER_PREFIXES: list[str] = [
    "api",
    "collector",
    "storage",
    "rules",
    "core",
]


def _repo(request: Request) -> LogRepository:
    return request.app.state.log_repo


# ─── 查询 ──────────────────────────────────────────

@router.get("")
async def query_logs(
    request: Request,
    levels: list[Literal["DEBUG", "INFO", "WARNING", "ERROR"]] | None = Query(
        None, description="可选级别过滤；重复传入 ?levels=INFO&levels=ERROR"
    ),
    loggers: list[str] | None = Query(
        None, description="logger 前缀；如 api、collector"
    ),
    keyword: str | None = Query(None, max_length=200),
    symbol: str | None = Query(None, description="从 context.symbol 精确匹配"),
    from_ts: str | None = Query(
        None, description="ISO 时间下限（>=）；例如 2026-04-24T00:00:00"
    ),
    to_ts: str | None = Query(None, description="ISO 时间上限（<=）"),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    items: list[LogEntry] = await _repo(request).query(
        levels=levels,
        loggers_prefix=loggers,
        keyword=keyword,
        symbol=symbol,
        from_ts=from_ts,
        to_ts=to_ts,
        limit=limit,
        offset=offset,
    )
    has_more = len(items) == limit
    return {
        "items": [it.model_dump() for it in items],
        "count": len(items),
        "offset": offset,
        "limit": limit,
        "has_more": has_more,
        "next_offset": offset + len(items) if has_more else None,
    }


# ─── 概览 ──────────────────────────────────────────

@router.get("/summary")
async def logs_summary(request: Request) -> dict[str, Any]:
    """近 1h / 24h 级别计数 + top 10 logger。"""
    repo = _repo(request)
    db = repo._db   # 内部字段；summary 走纯 SQL 更经济
    now = datetime.now(tz=UTC)
    t_1h = (now - timedelta(hours=1)).isoformat()
    t_24h = (now - timedelta(hours=24)).isoformat()

    async def _counts_by_level(since_iso: str) -> dict[str, int]:
        rows = await db.fetchall(
            "SELECT level, COUNT(1) AS c FROM logs WHERE ts >= ? GROUP BY level",
            (since_iso,),
        )
        out = dict.fromkeys(LOG_LEVELS, 0)
        for r in rows:
            out[r["level"]] = int(r["c"])
        return out

    async def _top_loggers(since_iso: str, top: int = 10) -> list[dict[str, Any]]:
        rows = await db.fetchall(
            "SELECT logger, COUNT(1) AS c FROM logs WHERE ts >= ? "
            "GROUP BY logger ORDER BY c DESC LIMIT ?",
            (since_iso, top),
        )
        return [{"logger": r["logger"], "count": int(r["c"])} for r in rows]

    last_1h = await _counts_by_level(t_1h)
    last_24h = await _counts_by_level(t_24h)
    top = await _top_loggers(t_24h)
    total = await repo.count()
    return {
        "total": total,
        "last_1h": last_1h,
        "last_24h": last_24h,
        "top_loggers_24h": top,
    }


# ─── 前端筛选下拉 ─────────────────────────────────

@router.get("/meta")
async def logs_meta(_request: Request) -> dict[str, Any]:
    return {
        "levels": LOG_LEVELS,
        "tags": KNOWN_TAGS,
        "logger_prefixes": KNOWN_LOGGER_PREFIXES,
    }
