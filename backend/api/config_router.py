"""配置 API —— 暴露 RulesConfigService 能力给前端。

路由总览::

    GET    /api/config/meta               前端渲染表单用的 groups+items
    GET    /api/config                    当前合并 snapshot + 全部 overrides
    GET    /api/config/audit              审计日志（支持 key / limit 过滤）
    GET    /api/config/item/{key:path}    单项详情
    PATCH  /api/config                    bulk 写入（含单项）
    POST   /api/config/preview            不落盘：返回应用后的 snapshot
    POST   /api/config/reset              by key 或全量复位

所有写入触发的热更新链路（4.1 已接）：
    RulesConfigService → 广播 ConfigChangeEvent
    lifespan 订阅者 → 重算 RuleRunner._config / 清 dashboard cache
"""

from __future__ import annotations

import copy
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from backend.ai.config import mask_secret
from backend.core.logging import Tags
from backend.core.rules_config import RulesConfigService
from backend.storage.repositories import ConfigRepository

logger = logging.getLogger("api.config")

router = APIRouter(prefix="/api/config", tags=["config"])


# ─── Secret mask helpers ──────────────────────────────────

def _secret_keys(meta_items: dict[str, Any]) -> set[str]:
    """枚举 meta.yaml 里所有 ``format: "secret"`` 的 key 路径。"""
    return {
        k for k, m in meta_items.items()
        if isinstance(m, dict) and m.get("format") == "secret"
    }


def _set_nested(data: dict[str, Any], key_path: str, value: Any) -> None:
    """按点分路径写入嵌套 dict；中间缺失的节点跳过（不新建）。"""
    parts = key_path.split(".")
    cursor: Any = data
    for p in parts[:-1]:
        if not isinstance(cursor, dict) or p not in cursor:
            return
        cursor = cursor[p]
    if isinstance(cursor, dict) and parts[-1] in cursor:
        cursor[parts[-1]] = value


def _mask_values_tree(values: dict[str, Any], secret_keys: set[str]) -> dict[str, Any]:
    """给嵌套 values 树里所有 secret 字段替换成 mask 形态（原地深拷贝）。"""
    masked = copy.deepcopy(values)
    for key in secret_keys:
        try:
            parts = key.split(".")
            cursor: Any = masked
            ok = True
            for p in parts[:-1]:
                if not isinstance(cursor, dict) or p not in cursor:
                    ok = False
                    break
                cursor = cursor[p]
            if ok and isinstance(cursor, dict) and parts[-1] in cursor:
                cursor[parts[-1]] = mask_secret(str(cursor[parts[-1]] or ""))
        except Exception:  # noqa: BLE001
            continue
    return masked


