"""流动性磁吸评分（对单个目标打分）。

一个候选目标（heatmap / fuel / vacuum 合成）的吸引力由 4 个维度决定：
1. heatmap_intensity  清算热度
2. fuel_strength      燃料强度
3. vacuum_pull        真空带拖拽
4. distance_close     距离当前价越近越强（有阈值封顶）
"""

from __future__ import annotations

from typing import Any

from .common import cfg_path, clamp01, finalize_score
from .types import Evidence, MagnetCandidate, MagnetScore


def score_magnet(
    cand: MagnetCandidate, cfg: dict[str, Any] | None = None
) -> MagnetScore:
    weights = cfg_path(cfg, "capabilities.liquidity_magnet.weights", {}) or {}
    thr = cfg_path(cfg, "capabilities.liquidity_magnet.thresholds", {}) or {}

    max_dist = float(thr.get("max_distance_pct", 0.05))
    h_min = float(thr.get("heatmap_min_intensity", 0.5))
    f_min = float(thr.get("fuel_min", 0.3))

    evs: list[Evidence] = []

    # 1) heatmap
    w = float(weights.get("heatmap_intensity", 0.40))
    h_hit = cand.heatmap_intensity >= h_min
    evs.append(
        Evidence(
            rule_id="heatmap_intensity", label="清算热度",
            weight=w, hit=h_hit, ratio=clamp01(cand.heatmap_intensity),
            value=round(cand.heatmap_intensity, 3), threshold=h_min,
        )
    )

    # 2) fuel
    w = float(weights.get("fuel_strength", 0.30))
    f_hit = cand.fuel_strength >= f_min
    evs.append(
        Evidence(
            rule_id="fuel_strength", label="清算燃料",
            weight=w, hit=f_hit, ratio=clamp01(cand.fuel_strength),
            value=round(cand.fuel_strength, 3), threshold=f_min,
        )
    )

    # 3) vacuum
    w = float(weights.get("vacuum_pull", 0.20))
    v_hit = cand.vacuum_pull > 0
    evs.append(
        Evidence(
            rule_id="vacuum_pull", label="真空带拉扯",
            weight=w, hit=v_hit, ratio=clamp01(cand.vacuum_pull),
            value=round(cand.vacuum_pull, 3),
        )
    )

    # 4) distance（越近越满分；超过 max_dist → 0）
    w = float(weights.get("distance_close", 0.10))
    dist = max(cand.distance_pct, 0.0)
    if max_dist <= 0:
        d_ratio = 0.0
    else:
        d_ratio = clamp01((max_dist - dist) / max_dist)
    evs.append(
        Evidence(
            rule_id="distance_close", label="距离近",
            weight=w, hit=dist <= max_dist, ratio=d_ratio,
            value=round(dist * 100, 3),
            threshold=round(max_dist * 100, 3),
        )
    )

    score = finalize_score(evs)
    return MagnetScore(
        price=cand.price,
        side=cand.side,
        score=score,
        distance_pct=cand.distance_pct,
        evidence=evs,
    )


__all__ = ["score_magnet"]
