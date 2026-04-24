"""FastAPI 依赖：从 ``app.state`` 取全局组件 + symbol 规范化。"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from backend.collector.subscription_mgr import SubscriptionManager
from backend.core.config import Settings
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
    """tf 白名单。"""
    tf = tf.strip().lower()
    allowed = {"5m", "15m", "30m", "1h", "2h", "4h", "1d"}
    if tf not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"tf 不在白名单 {sorted(allowed)}: {tf}",
        )
    return tf


__all__ = [
    "Depends",
    "get_dashboard_cache",
    "get_rule_runner",
    "get_settings",
    "get_sub_mgr",
    "get_sub_repo",
    "normalize_symbol",
    "normalize_tf",
]
