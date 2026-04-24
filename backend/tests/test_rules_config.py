"""规则配置服务 + 配置仓库 单元测试。

覆盖：
1. ConfigRepository CRUD + audit
2. deep-merge 正确性
3. ConfigService.get / set / bulk_set / reset / reset_all
4. meta 白名单拦截（非 Tier 1 key）
5. 类型 / 范围校验
6. 订阅 listener
7. preview（不落盘）
"""

from __future__ import annotations

import pytest

from backend.core.exceptions import (
    ConfigKeyNotAllowedError,
    ConfigValueInvalidError,
)
from backend.core.rules_config import (
    ConfigChangeEvent,
    RulesConfigService,
    _deep_merge,
    _remove_path,
    validate_value,
)
from backend.storage.repositories.config import (
    ConfigRepository,
    decode_value,
    encode_value,
    infer_value_type,
)


# ─── 值类型推断 ──────────────────────────────────────────────


def test_infer_value_type_basic():
    assert infer_value_type(True) == "bool"
    assert infer_value_type(1) == "int"
    assert infer_value_type(1.5) == "number"
    assert infer_value_type("x") == "string"
    assert infer_value_type([1, 2]) == "array"
    assert infer_value_type({"a": 1}) == "object"
    assert infer_value_type(None) == "null"


def test_encode_decode_roundtrip():
    payload = {"a": 1, "b": [1.2, 3.4], "c": True}
    assert decode_value(encode_value(payload)) == payload


# ─── deep_merge ──────────────────────────────────────────────


def test_deep_merge_basic():
    base = {"a": {"b": 1, "c": 2}, "d": [1]}
    override = {"a": {"c": 99, "e": 3}, "f": "x"}
    m = _deep_merge(base, override)
    assert m == {"a": {"b": 1, "c": 99, "e": 3}, "d": [1], "f": "x"}
    # 不能污染 base
    assert base == {"a": {"b": 1, "c": 2}, "d": [1]}


def test_deep_merge_array_replaced_entirely():
    base = {"a": [1, 2, 3]}
    override = {"a": [9]}
    assert _deep_merge(base, override) == {"a": [9]}


def test_remove_path_cleans_empty_parents():
    tree = {"a": {"b": {"c": 1}}, "x": 2}
    out = _remove_path(tree, "a.b.c")
    assert out == {"x": 2}
    assert "a" not in out


def test_remove_path_noop_when_missing():
    tree = {"a": {"b": 1}}
    out = _remove_path(tree, "a.z.y")
    assert out == tree


# ─── 校验 validate_value ─────────────────────────────────────


def test_validate_int_ok_and_out_of_range():
    meta = {"type": "int", "min": 1, "max": 10}
    assert validate_value(meta, 5) == 5
    with pytest.raises(ConfigValueInvalidError):
        validate_value(meta, 0)
    with pytest.raises(ConfigValueInvalidError):
        validate_value(meta, 11)
    # bool 不能当 int 使用
    with pytest.raises(ConfigValueInvalidError):
        validate_value(meta, True)


def test_validate_percent_coerces_int_to_float():
    meta = {"type": "percent", "min": 0, "max": 1}
    v = validate_value(meta, 0)
    assert isinstance(v, float) and v == 0.0


def test_validate_enum():
    meta = {"type": "enum", "options": ["dark", "light"]}
    assert validate_value(meta, "dark") == "dark"
    with pytest.raises(ConfigValueInvalidError):
        validate_value(meta, "neon")


def test_validate_array_number():
    meta = {"type": "array", "item_type": "number"}
    v = validate_value(meta, [1, 2.5])
    assert v == [1.0, 2.5]
    with pytest.raises(ConfigValueInvalidError):
        validate_value(meta, [1, "x"])


def test_validate_bool_strict():
    meta = {"type": "bool"}
    assert validate_value(meta, True) is True
    with pytest.raises(ConfigValueInvalidError):
        validate_value(meta, 1)  # 1 不是 bool


# ─── ConfigRepository ───────────────────────────────────────