def _mask_overrides_list(
    overrides: list[dict[str, Any]], secret_keys: set[str]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in overrides:
        r = dict(row)
        if r.get("key") in secret_keys and "value" in r:
            r["value"] = mask_secret(str(r.get("value") or ""))
        out.append(r)
    return out


def _mask_audit_list(
    rows: list[dict[str, Any]], secret_keys: set[str]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        r = dict(row)
        if r.get("key") in secret_keys:
            if "old_value" in r:
                r["old_value"] = mask_secret(str(r.get("old_value") or ""))
            if "new_value" in r:
                r["new_value"] = mask_secret(str(r.get("new_value") or ""))
        out.append(r)
    return out


# ─── 依赖 ─────────────────────────────────────────────────

def _svc(request: Request) -> RulesConfigService:
    return request.app.state.rules_config_svc


def _repo(request: Request) -> ConfigRepository:
    return request.app.state.config_repo


# ─── 请求模型 ─────────────────────────────────────────────

class BulkSetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: dict[str, Any] = Field(
        ..., min_length=1, description="key(点分路径) → value"
    )
    updated_by: str = Field(default="ui", min_length=1, max_length=64)
    reason: str | None = Field(default=None, max_length=200)


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overrides: dict[str, Any] = Field(..., min_length=1)


class ResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str | None = Field(
        default=None, description="要复位的 key；省略则复位全部 overrides"
    )
    updated_by: str = Field(default="ui", min_length=1, max_length=64)
    reason: str | None = Field(default=None, max_length=200)


# ─── 静态路径在先 ─────────────────────────────────────────

@router.get("/meta")
async def get_meta(request: Request) -> dict[str, Any]:
    """给前端渲染配置表单：groups 决定分组/顺序，items 决定每项约束。"""
    return _svc(request).meta()


@router.get("")
async def get_config(request: Request) -> dict[str, Any]:
    """返回当前合并 snapshot + 原始 overrides。

    - ``values``   嵌套 dict：default + override 合并后的运行真理源
    - ``overrides`` 数组：每条带 value_type / updated_at / updated_by / reason

    V1.1 · Phase 9：所有 ``format: "secret"`` 字段在 values / overrides 中 mask。
    """
    svc = _svc(request)
    overrides = await _repo(request).list_raw()
    secret_keys = _secret_keys(svc.meta()["items"])
    return {
        "values": _mask_values_tree(svc.snapshot(), secret_keys),
        "overrides": _mask_overrides_list(overrides, secret_keys),
    }


@router.get("/audit")
async def get_audit(
    request: Request,
    key: str | None = Query(None, description="按 key 过滤；省略则返回全局最近 N 条"),
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    rows = await _repo(request).list_audit(key=key, limit=limit)
    svc = _svc(request)
    secret_keys = _secret_keys(svc.meta()["items"])
    rows = _mask_audit_list(rows, secret_keys)
    return {"items": rows, "total": len(rows)}


@router.post("/preview")
async def preview_config(
    request: Request, payload: PreviewRequest
) -> dict[str, Any]:
    """不落盘：返回应用临时覆盖后的 snapshot，便于前端在"保存"前看差异。"""
    svc = _svc(request)
    after = svc.preview(payload.overrides)
    return {
        "snapshot_before": svc.snapshot(),
        "snapshot_after": after,
    }


@router.post("/reset")
async def reset_config(
    request: Request, payload: ResetRequest
) -> dict[str, Any]:
    """by key 复位单项；省略 ``key`` 则清空全部 overrides（reset_all）。"""
    svc = _svc(request)

    if payload.key is None:
        removed = await svc.reset_all(
            updated_by=payload.updated_by, reason=payload.reason
        )
        logger.info(
            f"配置全量复位 removed={removed} by={payload.updated_by}",
            extra={"tags": [Tags.CONFIG, Tags.API]},
        )
        return {"scope": "all", "removed": removed}

    removed = await svc.reset(
        payload.key, updated_by=payload.updated_by, reason=payload.reason
    )
    return {
        "scope": "single",
        "key": payload.key,
        "removed": removed,
        "value_after": svc.get(payload.key),
    }


# ─── bulk PATCH（含单项） ────────────────────────────────

@router.patch("")
async def patch_config(
    request: Request, payload: BulkSetRequest
) -> dict[str, Any]:
    """bulk 写入；任何一项非法 → 整批拒绝（RulesConfigService 已保证原子）。"""
    svc = _svc(request)
    applied = await svc.bulk_set(
        payload.items,
        updated_by=payload.updated_by,
        reason=payload.reason,
    )
    logger.info(
        f"配置批量写入 keys={list(applied.keys())} by={payload.updated_by}",
        extra={
            "tags": [Tags.CONFIG, Tags.API],
            "context": {
                "keys": list(applied.keys()),
                "updated_by": payload.updated_by,
            },
        },
    )
    return {"applied": applied, "count": len(applied)}


# ─── 单项查询（放最后，避免吞其它静态路径） ────────────

@router.get("/item/{key:path}")
async def get_config_item(request: Request, key: str) -> dict[str, Any]:
    """单项详情：当前运行值 + 出厂默认值 + 是否被 override + 该项的 meta。

    V1.1 · Phase 9：若该项 ``format=="secret"``，value 与 override_value 返回 mask。
    """
    svc = _svc(request)
    if not svc.is_tier1(key):
        raise HTTPException(
            status_code=404,
            detail=f"配置项 {key} 不在可配置白名单内（Tier 1）",
        )
    meta = svc.meta()["items"].get(key)
    override = await _repo(request).get(key)
    value: Any = svc.get(key)
    override_value = override
    if isinstance(meta, dict) and meta.get("format") == "secret":
        value = mask_secret(str(value or ""))
        if override_value is not None:
            override_value = mask_secret(str(override_value or ""))
    return {
        "key": key,
        "value": value,
        "is_overridden": override is not None,
        "override_value": override_value,
        "meta": meta,
    }
