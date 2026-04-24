"""WebSocket 路由 —— 薄层，只做协议对接。"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

from backend.storage.repositories import SubscriptionRepository

from .deps import normalize_symbol, normalize_tf
from .ws_brokers import DashboardBroker, LogBroker

logger = logging.getLogger("api.ws")

router = APIRouter()


def _dashboard(request: WebSocket) -> DashboardBroker:
    return request.app.state.ws_dashboard


def _log_broker(request: WebSocket) -> LogBroker:
    return request.app.state.ws_logs


def _sub_repo(request: WebSocket) -> SubscriptionRepository:
    return request.app.state.sub_repo


# ─── /ws/dashboard ────────────────────────────────────────

@router.websocket("/ws/dashboard")
async def ws_dashboard(ws: WebSocket) -> None:
    broker = _dashboard(ws)
    sub_repo = _sub_repo(ws)
    await ws.accept()
    sub = await broker.add(ws)
    await ws.send_json({"type": "hello", "channel": "dashboard"})

    try:
        while True:
            msg = await ws.receive_json()
            action = msg.get("action")

            if action == "subscribe":
                try:
                    tf = normalize_tf(msg.get("tf") or "30m")
                    sym_raw = msg.get("symbol")
                    if sym_raw:
                        symbol = normalize_symbol(sym_raw)
                    else:
                        active = await sub_repo.list_active()
                        if not active:
                            await ws.send_json({
                                "type": "error",
                                "code": "NO_ACTIVE_SUBSCRIPTION",
                            })
                            continue
                        symbol = active[0].symbol
                except Exception as e:   # HTTPException or others
                    await ws.send_json({
                        "type": "error",
                        "code": "BAD_REQUEST",
                        "message": str(e),
                    })
                    continue
                await broker.update_subscription(ws, symbol=symbol, tf=tf)
                await ws.send_json({
                    "type": "subscribed", "symbol": symbol, "tf": tf,
                })

            elif action == "unsubscribe":
                await broker.update_subscription(ws, symbol=None, tf=sub.tf)
                await ws.send_json({"type": "unsubscribed"})

            elif action == "ping":
                await ws.send_json({"type": "pong"})

            else:
                await ws.send_json({
                    "type": "error", "code": "UNKNOWN_ACTION",
                    "action": action,
                })

    except WebSocketDisconnect:
        pass
    except Exception as e:   # noqa: BLE001
        logger.warning(f"ws/dashboard 异常断开: {e}")
    finally:
        await broker.remove(ws)


# ─── /ws/logs ────────────────────────────────────────────

@router.websocket("/ws/logs")
async def ws_logs(ws: WebSocket) -> None:
    broker = _log_broker(ws)
    await ws.accept()
    await broker.add(ws)
    await ws.send_json({"type": "hello", "channel": "logs"})

    try:
        while True:
            msg = await ws.receive_json()
            action = msg.get("action")

            if action == "subscribe":
                levels = msg.get("levels") or []
                loggers = msg.get("loggers") or []
                if not isinstance(levels, list) or not isinstance(loggers, list):
                    await ws.send_json({"type": "error", "code": "BAD_REQUEST"})
                    continue
                await broker.update_filter(ws, levels=levels, loggers=loggers)
                await ws.send_json({
                    "type": "subscribed", "levels": levels, "loggers": loggers,
                })

            elif action == "ping":
                await ws.send_json({"type": "pong"})

            else:
                await ws.send_json({
                    "type": "error", "code": "UNKNOWN_ACTION",
                    "action": action,
                })

    except WebSocketDisconnect:
        pass
    except Exception as e:   # noqa: BLE001
        logger.warning(f"ws/logs 异常断开: {e}")
    finally:
        await broker.remove(ws)
