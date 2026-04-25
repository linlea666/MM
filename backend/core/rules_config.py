"""规则引擎配置服务。

职责：
1. 合并 ``rules.default.yaml``（出厂默认）+ SQLite ``config_overrides``（动态覆盖）
   产出运行时 "真理源"：一份 deep-merge 后的嵌套 dict。
2. 提供点分路径 ``get("capabilities.accumulation.weights.fair_value_slope")`` 取值。
3. 校验写入值是否满足 ``rules.meta.yaml`` 的 Tier 1 白名单与类型约束。
4. 订阅 / 广播 ``config.changed`` 事件（Step 4 接 WebSocket）。

使用：
    svc = RulesConfigService(settings=settings, repo=cfg_repo)
    await svc.load()

    weight = svc.get("capabilities.accumulation.weights.fair_value_slope")  # 0.20

    await svc.set(
        "capabilities.accumulation.weights.fair_value_slope",
        0.25,
        updated_by="user",
        reason="上调 fair_value 权重",
    )

规则引擎每次 score 时通过 ``svc.snapshot()`` 拿一份不可变快照，零缓存延迟。
"""

from __future__ import annotations

import asyncio
import copy
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .config import Settings
from .exceptions import (
    ConfigError,
    ConfigKeyNotAllowedError,
    ConfigValueInvalidError,
)

logger = logging.getLogger("core.rules_config")

# ─── 事件载荷 ─────────────────────────────────────────────


@dataclass
class ConfigChangeEvent:
    """单次变更事件，给订阅者用（WS 广播 / 规则引擎刷新）。

    V1.1 · 批量去抖：``set_many`` 一次写多个 key 时，**只派发一个** ``kind="set_batch"`` 事件，
    具体改动 keys 放在 ``batch_keys`` 里。监听者（如 AI observer reload / RuleRunner 热更新）
    据此只 reload 一次。``key/old_value/new_value`` 三个字段在批量场景下保留首项以兼容旧消费者。
    """

    key: str
    old_value: Any
    new_value: Any
    updated_by: str
    reason: str | None
    kind: str  # "set" | "delete" | "reset_all" | "set_batch"
    batch_keys: list[str] = field(default_factory=list)


ChangeListener = Callable[[ConfigChangeEvent], Awaitable[None]]


# ─── 工具 ─────────────────────────────────────────────────


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """递归合并；override 胜出，非 dict 值直接替换。

    不破坏 base（返回新 dict），因此 snapshot() 可以复用 cache。
    """
    out: dict[str, Any] = {}
    for k, v in base.items():
        if (
            k in override
            and isinstance(v, Mapping)
            and isinstance(override[k], Mapping)
        ):
            out[k] = _deep_merge(v, dict(override[k]))
        elif k in override:
            out[k] = override[k]
        else:
            out[k] = copy.deepcopy(v) if isinstance(v, (dict, list)) else v
    for k, v in override.items():
        if k not in base:
            out[k] = copy.deepcopy(v) if isinstance(v, (dict, list)) else v
    return out


def _get_path(data: Mapping[str, Any], path: str) -> Any:
    cursor: Any = data
    for part in path.split("."):
        if not isinstance(cursor, Mapping) or part not in cursor:
            raise KeyError(path)
        cursor = cursor[part]
    return cursor


