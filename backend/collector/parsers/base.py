"""Parser 基类型与通用工具。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel


@dataclass
class ParserResult:
    """解析结果。

    - ``atoms``:        按 AtomRepositories 字段名分组的模型列表（upsert 语义）
    - ``replace_scopes``: 若某键出现在这里，engine 会走 ``replace_for(scope)``
                         而不是 upsert。典型：价位/HVN/真空/燃料/heatmap
    """

    atoms: dict[str, list[BaseModel]] = field(default_factory=dict)
    replace_scopes: dict[str, dict[str, Any]] = field(default_factory=dict)

    def add(self, key: str, models: list[BaseModel]) -> None:
        if not models:
            return
        self.atoms.setdefault(key, []).extend(models)

    def replace(self, key: str, scope: dict[str, Any], models: list[BaseModel]) -> None:
        self.atoms[key] = list(models)
        self.replace_scopes[key] = dict(scope)

    def total(self) -> int:
        return sum(len(v) for v in self.atoms.values())


ParserFn = Callable[[str, str, dict[str, Any]], ParserResult]


# ─── 字段转换工具 ───

def _as_int_ms(v: Any) -> int:
    """把 ts 字段规整到 ms 整数。"""
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    if isinstance(v, str):
        s = v.strip()
        if s.isdigit():
            return int(s)
        s_iso = s.replace(" ", "T")
        if "+" not in s_iso[10:] and not s_iso.endswith("Z"):
            s_iso += "+00:00"
        s_iso = s_iso.replace("Z", "+00:00")
        return int(datetime.fromisoformat(s_iso).timestamp() * 1000)
    raise ValueError(f"无法解析时间戳: {v!r}")


def _first_number(d: dict, keys: tuple[str, ...]) -> float:
    for k in keys:
        if k in d and d[k] is not None:
            return float(d[k])
    raise KeyError(f"缺字段: {keys}")


def _first_int_ms(d: dict, keys: tuple[str, ...]) -> int:
    for k in keys:
        if k in d and d[k] is not None:
            return _as_int_ms(d[k])
    raise KeyError(f"缺字段: {keys}")


def _safe_list(payload: dict, key: str) -> list:
    v = payload.get(key)
    return v if isinstance(v, list) else []


def _safe_dict(payload: dict, key: str) -> dict | None:
    v = payload.get(key)
    return v if isinstance(v, dict) else None


__all__ = [
    "ParserFn",
    "ParserResult",
    "_as_int_ms",
    "_first_int_ms",
    "_first_number",
    "_safe_dict",
    "_safe_list",
]
