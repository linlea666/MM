"""模块 4：关键位阶梯图（R3/R2/R1/S1/S2/S3）。

步骤：
1. 从 FeatureSnapshot 的各价位原子（HVN / zone / OB / micro_poc / vwap / heatmap / vacuum）
   收集候选 LevelCandidate
2. 按 merge_distance_pct 聚合（同一价位多来源合并）
3. 用 ``score_level`` 给每个聚合后的 level 打分
4. 按 side + score 选 R3..R1（resistance 从近到远 + 分最高者优先）
   和 S1..S3
"""

from __future__ import annotations

from typing import Any

from backend.models import Level, LevelFit, LevelLadder, LevelStrength

from ..features import FeatureSnapshot
from ..scoring import LevelCandidate, LevelSource, score_level
from ..scoring.common import cfg_path

# band → LevelStrength
_BAND_TO_STRENGTH: dict[str, LevelStrength] = {
    "very_strong": "strong",
    "strong": "strong",
    "medium": "medium",
    "neutral_low": "medium",
    "weak": "weak",
}


def _collect_candidates(snap: FeatureSnapshot, source_weights: dict[str, float]) -> list[LevelCandidate]:
    """把所有价位原子转成 (price, side, source) 的扁平候选列表。"""
    price = snap.last_price
    cands: list[LevelCandidate] = []

    # HVN
    for h in snap.hvn_nodes:
        side = "support" if h.price < price else "resistance"
        cands.append(
            LevelCandidate(
                price=h.price, side=side,
                sources=[LevelSource(kind="hvn", weight=float(source_weights.get("hvn", 40)), value=h.rank)],
            )
        )

    # Absolute zones —— 用 zone 中点
    for z in snap.absolute_zones:
        mid = (z.top_price + z.bottom_price) / 2
        side = "support" if mid < price else "resistance"
        cands.append(
            LevelCandidate(
                price=mid, side=side, top=z.top_price, bottom=z.bottom_price,
                sources=[LevelSource(kind="absolute_zone", weight=float(source_weights.get("absolute_zone", 20)), value=z.type)],
            )
        )

    # Order blocks (trend_price / ob_decay 都存这里)
    for ob in snap.order_blocks:
        side = "support" if ob.avg_price < price else "resistance"
        cands.append(
            LevelCandidate(
                price=ob.avg_price, side=side,
                sources=[LevelSource(kind="trend_price", weight=float(source_weights.get("trend_price", 10)), value=ob.type)],
            )
        )

    # Micro POC
    for mp in snap.micro_pocs:
        side = "support" if mp.poc_price < price else "resistance"
        cands.append(
            LevelCandidate(
                price=mp.poc_price, side=side,
                sources=[LevelSource(kind="micro_poc", weight=float(source_weights.get("micro_poc", 15)), value=mp.type)],
            )
        )

    # Smart money ongoing
    if snap.smart_money_ongoing:
        p = snap.smart_money_ongoing.avg_price
        side = "support" if p < price else "resistance"
        cands.append(
            LevelCandidate(
                price=p, side=side,
                sources=[LevelSource(kind="smart_money", weight=float(source_weights.get("smart_money", 10)), value=snap.smart_money_ongoing.type)],
            )
        )

    # Trailing VWAP —— support/resistance 分别一条
    if snap.trailing_vwap_last:
        tv = snap.trailing_vwap_last
        if tv.support is not None:
            cands.append(
                LevelCandidate(
                    price=tv.support, side="support",
                    sources=[LevelSource(kind="trailing_vwap", weight=float(source_weights.get("trailing_vwap", 10)))],
                )
            )
        if tv.resistance is not None:
            cands.append(
                LevelCandidate(
                    price=tv.resistance, side="resistance",
                    sources=[LevelSource(kind="trailing_vwap", weight=float(source_weights.get("trailing_vwap", 10)))],
                )
            )

    # Heatmap bands（清算带）
    for hb in snap.heatmap:
        side = "support" if hb.price < price else "resistance"
        cands.append(
            LevelCandidate(
                price=hb.price, side=side,
                sources=[LevelSource(kind="heatmap", weight=float(source_weights.get("heatmap", 20)), value=round(hb.intensity, 2))],
            )
        )

    # Vacuums 当 FVG 代理（使用上下沿）
    for v in snap.vacuums:
        for p in (v.low, v.high):
            side = "support" if p < price else "resistance"
            cands.append(
                LevelCandidate(
                    price=p, side=side, bottom=v.low, top=v.high,
                    sources=[LevelSource(kind="fvg", weight=float(source_weights.get("fvg", 15)))],
                )
            )

    return cands


