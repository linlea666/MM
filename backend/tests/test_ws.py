"""Step 4.2 WebSocket 集成测试。

- /ws/dashboard: 握手 → subscribe → 拿到 snapshot/error → ping/pong → 断开
- /ws/logs: 握手 → subscribe 过滤 → 触发日志 → 收到广播 → ping/pong

TestClient 对 WebSocket 是同步 API，不能 await；所以测试里用同步风格。
为保证实时性，DashboardBroker 的 interval 设 0.2 秒（通过 monkeypatch）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.collector.subscription_mgr import SubscriptionManager
from backend.core.config import Settings
from backend.main import create_app


@pytest.fixture
def ws_client(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_config_dir: Path
) -> Iterator[TestClient]:
    import backend.main as main_mod

    monkeypatch.setattr(main_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(main_mod, "register_sqlite_writer", lambda _repo: None)
    monkeypatch.setenv("MM_DISABLE_SCHEDULER", "1")

    from backend.collector.exchange_client import ExchangeClient
    from backend.collector.hfd_client import HFDClient

    async def _noop(self, *args, **kwargs):  # type: ignore[no-self-use]
        return None

    async def _probe_ok(self, *, symbol: str) -> bool:   # type: ignore[override]
        return True

    async def _symbol_exists(self, symbol: str) -> bool:   # type: ignore[override]
        return True

    monkeypatch.setattr(HFDClient, "start", _noop)
    monkeypatch.setattr(HFDClient, "close", _noop)
    monkeypatch.setattr(HFDClient, "probe", _probe_ok)
    monkeypatch.setattr(ExchangeClient, "start", _noop)
    monkeypatch.setattr(ExchangeClient, "close", _noop)
    monkeypatch.setattr(ExchangeClient, "symbol_exists", _symbol_exists)
    monkeypatch.setattr(SubscriptionManager, "_safe_collect_once", _noop)

    # Dashboard tick interval 调小方便测试
    from backend.api import ws_brokers

    orig_init = ws_brokers.DashboardBroker.__init__

    def _fast_init(self, runner, *, interval=5.0):  # type: ignore[no-redef]
        orig_init(self, runner, interval=0.2)

    monkeypatch.setattr(ws_brokers.DashboardBroker, "__init__", _fast_init)

    app = create_app()
    with TestClient(app) as client:
        yield client


# ─── /ws/dashboard ─────────────────────────────────────


def test_ws_dashboard_hello_and_ping(ws_client: TestClient) -> None:
    with ws_client.websocket_connect("/ws/dashboard") as ws:
        hello = ws.receive_json()
        assert hello == {"type": "hello", "channel": "dashboard"}

        ws.send_json({"action": "ping"})
        pong = ws.receive_json()
        assert pong == {"type": "pong"}


def test_ws_dashboard_subscribe_no_data(ws_client: TestClient) -> None:
    """空库 subscribe BTC/30m，tick 触发 NO_DATA 错误消息。"""
    with ws_client.websocket_connect("/ws/dashboard") as ws:
        ws.receive_json()   # hello
        ws.send_json({"action": "subscribe", "symbol": "btc", "tf": "30m"})
        confirm = ws.receive_json()
        assert confirm["type"] == "subscribed"
        assert confirm["symbol"] == "BTC"   # 规范化
        assert confirm["tf"] == "30m"

        # 等待至少一次 tick（interval=0.2s）
        err = ws.receive_json()
        assert err["type"] == "error"
        assert err["code"] == "NO_DATA"
        assert err["symbol"] == "BTC"


def test_ws_dashboard_subscribe_bad_tf(ws_client: TestClient) -> None:
    with ws_client.websocket_connect("/ws/dashboard") as ws:
        ws.receive_json()
        ws.send_json({"action": "subscribe", "symbol": "BTC", "tf": "7m"})
        err = ws.receive_json()
        assert err["type"] == "error"
        assert err["code"] == "BAD_REQUEST"


def test_ws_dashboard_unknown_action(ws_client: TestClient) -> None:
    with ws_client.websocket_connect("/ws/dashboard") as ws:
        ws.receive_json()
        ws.send_json({"action": "foo"})
        err = ws.receive_json()
        assert err["code"] == "UNKNOWN_ACTION"


def test_ws_dashboard_auto_pick_active_symbol(ws_client: TestClient) -> None:
    """subscribe 不传 symbol → 取第一个 active 订阅（默认有 BTC）。"""
    with ws_client.websocket_connect("/ws/dashboard") as ws:
        ws.receive_json()
        ws.send_json({"action": "subscribe"})
        confirm = ws.receive_json()
        assert confirm["type"] == "subscribed"
        assert confirm["symbol"] == "BTC"


def test_ws_dashboard_unknown_symbol_rejected(ws_client: TestClient) -> None:
    """V1.1 · 币种单一真源：非 active 订阅 symbol 应被 WS 拒绝（NO_ACTIVE_SUBSCRIPTION）。"""
    with ws_client.websocket_connect("/ws/dashboard") as ws:
        ws.receive_json()
        ws.send_json({"action": "subscribe", "symbol": "ETH", "tf": "30m"})
        err = ws.receive_json()
        assert err["type"] == "error"
        assert err["code"] == "NO_ACTIVE_SUBSCRIPTION"
        # message 给前端可读提示
        assert "ETH" in err.get("message", "")


def test_ws_dashboard_deprecated_tf_rejected(ws_client: TestClient) -> None:
    """V1.1 · 周期单一真源：5m/15m/2h/1d 等老 tf 在 WS 侧也被拒绝。"""
    for bad_tf in ("5m", "15m", "2h", "1d"):
        with ws_client.websocket_connect("/ws/dashboard") as ws:
            ws.receive_json()
            ws.send_json({"action": "subscribe", "symbol": "BTC", "tf": bad_tf})
            err = ws.receive_json()
            assert err["type"] == "error"
            assert err["code"] == "BAD_REQUEST"
            assert bad_tf in err.get("message", "") or "白名单" in err.get(
                "message", ""
            )


# ─── /ws/logs ──────────────────────────────────────────


def test_ws_logs_hello_and_filter(ws_client: TestClient) -> None:
    with ws_client.websocket_connect("/ws/logs") as ws:
        hello = ws.receive_json()
        assert hello == {"type": "hello", "channel": "logs"}

        ws.send_json({
            "action": "subscribe",
            "levels": ["ERROR"],
            "loggers": ["api.test_ws"],
        })
        confirm = ws.receive_json()
        assert confirm["type"] == "subscribed"
        assert confirm["levels"] == ["ERROR"]

        # 触发一条 ERROR 日志；应被广播
        log = logging.getLogger("api.test_ws.logtarget")
        log.error("hello from test", extra={"context": {"symbol": "BTC"}})

        # 等广播扇出（后台 consumer 任务）
        msg = ws.receive_json()
        assert msg["type"] == "log"
        assert msg["data"]["level"] == "ERROR"
        assert msg["data"]["message"] == "hello from test"
        assert msg["data"]["logger"].startswith("api.test_ws")

        # INFO 不应被推送
        log.info("info msg")
        ws.send_json({"action": "ping"})
        pong = ws.receive_json()
        assert pong == {"type": "pong"}


def test_ws_logs_no_filter_gets_everything(ws_client: TestClient) -> None:
    with ws_client.websocket_connect("/ws/logs") as ws:
        ws.receive_json()
        ws.send_json({"action": "subscribe"})
        ws.receive_json()   # subscribed

        log = logging.getLogger("api.test_ws.any")
        log.warning("warn msg")

        msg = ws.receive_json()
        assert msg["type"] == "log"
        assert msg["data"]["level"] == "WARNING"
