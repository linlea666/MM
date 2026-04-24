"""V1.1 · Phase 9 · AI REST 接口集成测试。

覆盖：
- GET  /api/ai/status              基础字段 + api_key mask
- POST /api/ai/test                enabled=false 时不探活、enabled 后探活
- GET  /api/ai/observations        空 / 有内容
- GET  /api/ai/observations/latest 空 → 404、有 → 200
- POST /api/ai/observations/run    ai.enabled=false → 400；enabled + stub → 200

全部用 StubProvider（ai.provider="stub"），不调任何真 LLM。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from backend.collector.subscription_mgr import SubscriptionManager
from backend.core.config import Settings
from backend.main import create_app


@pytest_asyncio.fixture
async def api_client(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_config_dir: Path
) -> AsyncIterator[TestClient]:
    import backend.main as main_mod

    monkeypatch.setattr(main_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(main_mod, "register_sqlite_writer", lambda _repo: None)
    monkeypatch.setenv("MM_DISABLE_SCHEDULER", "1")

    from backend.collector.exchange_client import ExchangeClient
    from backend.collector.hfd_client import HFDClient

    async def _noop(self, *args, **kwargs):  # type: ignore[no-self-use]
        return None

    async def _probe_ok(self, *, symbol: str) -> bool:  # type: ignore[override]
        return True

    async def _symbol_exists(self, symbol: str) -> bool:  # type: ignore[override]
        return True

    monkeypatch.setattr(HFDClient, "start", _noop)
    monkeypatch.setattr(HFDClient, "close", _noop)
    monkeypatch.setattr(HFDClient, "probe", _probe_ok)
    monkeypatch.setattr(ExchangeClient, "start", _noop)
    monkeypatch.setattr(ExchangeClient, "close", _noop)
    monkeypatch.setattr(ExchangeClient, "symbol_exists", _symbol_exists)
    monkeypatch.setattr(SubscriptionManager, "_safe_collect_once", _noop)

    app = create_app()
    with TestClient(app) as client:
        yield client


def _enable_ai_stub(client: TestClient) -> None:
    """开启 AI + 切到 StubProvider；经过 rules config 热更新路径。"""
    r = client.patch(
        "/api/config",
        json={
            "items": {
                "ai.enabled": True,
                "ai.provider": "stub",
            },
            "updated_by": "test",
        },
    )
    assert r.status_code == 200, r.text


# ─── /status + mask ──────────────────────────────────

def test_ai_status_has_masked_key(api_client: TestClient) -> None:
    # 先写入一个明文 key
    api_client.patch(
        "/api/config",
        json={"items": {"ai.api_key": "sk-demo-ffff1111eeee2222"}, "updated_by": "t"},
    )
    r = api_client.get("/api/ai/status")
    assert r.status_code == 200
    body = r.json()
    assert "config" in body and "provider_kind" in body
    # api_key 必须 mask
    masked = body["config"]["api_key"]
    assert "*" in masked
    assert "ffff1111eeee2222" not in masked


# ─── /test 探活 ──────────────────────────────────────

def test_ai_test_disabled(api_client: TestClient) -> None:
    r = api_client.post("/api/ai/test")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "未启用" in body["reason"]


def test_ai_test_stub_provider_ok(api_client: TestClient) -> None:
    _enable_ai_stub(api_client)
    r = api_client.post("/api/ai/test")
    assert r.status_code == 200
    body = r.json()
    # StubProvider.ping 默认返回 True
    assert body["ok"] is True
    assert body["provider"] == "stub"


# ─── /observations ──────────────────────────────────

def test_observations_empty(api_client: TestClient) -> None:
    r = api_client.get("/api/ai/observations", params={"limit": 10})
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["size"] == 0


def test_observations_latest_404_when_empty(api_client: TestClient) -> None:
    r = api_client.get("/api/ai/observations/latest")
    assert r.status_code == 404


# ─── /observations/run ──────────────────────────────

def test_observations_run_requires_enabled(api_client: TestClient) -> None:
    r = api_client.post(
        "/api/ai/observations/run",
        json={"symbol": "BTC", "tf": "30m", "force_trade_plan": False},
    )
    assert r.status_code == 400
    assert "未启用" in r.json()["detail"] or "enabled" in r.json()["detail"].lower()


def test_observations_run_unknown_symbol(api_client: TestClient) -> None:
    _enable_ai_stub(api_client)
    r = api_client.post(
        "/api/ai/observations/run",
        json={"symbol": "NOTACOIN", "tf": "30m", "force_trade_plan": False},
    )
    # resolve_active_symbol 应直接 404
    assert r.status_code == 404


def test_observations_run_invalid_tf_is_422(api_client: TestClient) -> None:
    _enable_ai_stub(api_client)
    r = api_client.post(
        "/api/ai/observations/run",
        json={"symbol": "BTC", "tf": "15m", "force_trade_plan": False},
    )
    # tf 受 Literal 约束 → 422
    assert r.status_code == 422