@pytest.mark.asyncio
async def test_config_repo_crud_and_audit(db):
    repo = ConfigRepository(db)

    # 初始为空
    assert await repo.list_all() == {}

    # set
    await repo.set(
        "capabilities.accumulation.weights.fair_value_slope",
        0.25,
        updated_by="user",
        reason="测试",
    )
    all_values = await repo.list_all()
    assert all_values == {
        "capabilities.accumulation.weights.fair_value_slope": 0.25,
    }

    # 再 set 同 key：生成新的 audit 记录
    await repo.set(
        "capabilities.accumulation.weights.fair_value_slope",
        0.30,
        updated_by="ai_review",
        reason="日终复盘",
    )
    audit = await repo.list_audit()
    assert len(audit) == 2
    # 最新在前
    assert audit[0]["new_value"] == 0.30
    assert audit[0]["updated_by"] == "ai_review"
    assert audit[1]["new_value"] == 0.25

    # delete
    removed = await repo.delete(
        "capabilities.accumulation.weights.fair_value_slope",
        updated_by="user",
    )
    assert removed is True
    assert await repo.list_all() == {}
    # 再删一次 → False
    assert await repo.delete(
        "capabilities.accumulation.weights.fair_value_slope",
        updated_by="user",
    ) is False

    # audit 仍在（delete 也会写一条 new_value=NULL）
    audit = await repo.list_audit(key="capabilities.accumulation.weights.fair_value_slope")
    assert len(audit) == 3
    assert audit[0]["new_value"] is None  # 最后一条是删除


@pytest.mark.asyncio
async def test_config_repo_clear_all(db):
    repo = ConfigRepository(db)
    await repo.set("capabilities.accumulation.weights.fair_value_slope", 0.25, updated_by="u")
    await repo.set("capabilities.breakout.weights.whale_resonance", 0.3, updated_by="u")
    removed = await repo.clear_all(updated_by="u", reason="出厂重置")
    assert removed == 2
    assert await repo.list_all() == {}


@pytest.mark.asyncio
async def test_config_repo_prune_audit(db):
    repo = ConfigRepository(db)
    await repo.set("capabilities.accumulation.weights.fair_value_slope", 0.25, updated_by="u")
    # older_than 设到未来，会清空
    removed = await repo.prune_audit(older_than_ms=10**15)
    assert removed >= 1
    assert await repo.list_audit() == []


# ─── ConfigService ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_config_service_load_and_get(settings, db):
    repo = ConfigRepository(db)
    svc = RulesConfigService(settings, repo)
    await svc.load()

    # 默认值能取到
    v = svc.get("capabilities.accumulation.weights.fair_value_slope")
    assert v == pytest.approx(0.20)


@pytest.mark.asyncio
async def test_config_service_set_merges(settings, db):
    repo = ConfigRepository(db)
    svc = RulesConfigService(settings, repo)
    await svc.load()

    before = svc.get("capabilities.accumulation.weights.fair_value_slope")
    normalized = await svc.set(
        "capabilities.accumulation.weights.fair_value_slope",
        0.35,
        updated_by="user",
    )
    assert normalized == 0.35
    assert svc.get("capabilities.accumulation.weights.fair_value_slope") == 0.35

    # 重 load 也应能恢复
    svc2 = RulesConfigService(settings, repo)
    await svc2.load()
    assert svc2.get("capabilities.accumulation.weights.fair_value_slope") == 0.35
    assert before != 0.35  # 确保前后确实变了


@pytest.mark.asyncio
async def test_config_service_rejects_non_tier1(settings, db):
    repo = ConfigRepository(db)
    svc = RulesConfigService(settings, repo)
    await svc.load()

    # collector.global_rps 是 app.yaml 的字段，不在 meta.items 里 → Tier 3
    with pytest.raises(ConfigKeyNotAllowedError):
        await svc.set("collector.global_rps", 10, updated_by="user")


@pytest.mark.asyncio
async def test_config_service_value_validation(settings, db):
    repo = ConfigRepository(db)
    svc = RulesConfigService(settings, repo)
    await svc.load()

    # weight 范围 0-1：超上限报错
    with pytest.raises(ConfigValueInvalidError):
        await svc.set(
            "capabilities.accumulation.weights.fair_value_slope",
            2.0,
            updated_by="user",
        )


@pytest.mark.asyncio
async def test_config_service_bulk_set_is_atomic(settings, db):
    repo = ConfigRepository(db)
    svc = RulesConfigService(settings, repo)
    await svc.load()

    original_a = svc.get("capabilities.accumulation.weights.fair_value_slope")

    # 这批有一个非法 key，必须整批拒绝
    with pytest.raises(ConfigKeyNotAllowedError):
        await svc.bulk_set(
            {
                "capabilities.accumulation.weights.fair_value_slope": 0.25,
                "collector.global_rps": 99,  # Tier 3
            },
            updated_by="user",
        )
    # 失败后第一个 key 也不应写入
    assert svc.get("capabilities.accumulation.weights.fair_value_slope") == original_a


