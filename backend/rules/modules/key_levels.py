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

    # V1.1 · 💣 爆仓带（cascade_liquidation）—— 雷区插针反向接针 战法
    # docs/upstream-api/endpoints/cascade_liquidation.md：
    #   long_fuel（下方红带）= 多头爆仓燃料 → 支撑位
    #   short_fuel（上方绿带）= 空头爆仓燃料 → 阻力位
    for b in snap.cascade_bands:
        p = b.avg_price
        side = "support" if p < price else "resistance"
        cands.append(
            LevelCandidate(
                price=p, side=side, bottom=b.bottom_price, top=b.top_price,
                sources=[LevelSource(
                    kind="cascade_band",
                    weight=float(source_weights.get("cascade_band", 25)),
                    value=f"signal_count={b.signal_count}",
                )],
            )
        )

    # V1.1 · 散户止损带（retail_stop_loss）—— 磁吸方向 / 破位追单 战法
    for b in snap.retail_stop_bands:
        p = b.avg_price
        side = "support" if p < price else "resistance"
        cands.append(
            LevelCandidate(
                price=p, side=side, bottom=b.bottom_price, top=b.top_price,
                sources=[LevelSource(
                    kind="retail_band",
                    weight=float(source_weights.get("retail_band", 15)),
                    value=f"volume={round(b.volume, 2)}",
                )],
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


def _to_level(cand: LevelCandidate, res: Any) -> Level:
    strength: LevelStrength = _BAND_TO_STRENGTH.get(res.band, "weak")
    return Level(
        price=round(cand.price, 6),
        sources=[s.kind for s in cand.sources],
        strength=strength,
        test_count=1,
        decay_pct=0.0,
        fit=_fit_from(strength, 1),
        score=int(round(res.score)),
    )


def build_key_levels(
    snap: FeatureSnapshot, cfg: dict[str, Any] | None = None
) -> LevelLadder:
    merge_pct = float(cfg_path(cfg, "key_levels.merge_distance_pct", 0.003))
    min_spacing = float(cfg_path(cfg, "key_levels.min_spacing_pct", 0.005))
    r_n = int(cfg_path(cfg, "key_levels.r_levels", 3))
    s_n = int(cfg_path(cfg, "key_levels.s_levels", 3))
    min_sources = int(cfg_path(cfg, "key_levels.min_sources_for_show", 1))
    source_weights = cfg_path(cfg, "capabilities.key_level_strength.source_weights", {}) or {}

    # V1.1 · 远距参数（默认 1% ~ 8%，每侧最多 8 条）
    far_min = float(cfg_path(cfg, "key_levels.far_range_pct_min", 0.01))
    far_max = float(cfg_path(cfg, "key_levels.far_range_pct_max", 0.08))
    max_far = int(cfg_path(cfg, "key_levels.max_far_count", 8))

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
    # resistance 由下到上（价格小→大）；support 由上到下（价格大→小），等价于"距当前价由近→远"
    resistances = sorted([s for s in scored if s[0].side == "resistance"], key=lambda s: s[0].price)
    supports = sorted([s for s in scored if s[0].side == "support"], key=lambda s: -s[0].price)

    def _pick_ladder(
        levels: list[tuple[LevelCandidate, Any]], n: int
    ) -> tuple[list[Level], set[int]]:
        """返回 (阶梯 Level 列表, 已占位的候选索引集合)。"""
        picked: list[Level] = []
        used: set[int] = set()
        last_price: float | None = None
        for idx, (cand, res) in enumerate(levels):
            if last_price is not None and last_price > 0:
                if abs(cand.price - last_price) / last_price < min_spacing:
                    continue
            picked.append(_to_level(cand, res))
            used.add(idx)
            last_price = cand.price
            if len(picked) >= n:
                break
        return picked, used

    def _pick_far(
        levels: list[tuple[LevelCandidate, Any]], used: set[int]
    ) -> list[Level]:
        """从候选中挑 `远距`（far_min ≤ distance_pct ≤ far_max）且未被阶梯占用的 level。

        保持按距当前价由近→远的顺序（levels 已按该序排好），
        不再做 min_spacing 过滤（远距允许更密），最多 ``max_far`` 条；
        ``max_far ≤ 0`` 时直接返回空（等价于"关闭远距展示"）。
        """
        if max_far <= 0 or price <= 0:
            return []
        out: list[Level] = []
        for idx, (cand, res) in enumerate(levels):
            if idx in used:
                continue
            dist_pct = abs(cand.price - price) / price
            if dist_pct < far_min or dist_pct > far_max:
                continue
            out.append(_to_level(cand, res))
            if len(out) >= max_far:
                break
        return out

    r_levels, r_used = _pick_ladder(resistances, r_n)
    s_levels, s_used = _pick_ladder(supports, s_n)

    far_above = _pick_far(resistances, r_used)
    far_below = _pick_far(supports, s_used)

    ladder = LevelLadder(
        current_price=price,
        r1=r_levels[0] if len(r_levels) >= 1 else None,
        r2=r_levels[1] if len(r_levels) >= 2 else None,
        r3=r_levels[2] if len(r_levels) >= 3 else None,
        s1=s_levels[0] if len(s_levels) >= 1 else None,
        s2=s_levels[1] if len(s_levels) >= 2 else None,
        s3=s_levels[2] if len(s_levels) >= 3 else None,
        far_above=far_above,
        far_below=far_below,
    )
    return ladder


__all__ = ["build_key_levels"]
