"""Step 4.4 配置 API 集成测试。

复用 test_api.py 的集成 client fixture，覆盖：
- /api/config/meta            返回 groups + items
- /api/config                 返回 values + overrides
- /api/config/item/{key}      单项查询（合法 / 非白名单 → 404）
- PATCH /api/config           bulk 写入（合法、非白名单 400、越界 400、热更新生效）
- /api/config/preview         不落盘
- /api/config/reset           单项 + 全量
- /api/config/audit           按 key / 全局
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


# 跟 test_api.py 相同的 fixture，复制一份以避免跨文件依赖；逻辑完全一致
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


TIER1_KEY = "capabilities.accumulation.weights.fair_value_slope"
TIER1_KEY_2 = "capabilities.accumulation.weights.poc_shift_up"
NON_TIER1_KEY = "collector.global_rps"  # app.yaml 字段，不在 meta.items


# ─── 读接口 ──────────────────────────────────────────

def test_get_meta(api_client: TestClient) -> None:
    r = api_client.get("/api/config/meta")
    assert r.status_code == 200
    body = r.json()
    assert "groups" in body
    assert "items" in body
    assert TIER1_KEY in body["items"]


def test_meta_tier_basic_coverage(api_client: TestClient) -> None:
    """V1.1 · Phase 5：meta.yaml 至少标注了约 60 条 basic tier key，
    且涵盖所有权重/UI/关键位等常用项（小白模式的最小工作集）。"""
    r = api_client.get("/api/config/meta")
    assert r.status_code == 200
    items: dict[str, dict] = r.json()["items"]
    basic_keys = {k for k, v in items.items() if v.get("tier") == "basic"}

    # 数量下限（B2 ≈ 60）；给足余地以允许小幅调整
    assert len(basic_keys) >= 55, f"basic 条数异常：{len(basic_keys)}"

    # 关键代表：UI 主题、关键位档数、权重代表、Hero 阈值
    for must_have in (
        "ui.theme",
        "ui.refresh_ms",
        "key_levels.r_levels",
        "key_levels.s_levels",
        "key_levels.max_far_count",
        "hero.choch_alert_bars",
        "capabilities.accumulation.weights.fair_value_slope",
        "capabilities.breakout.weights.bos_confirm",
        "capabilities.reversal.weights.choch_reversal",
        "capabilities.key_level_strength.source_weights.cascade_band",
        "trade_plan.use_segment_portrait",
    ):
        assert must_have in basic_keys, f"缺失 basic 标注：{must_have}"

    # 专家项不应被误标：阈值、lookback 等属于 expert（默认未标 tier = expert）
    for must_not_basic in (
        "capabilities.accumulation.thresholds.imbalance_green_ratio",
        "capabilities.breakout.thresholds.pierce_atr_mult",
        "trade_plan.veto.exhaustion",
    ):
        tier = items.get(must_not_basic, {}).get("tier")
        assert tier != "basic", (
            f"{must_not_basic} 不应被标 basic（tier={tier}）"
        )


def test_get_config(api_client: TestClient) -> None:
    r = api_client.get("/api/config")
    assert r.status_code == 200
    body = r.json()
    assert "values" in body
    assert "overrides" in body
    # 初始应无 override
    assert body["overrides"] == []
    # 默认值能在 values 树里找到
    acc = body["values"]["capabilities"]["accumulation"]
    assert "weights" in acc and "fair_value_slope" in acc["weights"]


def test_get_item_tier1(api_client: TestClient) -> None:
    r = api_client.get(f"/api/config/item/{TIER1_KEY}")
    assert r.status_code == 200
    body = r.json()
    assert body["key"] == TIER1_KEY
    assert body["is_overridden"] is False
    assert body["override_value"] is None
    assert isinstance(body["value"], float)
    assert body["meta"]["type"] == "weight"


def test_get_item_non_tier1_is_404(api_client: TestClient) -> None:
    r = api_client.get(f"/api/config/item/{NON_TIER1_KEY}")
    assert r.status_code == 404


# ─── PATCH 写入 ─────────────────────────────────────

def test_patch_ok_and_item_reflects_override(api_client: TestClient) -> None:
    r = api_client.patch(
        "/api/config",
        json={
            "items": {TIER1_KEY: 0.35},
            "updated_by": "test",
            "reason": "上调",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["applied"] == {TIER1_KEY: 0.35}
    assert body["count"] == 1

    # 单项回查
    r2 = api_client.get(f"/api/config/item/{TIER1_KEY}")
    assert r2.json()["value"] == 0.35
    assert r2.json()["is_overridden"] is True
    assert r2.json()["override_value"] == 0.35

    # overrides 列表不空
    r3 = api_client.get("/api/config").json()
    assert any(o["key"] == TIER1_KEY for o in r3["overrides"])


def test_patch_rejects_non_tier1(api_client: TestClient) -> None:
    r = api_client.patch(
        "/api/config",
        json={"items": {NON_TIER1_KEY: 999}, "updated_by": "test"},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "CONFIG_KEY_NOT_ALLOWED"


def test_patch_rejects_out_of_range(api_client: TestClient) -> None:
    r = api_client.patch(
        "/api/config",
        json={"items": {TIER1_KEY: 1.5}, "updated_by": "test"},  # weight max=1
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "CONFIG_VALUE_INVALID"


def test_patch_atomic_reject_batch(api_client: TestClient) -> None:
    # 一合法一非法 → 整批拒绝，合法项不应被写入
    r = api_client.patch(
        "/api/config",
        json={
            "items": {TIER1_KEY: 0.5, TIER1_KEY_2: 5.0},  # 第二项越界
            "updated_by": "test",
        },
    )
    assert r.status_code == 400
    # TIER1_KEY 不应被写入
    item = api_client.get(f"/api/config/item/{TIER1_KEY}").json()
    assert item["is_overridden"] is False


# ─── preview ─────────────────────────────────────────

def test_preview_does_not_persist(api_client: TestClient) -> None:
    r = api_client.post(
        "/api/config/preview",
        json={"overrides": {TIER1_KEY: 0.9}},
    )
    assert r.status_code == 200
    body = r.json()
    assert "snapshot_before" in body and "snapshot_after" in body
    # after 里的值是临时覆盖
    after_val = body["snapshot_after"]["capabilities"]["accumulation"]["weights"][
        "fair_value_slope"
    ]
    assert after_val == 0.9
    # before 里仍是默认
    before_val = body["snapshot_before"]["capabilities"]["accumulation"]["weights"][
        "fair_value_slope"
    ]
    assert before_val != 0.9
    # 实际仓库没写
    item = api_client.get(f"/api/config/item/{TIER1_KEY}").json()
    assert item["is_overridden"] is False


# ─── reset ─────────────────────────────────────────

def test_reset_single_key(api_client: TestClient) -> None:
    api_client.patch(
        "/api/config",
        json={"items": {TIER1_KEY: 0.42}, "updated_by": "test"},
    )
    assert api_client.get(f"/api/config/item/{TIER1_KEY}").json()["is_overridden"]

    r = api_client.post(
        "/api/config/reset",
        json={"key": TIER1_KEY, "updated_by": "test"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["scope"] == "single"
    assert body["removed"] is True
    assert api_client.get(f"/api/config/item/{TIER1_KEY}").json()["is_overridden"] is False


def test_reset_all(api_client: TestClient) -> None:
    api_client.patch(
        "/api/config",
        json={
            "items": {TIER1_KEY: 0.42, TIER1_KEY_2: 0.33},
            "updated_by": "test",
        },
    )
    r = api_client.post("/api/config/reset", json={"updated_by": "test"})
    assert r.status_code == 200
    body = r.json()
    assert body["scope"] == "all"
    assert body["removed"] >= 2

    overrides = api_client.get("/api/config").json()["overrides"]
    assert overrides == []


# ─── audit ─────────────────────────────────────────

def test_audit_returns_records(api_client: TestClient) -> None:
    api_client.patch(
        "/api/config",
        json={"items": {TIER1_KEY: 0.25}, "updated_by": "alice", "reason": "测试"},
    )
    api_client.patch(
        "/api/config",
        json={"items": {TIER1_KEY: 0.27}, "updated_by": "alice", "reason": "再调"},
    )

    r = api_client.get("/api/config/audit", params={"key": TIER1_KEY, "limit": 10})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 2
    assert all(it["key"] == TIER1_KEY for it in body["items"])
    assert body["items"][0]["updated_by"] == "alice"

    # 全局
    r2 = api_client.get("/api/config/audit", params={"limit": 100})
    assert r2.status_code == 200
    assert r2.json()["total"] >= 2


# ─── V1.1 · Phase 9 · Secret mask ─────────────────────

SECRET_KEY = "ai.api_key"


def test_secret_key_is_masked_in_item(api_client: TestClient) -> None:
    """写入 api_key 后：单项查询返回 mask 形态。"""
    api_client.patch(
        "/api/config",
        json={
            "items": {SECRET_KEY: "sk-test-abcdef1234567890"},
            "updated_by": "test",
        },
    )
    r = api_client.get(f"/api/config/item/{SECRET_KEY}")
    assert r.status_code == 200
    body = r.json()
    value = body["value"]
    override_value = body["override_value"]
    assert isinstance(value, str) and "*" in value and "sk-" in value
    assert isinstance(override_value, str) and "*" in override_value
    # 全键位的原文"abcdef1234567890"不应出现在任何 mask 结果里
    assert "abcdef1234567890" not in value
    assert "abcdef1234567890" not in override_value


def test_secret_key_is_masked_in_global(api_client: TestClient) -> None:
    """全局 GET /api/config 的 values / overrides 都 mask。"""
    api_client.patch(
        "/api/config",
        json={
            "items": {SECRET_KEY: "sk-real-0011223344"},
            "updated_by": "test",
        },
    )
    body = api_client.get("/api/config").json()
    # values 树里 ai.api_key mask
    ai_val = body["values"]["ai"]["api_key"]
    assert "*" in ai_val and "0011223344" not in ai_val
    # overrides 列表里 mask
    row = next(o for o in body["overrides"] if o["key"] == SECRET_KEY)
    assert "*" in row["value"] and "0011223344" not in row["value"]


def test_secret_key_is_masked_in_audit(api_client: TestClient) -> None:
    """审计记录：old_value / new_value 都 mask。"""
    api_client.patch(
        "/api/config",
        json={"items": {SECRET_KEY: "sk-old-aaaaaaaa"}, "updated_by": "test"},
    )
    api_client.patch(
        "/api/config",
        json={"items": {SECRET_KEY: "sk-new-bbbbbbbb"}, "updated_by": "test"},
    )
    body = api_client.get("/api/config/audit", params={"key": SECRET_KEY}).json()
    assert body["total"] >= 2
    for it in body["items"]:
        for k in ("old_value", "new_value"):
            if k in it and it[k] is not None:
                assert "aaaaaaaa" not in str(it[k])
                assert "bbbbbbbb" not in str(it[k])


def test_secret_patch_rejects_masked_value(api_client: TestClient) -> None:
    """若前端把 mask 形态（含 ****）写回来，后端要拒绝以免覆盖真 key。"""
    api_client.patch(
        "/api/config",
        json={
            "items": {SECRET_KEY: "sk-real-key-9999"},
            "updated_by": "test",
        },
    )
    r = api_client.patch(
        "/api/config",
        json={
            "items": {SECRET_KEY: "sk-****9999"},  # mask 形态
            "updated_by": "test",
        },
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "CONFIG_VALUE_INVALID"
    # 真 key 不受影响（回查 mask 里仍含 "9999" 末尾）
    body = api_client.get(f"/api/config/item/{SECRET_KEY}").json()
    assert "9999" in body["value"]  # mask 保留末 4 位