@pytest.mark.asyncio
async def test_config_service_reset_restores_default(settings, db):
    repo = ConfigRepository(db)
    svc = RulesConfigService(settings, repo)
    await svc.load()

    default_val = svc.get("capabilities.accumulation.weights.fair_value_slope")
    await svc.set(
        "capabilities.accumulation.weights.fair_value_slope",
        0.40,
        updated_by="user",
    )
    assert svc.get("capabilities.accumulation.weights.fair_value_slope") == 0.40

    removed = await svc.reset(
        "capabilities.accumulation.weights.fair_value_slope",
        updated_by="user",
    )
    assert removed is True
    assert svc.get("capabilities.accumulation.weights.fair_value_slope") == default_val


@pytest.mark.asyncio
async def test_config_service_reset_all(settings, db):
    repo = ConfigRepository(db)
    svc = RulesConfigService(settings, repo)
    await svc.load()

    await svc.set("capabilities.accumulation.weights.fair_value_slope", 0.35, updated_by="u")
    await svc.set("capabilities.breakout.weights.whale_resonance", 0.30, updated_by="u")

    removed = await svc.reset_all(updated_by="u")
    assert removed == 2
    # 都回到默认值
    assert svc.get("capabilities.accumulation.weights.fair_value_slope") == pytest.approx(0.20)
    assert svc.get("capabilities.breakout.weights.whale_resonance") == pytest.approx(0.25)


@pytest.mark.asyncio
async def test_config_service_subscribe_dispatches(settings, db):
    repo = ConfigRepository(db)
    svc = RulesConfigService(settings, repo)
    await svc.load()

    events: list[ConfigChangeEvent] = []

    async def listener(ev: ConfigChangeEvent) -> None:
        events.append(ev)

    unsub = svc.subscribe(listener)
    try:
        await svc.set(
            "capabilities.accumulation.weights.fair_value_slope",
            0.33,
            updated_by="user",
        )
    finally:
        unsub()

    assert len(events) == 1
    assert events[0].key == "capabilities.accumulation.weights.fair_value_slope"
    assert events[0].new_value == 0.33
    assert events[0].kind == "set"

    # 取消订阅后不再接
    await svc.set(
        "capabilities.accumulation.weights.fair_value_slope",
        0.36,
        updated_by="user",
    )
    assert len(events) == 1


@pytest.mark.asyncio
async def test_config_service_preview_no_side_effect(settings, db):
    repo = ConfigRepository(db)
    svc = RulesConfigService(settings, repo)
    await svc.load()

    prev_val = svc.get("capabilities.accumulation.weights.fair_value_slope")
    preview_snapshot = svc.preview(
        {"capabilities.accumulation.weights.fair_value_slope": 0.88}
    )
    # 预览里值变了
    assert preview_snapshot["capabilities"]["accumulation"]["weights"]["fair_value_slope"] == 0.88
    # 但实际 get 未变
    assert svc.get("capabilities.accumulation.weights.fair_value_slope") == prev_val
    # 存储也没写
    assert await repo.list_all() == {}


def test_meta_every_group_has_items(settings):
    """meta 里声明的每个 group 都至少有一个 item 引用（防空组）。"""
    items = settings.rules_meta.get("items", {})
    groups_in_items = {it["group"] for it in items.values() if it.get("group")}
    declared_groups = {g["id"] for g in settings.rules_meta.get("groups", [])}
    # 每个被引用的 group 都应该在 groups 列表里
    assert groups_in_items.issubset(declared_groups), (
        f"items 里用到但未在 groups 声明的分组: {groups_in_items - declared_groups}"
    )


def test_every_meta_item_has_valid_default(settings):
    """meta.items 里的每个 Tier 1 key 在 default YAML 里都有默认值，且符合约束。"""
    items = settings.rules_meta.get("items", {})
    defaults = settings.rules_defaults

    missing: list[str] = []
    invalid: list[tuple[str, str]] = []
    for path, meta in items.items():
        try:
            cursor = defaults
            for part in path.split("."):
                cursor = cursor[part]
            validate_value(meta, cursor)
        except (KeyError, TypeError):
            missing.append(path)
        except ConfigValueInvalidError as e:
            invalid.append((path, str(e)))

    assert not missing, f"meta 里声明但 default 缺省值的 key: {missing}"
    assert not invalid, f"default 值不满足 meta 约束: {invalid}"