def _set_path(data: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cursor = data
    for p in parts[:-1]:
        nxt = cursor.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            cursor[p] = nxt
        cursor = nxt
    cursor[parts[-1]] = value


# ─── 类型 / 范围校验（依赖 meta.yaml 的 items 节点）───────


def _expect(cond: bool, msg: str) -> None:
    if not cond:
        raise ConfigValueInvalidError(msg)


def _looks_like_masked_secret(value: str) -> bool:
    """mask 形态侦测：值包含至少 3 个 ``*`` 就视为 mask 形态。

    前端回填时（用户没修改 secret）应当直接不传；若误传 mask 字符串，
    我们拒绝保存以避免覆盖真 key。
    """
    return isinstance(value, str) and value.count("*") >= 3


def validate_value(meta_item: Mapping[str, Any], value: Any) -> Any:
    """根据单项 meta 校验并可能强转 value；返回最终写入值。"""
    t = meta_item.get("type")
    fmt = meta_item.get("format")
    if t == "bool":
        _expect(isinstance(value, bool), f"期望 bool，实际 {type(value).__name__}")
    elif t == "int":
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        _expect(isinstance(value, int) and not isinstance(value, bool), f"期望 int，实际 {type(value).__name__}")
    elif t in ("number", "percent", "weight"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigValueInvalidError(f"期望 number，实际 {type(value).__name__}")
        value = float(value)
    elif t == "string":
        _expect(isinstance(value, str), f"期望 string，实际 {type(value).__name__}")
        # V1.1 · Phase 9：secret 格式特殊保护 —— 识别 mask 形态拒写
        if fmt == "secret" and _looks_like_masked_secret(value):
            raise ConfigValueInvalidError(
                "secret 字段不接受 mask 形态值（含 *）；若未修改请不要提交该字段。"
            )
    elif t == "enum":
        opts = meta_item.get("options") or []
        _expect(value in opts, f"必须是 {opts} 之一")
    elif t == "array":
        _expect(isinstance(value, list), f"期望 array，实际 {type(value).__name__}")
        item_type = meta_item.get("item_type")
        if item_type == "number":
            _expect(
                all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in value),
                "array 元素必须是 number",
            )
            value = [float(x) for x in value]
        elif item_type == "int":
            _expect(
                all(isinstance(x, int) and not isinstance(x, bool) for x in value),
                "array 元素必须是 int",
            )
        elif item_type == "string":
            _expect(all(isinstance(x, str) for x in value), "array 元素必须是 string")
    else:
        raise ConfigValueInvalidError(f"未知 meta.type: {t}")

    if t in ("number", "int", "percent", "weight"):
        mn = meta_item.get("min")
        mx = meta_item.get("max")
        if mn is not None:
            _expect(value >= mn, f"值 {value} 低于最小值 {mn}")
        if mx is not None:
            _expect(value <= mx, f"值 {value} 高于最大值 {mx}")
    return value


# ─── 服务主体 ─────────────────────────────────────────────


class RulesConfigService:
    """合并 default + override，提供 get/set/subscribe。"""

    def __init__(self, settings: Settings, repo) -> None:
        # repo: ConfigRepository，避免 storage→core 反向依赖这里不硬声明类型
        self._settings = settings
        self._repo = repo
        self._defaults: dict[str, Any] = copy.deepcopy(settings.rules_defaults or {})
        self._meta_items: dict[str, Any] = (settings.rules_meta or {}).get("items", {}) or {}
        self._meta_groups: list[dict[str, Any]] = (settings.rules_meta or {}).get("groups", []) or []
        self._overrides: dict[str, Any] = {}
        self._merged: dict[str, Any] = copy.deepcopy(self._defaults)
        self._lock = asyncio.Lock()
        self._listeners: list[ChangeListener] = []

    # ── 生命周期 ──

    async def load(self) -> None:
        """启动时调用，拉取所有 override 并构建合并 dict。"""
        raw = await self._repo.list_all()
        overrides_tree: dict[str, Any] = {}
        for path, val in raw.items():
            try:
                _set_path(overrides_tree, path, val)
            except Exception as e:  # pragma: no cover - 非法 key 已在写入时挡住
                logger.warning(
                    f"配置 override 路径异常跳过 {path}: {e}",
                    extra={"tags": ["CONFIG"], "context": {"key": path}},
                )
        self._overrides = overrides_tree
        self._merged = _deep_merge(self._defaults, self._overrides)
        logger.info(
            f"规则配置加载完成 overrides={len(raw)}",
            extra={"tags": ["CONFIG"], "context": {"override_count": len(raw)}},
        )

    # ── 查询 ──

    def snapshot(self) -> dict[str, Any]:
        """拿一份 deep-copy 的当前运行值。规则引擎每 tick 调用。"""
        return copy.deepcopy(self._merged)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return _get_path(self._merged, key)
        except KeyError:
            return default

    def meta(self) -> dict[str, Any]:
        """返回 UI 元数据（给前端渲染表单用）。"""
        return {"groups": self._meta_groups, "items": copy.deepcopy(self._meta_items)}

    def is_tier1(self, key: str) -> bool:
        return key in self._meta_items

    # ── 写入（所有 mutate 都走这）──

    async def set(
        self,
        key: str,
        value: Any,
        *,
        updated_by: str,
        reason: str | None = None,
    ) -> Any:
        if not self.is_tier1(key):
            raise ConfigKeyNotAllowedError(
                f"配置项 {key} 不在可配置白名单内（Tier 1），拒绝修改"
            )
        normalized = validate_value(self._meta_items[key], value)

        async with self._lock:
            old_value = self.get(key)
            await self._repo.set(key, normalized, updated_by=updated_by, reason=reason)
            _set_path(self._overrides, key, normalized)
            self._merged = _deep_merge(self._defaults, self._overrides)

        await self._dispatch(
            ConfigChangeEvent(
                key=key,
                old_value=old_value,
                new_value=normalized,
                updated_by=updated_by,
                reason=reason,
                kind="set",
            )
        )
        return normalized

    async def bulk_set(
        self,
        items: dict[str, Any],
        *,
        updated_by: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        # 先整批校验；任何一项失败整批拒绝
        normalized: dict[str, Any] = {}
        for k, v in items.items():
            if not self.is_tier1(k):
                raise ConfigKeyNotAllowedError(f"配置项 {k} 不在可配置白名单内")
            normalized[k] = validate_value(self._meta_items[k], v)

        async with self._lock:
            events: list[ConfigChangeEvent] = []
            for k, v in normalized.items():
                old_value = self.get(k)
                await self._repo.set(k, v, updated_by=updated_by, reason=reason)
                _set_path(self._overrides, k, v)
                events.append(
                    ConfigChangeEvent(
                        key=k,
                        old_value=old_value,
                        new_value=v,
                        updated_by=updated_by,
                        reason=reason,
                        kind="set",
                    )
                )
            self._merged = _deep_merge(self._defaults, self._overrides)

        # V1.1 · reload 去抖：set_many 批量只派发 1 次。
        # - len(events) == 1 时仍走单事件（kind="set"）保持向后兼容；
        # - 多事件时合并为 kind="set_batch"，监听者据此只 reload 一次。
        if len(events) == 1:
            await self._dispatch(events[0])
        elif events:
            first = events[0]
            await self._dispatch(
                ConfigChangeEvent(
                    key=first.key,
                    old_value=first.old_value,
                    new_value=first.new_value,
                    updated_by=updated_by,
                    reason=reason,
                    kind="set_batch",
                    batch_keys=[e.key for e in events],
                )
            )
        return normalized

    async def reset(
        self,
        key: str,
        *,
        updated_by: str,
        reason: str | None = None,
    ) -> bool:
        if not self.is_tier1(key):
            raise ConfigKeyNotAllowedError(f"配置项 {key} 不在可配置白名单内")
        async with self._lock:
            old_value = self.get(key)
            removed = await self._repo.delete(key, updated_by=updated_by, reason=reason)
            if removed:
                # 从 override 树里抹掉（走深层删除）
                self._overrides = _remove_path(self._overrides, key)
                self._merged = _deep_merge(self._defaults, self._overrides)

        if removed:
            await self._dispatch(
                ConfigChangeEvent(
                    key=key,
                    old_value=old_value,
                    new_value=self.get(key),
                    updated_by=updated_by,
                    reason=reason,
                    kind="delete",
                )
            )
        return removed

    async def reset_all(self, *, updated_by: str, reason: str | None = None) -> int:
        async with self._lock:
            removed = await self._repo.clear_all(updated_by=updated_by, reason=reason)
            self._overrides = {}
            self._merged = copy.deepcopy(self._defaults)
        if removed:
            await self._dispatch(
                ConfigChangeEvent(
                    key="*",
                    old_value=None,
                    new_value=None,
                    updated_by=updated_by,
                    reason=reason,
                    kind="reset_all",
                )
            )
        return removed

    # ── 预览（不落盘 / 不广播，给前端"应用前看效果"）──

    def preview(self, overrides: dict[str, Any]) -> dict[str, Any]:
        """给定一批临时覆盖，返回临时合并后的 snapshot。

        **不校验 Tier 1**，调用方可自愿 preview 任意值看差异。
        但类型校验仍走 meta 以避免明显错误。
        """
        tmp_overrides = copy.deepcopy(self._overrides)
        for k, v in overrides.items():
            if self.is_tier1(k):
                v = validate_value(self._meta_items[k], v)
            _set_path(tmp_overrides, k, v)
        return _deep_merge(self._defaults, tmp_overrides)

    # ── 订阅 ──

    def subscribe(self, listener: ChangeListener) -> Callable[[], None]:
        self._listeners.append(listener)

        def _unsub() -> None:
            try:
                self._listeners.remove(listener)
            except ValueError:
                pass

        return _unsub

    async def _dispatch(self, event: ConfigChangeEvent) -> None:
        for ln in list(self._listeners):
            try:
                await ln(event)
            except Exception as e:  # pragma: no cover
                logger.exception(
                    f"配置变更 listener 异常: {e}",
                    extra={"tags": ["CONFIG"], "context": {"key": event.key}},
                )


# ─── 辅助：从 override 树里剔除一个路径，空 dict 自动清理 ──


def _remove_path(tree: dict[str, Any], path: str) -> dict[str, Any]:
    """返回剔除指定路径后的新 tree；空的中间节点会被清掉。"""
    tree = copy.deepcopy(tree)
    parts = path.split(".")

    def _walk(node: Any, depth: int) -> bool:
        if not isinstance(node, dict):
            return False
        key = parts[depth]
        if key not in node:
            return False
        if depth == len(parts) - 1:
            del node[key]
            return True
        removed = _walk(node[key], depth + 1)
        if removed and isinstance(node[key], dict) and not node[key]:
            del node[key]
        return removed

    _walk(tree, 0)
    return tree


__all__ = [
    "ChangeListener",
    "ConfigChangeEvent",
    "RulesConfigService",
    "validate_value",
]