def _merge_candidates(
    cands: list[LevelCandidate], merge_pct: float
) -> list[LevelCandidate]:
    """同 side 内按 merge_pct 聚合（依价位排序，距离 < merge_pct 的合并来源）。"""
    out: list[LevelCandidate] = []
    for side in ("support", "resistance"):
        side_cands = sorted([c for c in cands if c.side == side], key=lambda c: c.price)
        merged: list[LevelCandidate] = []
        for c in side_cands:
            if merged:
                last = merged[-1]
                if last.price > 0 and abs(c.price - last.price) / last.price <= merge_pct:
                    # 合并：来源追加，price 取加权平均
                    total_w = sum(s.weight for s in last.sources) + sum(s.weight for s in c.sources)
                    if total_w > 0:
                        last.price = round(
                            (last.price * sum(s.weight for s in last.sources)
                             + c.price * sum(s.weight for s in c.sources)) / total_w,
                            6,
                        )
                    last.sources.extend(c.sources)
                    continue
            merged.append(c)
        out.extend(merged)
    return out


def _fit_from(strength: LevelStrength, test_count: int) -> LevelFit:
    if test_count >= 4:
        return "worn_out"
    if strength == "strong" and test_count == 1:
        return "first_test_good"
    if strength == "weak":
        return "can_break"
    return "observe"


def build_key_levels(
    snap: FeatureSnapshot, cfg: dict[str, Any] | None = None
) -> LevelLadder:
    merge_pct = float(cfg_path(cfg, "key_levels.merge_distance_pct", 0.003))
    min_spacing = float(cfg_path(cfg, "key_levels.min_spacing_pct", 0.005))
    r_n = int(cfg_path(cfg, "key_levels.r_levels", 3))
    s_n = int(cfg_path(cfg, "key_levels.s_levels", 3))
    min_sources = int(cfg_path(cfg, "key_levels.min_sources_for_show", 1))
    source_weights = cfg_path(cfg, "capabilities.key_level_strength.source_weights", {}) or {}

    cands = _collect_candidates(snap, source_weights)
    merged = _merge_candidates(cands, merge_pct)

    # 打分 + 过滤
    scored: list[tuple[LevelCandidate, Any]] = []
    for c in merged:
        if len(c.sources) < min_sources:
            continue
        res = score_level(c, snap, cfg, test_count=1, state="first_test")
        scored.append((c, res))

    price = snap.last_price
    resistances = sorted([s for s in scored if s[0].side == "resistance"], key=lambda s: s[0].price)
    supports = sorted([s for s in scored if s[0].side == "support"], key=lambda s: -s[0].price)

    def _pick_ladder(levels: list[tuple[LevelCandidate, Any]], n: int) -> list[Level]:
        picked: list[Level] = []
        last_price: float | None = None
        for cand, res in levels:
            # 间距检查
            if last_price is not None and last_price > 0:
                if abs(cand.price - last_price) / last_price < min_spacing:
                    continue
            strength: LevelStrength = _BAND_TO_STRENGTH.get(res.band, "weak")
            src_names = [s.kind for s in cand.sources]
            picked.append(
                Level(
                    price=round(cand.price, 6),
                    sources=src_names,
                    strength=strength,
                    test_count=1,
                    decay_pct=0.0,
                    fit=_fit_from(strength, 1),
                    score=int(round(res.score)),
                )
            )
            last_price = cand.price
            if len(picked) >= n:
                break
        return picked

    r_levels = _pick_ladder(resistances, r_n)
    s_levels = _pick_ladder(supports, s_n)

    # R3/R2/R1 从远到近（r_levels 是从近到远，倒序映射到 R1..R3）
    ladder = LevelLadder(
        current_price=price,
        r1=r_levels[0] if len(r_levels) >= 1 else None,
        r2=r_levels[1] if len(r_levels) >= 2 else None,
        r3=r_levels[2] if len(r_levels) >= 3 else None,
        s1=s_levels[0] if len(s_levels) >= 1 else None,
        s2=s_levels[1] if len(s_levels) >= 2 else None,
        s3=s_levels[2] if len(s_levels) >= 3 else None,
    )
    return ladder


__all__ = ["build_key_levels"]
