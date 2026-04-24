"""模块 5：流动性磁吸罗盘。

把 heatmap / fuel / vacuum 三类原子合成"磁吸目标"，
按 side 分组、按 score_magnet 打分、排序、截断到 max_targets_per_side。
"""

from __future__ import annotations

from typing import Any

from backend.models import LiquidityCompass, LiquidityTarget, MagnetSide

from ..features import FeatureSnapshot
from ..scoring import MagnetCandidate, score_magnet
from ..scoring.common import cfg_path

# source 标签（LiquidityTarget.source 字段）
_SRC_HEATMAP = "heatmap"
_SRC_FUEL = "fuel"
_SRC_VACUUM = "vacuum"


def _build_candidates(snap: FeatureSnapshot) -> list[tuple[MagnetCandidate, str]]:
    price = snap.last_price
    out: list[tuple[MagnetCandidate, str]] = []

    # heatmap bands → 一个 band 一个目标
    for hb in snap.heatmap:
        dist = abs(hb.price - price) / price if price > 0 else 0
        side: MagnetSide = "above" if hb.price > price else "below"
        out.append(
            (
                MagnetCandidate(
                    price=hb.price,
                    side="upside" if side == "above" else "downside",
                    heatmap_intensity=float(hb.intensity),
                    distance_pct=dist,
                ),
                _SRC_HEATMAP,
            )
        )

    # fuel bands → 中点
    for f in snap.liquidation_fuel:
        mid = (f.bottom + f.top) / 2
        side = "above" if mid > price else "below"
        dist = abs(mid - price) / price if price > 0 else 0
        out.append(
            (
                MagnetCandidate(
                    price=mid,
                    side="upside" if side == "above" else "downside",
                    fuel_strength=float(f.fuel),
                    distance_pct=dist,
                ),
                _SRC_FUEL,
            )
        )

    # vacuum bands → 中点
    for v in snap.vacuums:
        mid = (v.low + v.high) / 2
        side = "above" if mid > price else "below"
        dist = abs(mid - price) / price if price > 0 else 0
        pull = min((v.high - v.low) / max(price, 1), 0.05) / 0.05   # 归一到 0-1
        out.append(
            (
                MagnetCandidate(
                    price=mid,
                    side="upside" if side == "above" else "downside",
                    vacuum_pull=float(pull),
                    distance_pct=dist,
                ),
                _SRC_VACUUM,
            )
        )
    return out


def build_liquidity_map(
    snap: FeatureSnapshot, cfg: dict[str, Any] | None = None
) -> LiquidityCompass:
    max_per_side = int(cfg_path(cfg, "capabilities.liquidity_magnet.max_targets_per_side", 3))

    cands = _build_candidates(snap)
    above: list[LiquidityTarget] = []
    below: list[LiquidityTarget] = []

    scored: list[tuple[float, LiquidityTarget]] = []
    for cand, src in cands:
        res = score_magnet(cand, cfg)
        # 转成 intensity 0-1（规则层 score / 100）
        intensity = max(0.0, min(res.score / 100.0, 1.0))
        side: MagnetSide = "above" if cand.side == "upside" else "below"
        target = LiquidityTarget(
            side=side,
            price=round(cand.price, 6),
            distance_pct=round(cand.distance_pct, 4),
            intensity=round(intensity, 3),
            source=src,
        )
        scored.append((res.score, target))

    # 分 side 排序（intensity 高优先 + 距离近）
    above_sorted = sorted(
        [t for s, t in scored if t.side == "above"],
        key=lambda t: (-t.intensity, t.distance_pct),
    )
    below_sorted = sorted(
        [t for s, t in scored if t.side == "below"],
        key=lambda t: (-t.intensity, t.distance_pct),
    )
    above = above_sorted[:max_per_side]
    below = below_sorted[:max_per_side]

    # 最近一侧 & 距离
    nearest_side: MagnetSide | None = None
    nearest_dist: float | None = None
    nearest_above = min((t.distance_pct for t in above), default=None)
    nearest_below = min((t.distance_pct for t in below), default=None)
    if nearest_above is not None and (nearest_below is None or nearest_above < nearest_below):
        nearest_side = "above"
        nearest_dist = nearest_above
    elif nearest_below is not None:
        nearest_side = "below"
        nearest_dist = nearest_below

    return LiquidityCompass(
        above_targets=above,
        below_targets=below,
        nearest_side=nearest_side,
        nearest_distance_pct=nearest_dist,
    )


__all__ = ["build_liquidity_map"]
