"""多头吸筹分 scorer。

对应 rules.default.yaml → capabilities.accumulation
输入：FeatureSnapshot + rules_defaults（merged）
输出：CapabilityScore
"""

from __future__ import annotations

from typing import Any

from ..features import FeatureSnapshot
from .common import band_from, cfg_path, clamp01, finalize_score, ratio_above
from .types import CapabilityScore, Evidence


def score_accumulation(
    snap: FeatureSnapshot, cfg: dict[str, Any] | None = None
) -> CapabilityScore:
    weights = cfg_path(cfg, "capabilities.accumulation.weights", {}) or {}
    thr = cfg_path(cfg, "capabilities.accumulation.thresholds", {}) or {}
    bands = cfg_path(cfg, "capabilities.accumulation.label_bands", {}) or {}
    near_pct = float(cfg_path(cfg, "global.near_price_pct", 0.006))
    slope_eps = float(thr.get("slope_epsilon", 0.0))

    evs: list[Evidence] = []

    # 1) fair_value (vwap) 上行斜率
    fv_slope = snap.vwap_slope
    w = float(weights.get("fair_value_slope", 0.20))
    if fv_slope is None:
        evs.append(
            Evidence(
                rule_id="fair_value_slope",
                label="真实价值上行斜率",
                weight=w, hit=False, ratio=0.0, value=None,
                note="vwap 序列缺失",
            )
        )
    else:
        hit = fv_slope > slope_eps
        # >=1% 给满分
        r = clamp01(fv_slope * 100) if hit else 0.0
        evs.append(
            Evidence(
                rule_id="fair_value_slope",
                label="真实价值上行斜率",
                weight=w, hit=hit, ratio=r,
                value=round(fv_slope * 100, 3),
                threshold=slope_eps,
                note="结构窗 lookback_bars 内 vwap 百分比斜率",
            )
        )

    # 2) POC 重心上移
    w = float(weights.get("poc_shift_up", 0.20))
    min_pct = float(thr.get("poc_shift_min_pct", 0.002))
    delta = snap.poc_shift_delta_pct
    if delta is None or snap.poc_shift_trend == "flat":
        evs.append(
            Evidence(
                rule_id="poc_shift_up", label="POC 重心上移",
                weight=w, hit=False, ratio=0.0, value=delta,
                note="poc_shift 序列缺失或无方向",
            )
        )
    else:
        hit = snap.poc_shift_trend == "up" and delta >= min_pct
        r = ratio_above(delta if delta > 0 else 0.0, min_pct * 2)  # 2x threshold → 满分
        evs.append(
            Evidence(
                rule_id="poc_shift_up", label="POC 重心上移",
                weight=w, hit=hit, ratio=r if hit else 0.0,
                value=round(delta * 100, 3), threshold=round(min_pct * 100, 3),
                note="累计 POC 上移百分比",
            )
        )

    # 3) imbalance 绿占比
    w = float(weights.get("imbalance_green", 0.15))
    green_th = float(thr.get("imbalance_green_ratio", 0.6))
    gr = snap.imbalance_green_ratio
    hit = gr >= green_th
    evs.append(
        Evidence(
            rule_id="imbalance_green", label="买方能量条占比",
            weight=w, hit=hit, ratio=ratio_above(gr, green_th),
            value=round(gr, 3), threshold=green_th,
        )
    )

    # 4) CVD 斜率为正
    w = float(weights.get("cvd_slope_up", 0.15))
    cvd = snap.cvd_slope
    hit = snap.cvd_slope_sign == "up"
    evs.append(
        Evidence(
            rule_id="cvd_slope_up", label="CVD 累积上升",
            weight=w, hit=hit, ratio=1.0 if hit else 0.0,
            value=cvd, threshold=0.0,
        )
    )

    # 5) 价格贴近支撑
    w = float(weights.get("near_support", 0.15))
    dist = snap.nearest_support_distance_pct
    if dist is None:
        evs.append(
            Evidence(
                rule_id="near_support", label="贴近支撑",
                weight=w, hit=False, ratio=0.0, value=None,
                note="无候选支撑位",
            )
        )
    else:
        hit = dist <= near_pct
        # 越近越强：0 → 1，near_pct → 0
        r = clamp01((near_pct - dist) / near_pct) if dist >= 0 else 0.0
        evs.append(
            Evidence(
                rule_id="near_support", label="贴近支撑",
                weight=w, hit=hit, ratio=r,
                value=round(dist * 100, 3),
                threshold=round(near_pct * 100, 3),
                note="距最近支撑百分比",
            )
        )

    # 6) 共振买方向
    w = float(weights.get("resonance_buy", 0.15))
    min_n = int(thr.get("resonance_min_count", 2))
    buy_n = snap.resonance_buy_count
    sell_n = snap.resonance_sell_count
    # 净多买数量
    net_buy = max(buy_n - sell_n, 0)
    hit = buy_n >= min_n and net_buy >= 1
    r = ratio_above(float(net_buy), float(min_n))
    evs.append(
        Evidence(
            rule_id="resonance_buy", label="共振买方向",
            weight=w, hit=hit, ratio=r,
            value=f"buy={buy_n}, sell={sell_n}",
            threshold=min_n,
        )
    )

    score = finalize_score(evs)
    return CapabilityScore(
        name="accumulation",
        score=score,
        band=band_from(score, bands, default="weak"),
        direction="bullish",
        evidence=evs,
    )


__all__ = ["score_accumulation"]
