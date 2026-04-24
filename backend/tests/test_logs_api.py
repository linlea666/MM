"""Step 4.3 日志查询 API 集成测试。

通过 LogRepository.write_payload（同步）插测试数据，
然后用 REST 查询验证各过滤/分页/聚合逻辑。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
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


async def _seed_logs(client: TestClient) -> None:
    """向日志库插 6 条测试记录，覆盖多 level / logger / context。"""
    log_repo = client.app.state.log_repo
    now = datetime.now(tz=UTC)

    rows = [
        # recent (now) - 最新
        (now.isoformat(), "ERROR", "collector.hfd", "HFD 限流", ["HFD", "CIRCUIT"], {"symbol": "BTC"}),
        ((now - timedelta(minutes=30)).isoformat(), "WARNING", "api.dashboard", "慢请求", [], {"symbol": "BTC"}),
        ((now - timedelta(minutes=45)).isoformat(), "INFO", "api.dashboard", "dashboard 生成", ["API", "DASHBOARD"], {"symbol": "ETH"}),
        ((now - timedelta(hours=2)).isoformat(), "INFO", "collector.engine", "采集完成", ["TICK"], {"symbol": "BTC"}),
        ((now - timedelta(hours=5)).isoformat(), "DEBUG", "rules.runner", "snapshot ready", ["RULES"], {"symbol": "BTC"}),
        ((now - timedelta(hours=26)).isoformat(), "INFO", "core.config", "启动 —— 超过 24h 窗口", ["LIFECYCLE"], {}),
    ]

    for ts, level, logger_name, msg, tags, ctx in rows:
        log_repo.write_payload(
            {
                "ts": ts,
                "level": level,
                "logger": logger_name,
                "message": msg,
                "tags": tags,
                "context": ctx,
            }
        )


# ─── query ─────────────────────────────────────────────

def test_query_empty_db(api_client: TestClient) -> None:
    r = api_client.get("/api/logs", params={"limit": 50})
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["count"] == 0
    assert body["has_more"] is False
    assert body["next_offset"] is None


def test_query_filters_levels_and_loggers(api_client: TestClient) -> None:
    import asyncio

    asyncio.run(_seed_logs(api_client))

    r = api_client.get(
        "/api/logs",
        params=[("levels", "ERROR"), ("levels", "WARNING"), ("limit", "50")],
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 2
    assert all(it["level"] in ("ERROR", "WARNING") for it in items)

    r2 = api_client.get("/api/logs", params=[("loggers", "collector"), ("limit", "50")])
    items2 = r2.json()["items"]
    assert all(it["logger"].startswith("collector") for it in items2)
    assert len(items2) == 2


def test_query_symbol_and_keyword(api_client: TestClient) -> None:
    import asyncio

    asyncio.run(_seed_logs(api_client))

    r = api_client.get("/api/logs", params={"symbol": "ETH", "limit": 50})
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["context"]["symbol"] == "ETH"

    r2 = api_client.get("/api/logs", params={"keyword": "限流", "limit": 50})
    items2 = r2.json()["items"]
    assert len(items2) == 1
    assert "限流" in items2[0]["message"]


def test_query_pagination(api_client: TestClient) -> None:
    import asyncio

    asyncio.run(_seed_logs(api_client))

    page1 = api_client.get("/api/logs", params={"limit": 2, "offset": 0}).json()
    assert page1["count"] == 2
    assert page1["has_more"] is True
    assert page1["next_offset"] == 2

    page2 = api_client.get(
        "/api/logs", params={"limit": 2, "offset": page1["next_offset"]}
    ).json()
    assert page2["count"] == 2
    assert page2["offset"] == 2

    # items 不重叠
    ids1 = {it["id"] for it in page1["items"]}
    ids2 = {it["id"] for it in page2["items"]}
    assert ids1.isdisjoint(ids2)


# ─── summary ─────────────────────────────────────────

def test_summary_buckets(api_client: TestClient) -> None:
    import asyncio

    asyncio.run(_seed_logs(api_client))

    r = api_client.get("/api/logs/summary")
    assert r.status_code == 200
    body = r.json()

    # 最近 1h：3 条（ERROR 1 + WARNING 1 + INFO 1）
    assert body["last_1h"]["ERROR"] == 1
    assert body["last_1h"]["WARNING"] == 1
    assert body["last_1h"]["INFO"] == 1
    assert body["last_1h"]["DEBUG"] == 0

    # 最近 24h：5 条（加上 2h / 5h 两条 INFO+DEBUG，不含 26h 那条）
    assert body["last_24h"]["ERROR"] == 1
    assert body["last_24h"]["WARNING"] == 1
    assert body["last_24h"]["INFO"] == 2
    assert body["last_24h"]["DEBUG"] == 1

    assert body["total"] == 6
    assert isinstance(body["top_loggers_24h"], list)
    assert len(body["top_loggers_24h"]) <= 10


# ─── meta ─────────────────────────────────────────────

def test_meta(api_client: TestClient) -> None:
    r = api_client.get("/api/logs/meta")
    assert r.status_code == 200
    body = r.json()
    assert body["levels"] == ["DEBUG", "INFO", "WARNING", "ERROR"]
    assert "API" in body["tags"]
    assert "CONFIG" in body["tags"]
    assert "api" in body["logger_prefixes"]
    assert "collector" in body["logger_prefixes"]
