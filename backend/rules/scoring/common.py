"""评分通用工具：线性裁剪、band 映射、配置读取。"""

from __future__ import annotations

from typing import Any


def clamp01(x: float) -> float:
    if x < 0:
        return 0.0
    if x > 1:
        return 1.0
    return x


def ratio_above(value: float | None, threshold: float) -> float:
    """value >= threshold → 1；value <= 0 → 0；中间线性。"""
    if value is None or threshold <= 0:
        return 0.0
    return clamp01(value / threshold)


def ratio_below(value: float | None, threshold: float) -> float:
    """"越小越满分"：value <= 0 → 1；value >= threshold → 0。"""
    if value is None or threshold <= 0:
        return 0.0
    return clamp01((threshold - value) / threshold)


def band_from(score: float, bands: dict[str, float], default: str = "weak") -> str:
    """label_bands 格式：{"strong": 60, "very_strong": 80}。"""
    # 从高到低排序：分数 >= 该阈值即命中
    ordered = sorted(bands.items(), key=lambda kv: -kv[1])
    for name, th in ordered:
        if score >= th:
            return name
    return default


def cfg_path(cfg: dict[str, Any] | None, path: str, default: Any = None) -> Any:
    """按 'a.b.c' 取配置，None 走 default。"""
    if cfg is None:
        return default
    cur: Any = cfg
    for seg in path.split("."):
        if not isinstance(cur, dict) or seg not in cur:
            return default
        cur = cur[seg]
    return cur


def finalize_score(evidences: list) -> float:
    """累加所有 evidence.contribution，裁到 0-100。"""
    total = sum(e.contribution for e in evidences)
    if total < 0:
        return 0.0
    if total > 100:
        return 100.0
    return round(total, 2)


__all__ = [
    "band_from",
    "cfg_path",
    "clamp01",
    "finalize_score",
    "ratio_above",
    "ratio_below",
]
