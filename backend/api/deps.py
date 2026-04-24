"""FastAPI 依赖：从 ``app.state`` 取全局组件 + symbol 规范化。"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from backend.collector.subscription_mgr import SubscriptionManager
from backend.core.config import Settings
from backend.core.timeframes import SUPPORTED_TFS
from backend.rules import RuleRunner
from backend.storage.repositories import SubscriptionRepository

from .cache import TTLCache


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_sub_mgr(request: Request) -> SubscriptionManager:
    return request.app.state.sub_mgr


def get_sub_repo(request: Request) -> SubscriptionRepository:
    return request.app.state.sub_repo


def get_rule_runner(request: Request) -> RuleRunner:
    return request.app.state.rule_runner


def get_dashboard_cache(request: Request) -> TTLCache:
    return request.app.state.dashboard_cache


# ─── symbol / tf 规范化 ──────────────────────────────


def normalize_symbol(symbol: str) -> str:
    """统一大写、去空白；仅接受字母数字（与 SubscriptionManager 校验一致）。"""
    s = symbol.strip().upper()
    if not s.isalnum() or len(s) > 16:
        raise HTTPException(status_code=400, detail=f"symbol 格式非法: {symbol}")
    return s


def normalize_tf(tf: str) -> str:
    """tf 白名单（V1.1 · 周期单一真源，仅 30m/1h/4h）。

    历史版本允许 5m/15m/2h/1d，但 ``collector.timeframes`` 只采这三档；
    收紧白名单可把"前端能发、后端空跑"的静默错误前置成 400。
    """
    tf = tf.strip().lower()
    if tf not in SUPPORTED_TFS:
        raise HTTPException(
            status_code=400,
            detail=f"tf 不在白名单 {list(SUPPORTED_TFS)}: {tf}",
        )
    return tf


async def resolve_active_symbol(
    symbol: str | None,
    sub_repo: SubscriptionRepository,
) -> str:
    """V1.1 · 币种单一真源：解析 symbol → 必须在"激活订阅表"里。

    规则：
    - 全局无任何 active 订阅 → **404** ``NO_ACTIVE_SUBSCRIPTION``
      （提示前端去 /subscriptions 先订阅）。
    - symbol 省略 → 取 active 列表第 1 条（按 display_order asc）。
    - symbol 传入 → 先走 ``normalize_symbol`` 做格式校验，再检查是否 active；
      否则 **404**（而不是静默空数据或 500）。

    这是 dashboard REST 与 WebSocket 共用的单一真源校验，避免两条入口
    各自实现一份会漂移。
    """
    active = await sub_repo.list_active()
    if not active:
        raise HTTPException(
            status_code=404,
            detail="NO_ACTIVE_SUBSCRIPTION：当前没有激活的订阅，请先 POST /api/subscriptions",
        )
    active_symbols = {s.symbol for s in active}
    if symbol is None:
        return active[0].symbol
    s = normalize_symbol(symbol)
    if s not in active_symbols:
        raise HTTPException(
            status_code=404,
            detail=(
                f"NO_ACTIVE_SUBSCRIPTION：symbol '{s}' 未在激活订阅中，"
                f"当前允许：{sorted(active_symbols)}"
            ),
        )
    return s


__all__ = [
    "Depends",
    "get_dashboard_cache",
    "get_rule_runner",
    "get_settings",
    "get_sub_mgr",
    "get_sub_repo",
    "normalize_symbol",
    "normalize_tf",
    "resolve_active_symbol",
]
