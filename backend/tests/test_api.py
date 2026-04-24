"""Step 4.1 REST API 集成测试。

覆盖：
- /api/subscriptions CRUD（增删改查 + 边界）
- /api/dashboard 流程（默认 symbol / TTL 缓存 / 无数据 404）
- /api/system/health 字段

走 FastAPI TestClient，复用 conftest 的 settings/db 临时目录；
为了不依赖网络，通过 ``skip_validation`` monkeypatch 掉 Exchange + HFD 校验。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from backend.api.cache import TTLCache
from backend.collector.subscription_mgr import SubscriptionManager
from backend.core.config import Settings
from backend.main import create_app
from backend.storage.db import Database


@pytest_asyncio.fixture
async def api_client(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_config_dir: Path
) -> AsyncIterator[TestClient]:
    """构造集成 TestClient，禁 scheduler、跳过 HFD/Exchange 真实连接。"""

    # main.create_app() 内部会调 get_settings()；用 monkeypatch 替换成 fixture 版本
    import backend.main as main_mod

    monkeypatch.setattr(main_mod, "get_settings", lambda: settings)
    # 禁 sqlite 日志 writer（避免与 aiosqlite 抢锁）
    monkeypatch.setattr(main_mod, "register_sqlite_writer", lambda _repo: None)
    # 禁 scheduler（避免后台任务）
    monkeypatch.setenv("MM_DISABLE_SCHEDULER", "1")

    # HFDClient / ExchangeClient 的 start/close/probe 走真网络会失败；打桩
    from backend.collector.exchange_client import ExchangeClient
    from backend.collector.hfd_client import HFDClient

    async def _noop_start(self):  # type: ignore[no-self-use, no-redef]
        return None

    async def _noop_close(self):  # type: ignore[no-self-use, no-redef]
        return None

    async def _probe_ok(self, *, symbol: str) -> bool:   # type: ignore[override]
        return True

    async def _symbol_exists(self, symbol: str) -> bool:   # type: ignore[override]
        return symbol.upper() in {"BTC", "ETH", "SOL", "DOGE"}

    monkeypatch.setattr(HFDClient, "start", _noop_start)
    monkeypatch.setattr(HFDClient, "close", _noop_close)
    monkeypatch.setattr(HFDClient, "probe", _probe_ok)
    monkeypatch.setattr(ExchangeClient, "start", _noop_start)
    monkeypatch.setattr(ExchangeClient, "close", _noop_close)
    monkeypatch.setattr(ExchangeClient, "symbol_exists", _symbol_exists)

    # 避免 _safe_collect_once 真正下网：SubscriptionManager.add 会 create_task
    async def _noop_collect(self, symbol: str) -> None:   # type: ignore[override]
        return None

    monkeypatch.setattr(SubscriptionManager, "_safe_collect_once", _noop_collect)

    app = create_app()

    with TestClient(app) as client:
        yield client


# ─── /api/subscriptions ──────────────────────────────────


def test_list_subscriptions_default(api_client: TestClient) -> None:
    r = api_client.get("/api/subscriptions")
    assert r.status_code == 200
    data = r.json()
    symbols = {item["symbol"] for item in data}
    assert "BTC" in symbols   # 来自默认订阅


def test_create_and_delete_subscription(api_client: TestClient) -> None:
    r = api_client.post("/api/subscriptions", json={"symbol": "sol"})   # 小写
    assert r.status_code == 201
    body = r.json()
    assert body["symbol"] == "SOL"   # 规范化成大写
    assert body["active"] is True

    # 重复创建 → 409
    r2 = api_client.post("/api/subscriptions", json={"symbol": "SOL"})
    assert r2.status_code == 409

    # 非法 symbol → 400
    r3 = api_client.post("/api/subscriptions", json={"symbol": "BTC-USDT"})
    assert r3.status_code == 400

    # 删除
    r4 = api_client.delete("/api/subscriptions/sol")
    assert r4.status_code == 204

    # 再删 → 404
    r5 = api_client.delete("/api/subscriptions/SOL")
    assert r5.status_code == 404


def test_patch_subscription_toggle_active(api_client: TestClient) -> None:
    api_client.post("/api/subscriptions", json={"symbol": "eth"})
    r = api_client.patch("/api/subscriptions/ETH", json={"active": False})
    assert r.status_code == 200
    assert r.json()["active"] is False

    r2 = api_client.patch("/api/subscriptions/ETH", json={"active": True})
    assert r2.status_code == 200
    assert r2.json()["active"] is True

    # 空 body → 400
    r3 = api_client.patch("/api/subscriptions/ETH", json={})
    assert r3.status_code == 400

    # 未知币 → 404
    r4 = api_client.patch("/api/subscriptions/XXX", json={"active": False})
    assert r4.status_code == 404


# ─── /api/dashboard ──────────────────────────────────────


def test_dashboard_no_data_is_404(api_client: TestClient) -> None:
    # 空 DB 下调 BTC/30m，FeatureExtractor 返回 None → NoDataError → 404
    r = api_client.get("/api/dashboard", params={"symbol": "BTC", "tf": "30m"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NO_DATA"


def test_dashboard_invalid_tf_is_422(api_client: TestClient) -> None:
    """V1.1 · 周期单一真源：非 30m/1h/4h 的 tf 被 FastAPI Literal 拦为 422。"""
    r = api_client.get("/api/dashboard", params={"tf": "7m"})
    assert r.status_code == 422
    # 错误信息里应能辨认出是 tf 字段问题
    assert "tf" in r.text.lower()


@pytest.mark.parametrize("bad_tf", ["5m", "15m", "2h", "1d", "", "TF"])
def test_dashboard_rejects_deprecated_tfs(
    api_client: TestClient, bad_tf: str
) -> None:
    """V1.1：历史遗留的 5m/15m/2h/1d 一律 422，防止前端静默空跑。"""
    r = api_client.get("/api/dashboard", params={"tf": bad_tf})
    assert r.status_code == 422


def test_dashboard_no_subscription_is_404(api_client: TestClient) -> None:
    # 删光订阅（先确认 BTC 可以删）
    api_client.delete("/api/subscriptions/BTC")
    r = api_client.get("/api/dashboard", params={"tf": "30m"})
    # 没有 active 订阅 → 404
    assert r.status_code == 404


def test_dashboard_unknown_symbol_is_404(api_client: TestClient) -> None:
    """V1.1 · 币种单一真源：传入的 symbol 不在 active 订阅中应返 404，
    提示用户去订阅，而不是静默 500 / 空跑。"""
    # 默认订阅里只有 BTC，请求 ETH（格式合法但未订阅）
    r = api_client.get("/api/dashboard", params={"symbol": "ETH", "tf": "30m"})
    assert r.status_code == 404
    detail = r.json()["error"]["message"] if "error" in r.json() else r.text
    assert "NO_ACTIVE_SUBSCRIPTION" in detail or "未在激活订阅" in detail


def test_dashboard_default_tf_is_30m(api_client: TestClient) -> None:
    """V1.1：未传 tf 时默认走 30m（DEFAULT_TF），即参数解析不应 422。"""
    r = api_client.get("/api/dashboard", params={"symbol": "BTC"})
    # 空 DB 下必然 NO_DATA 404；重点是确认 **不是** 422（证明 Literal 默认值生效）
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NO_DATA"


# ─── /api/system/health ─────────────────────────────────


def test_system_health_fields(api_client: TestClient) -> None:
    r = api_client.get("/api/system/health")
    assert r.status_code == 200
    body = r.json()
    for field in (
        "status",
        "ts",
        "uptime_seconds",
        "app_name",
        "app_version",
        "env",
        "active_symbols",
        "inactive_symbols",
        "scheduler_running",
        "scheduler_jobs",
        "circuits",
    ):
        assert field in body
    assert body["status"] == "ok"


# ─── TTLCache 单测 ──────────────────────────────────────


def test_ttl_cache_hits_and_expires() -> None:
    cache: TTLCache[int] = TTLCache(ttl_seconds=0.1)
    calls: list[int] = []

    async def factory() -> int:
        calls.append(1)
        return 42

    async def run() -> None:
        v1, hit1 = await cache.get_or_compute("k", factory)
        v2, hit2 = await cache.get_or_compute("k", factory)
        assert (v1, hit1) == (42, False)
        assert (v2, hit2) == (42, True)

        await asyncio.sleep(0.15)
        v3, hit3 = await cache.get_or_compute("k", factory)
        assert (v3, hit3) == (42, False)
        assert len(calls) == 2

        cache.invalidate("k")
        assert cache.peek("k") is None

    asyncio.run(run())


def test_ttl_cache_concurrent_single_flight() -> None:
    cache: TTLCache[int] = TTLCache(ttl_seconds=10.0)
    counter = {"n": 0}

    async def slow() -> int:
        counter["n"] += 1
        await asyncio.sleep(0.05)
        return counter["n"]

    async def run() -> None:
        results = await asyncio.gather(
            cache.get_or_compute("shared", slow),
            cache.get_or_compute("shared", slow),
            cache.get_or_compute("shared", slow),
        )
        # 期望 factory 只跑 1 次
        assert counter["n"] == 1
        assert all(r[0] == 1 for r in results)
        # 首次 False，后续 True
        assert sorted(r[1] for r in results) == [False, True, True]

    asyncio.run(run())
