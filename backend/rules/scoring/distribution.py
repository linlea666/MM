"""空头派发分 scorer（与 accumulation 对称）。"""

from __future__ import annotations

from typing import Any

from ..features import FeatureSnapshot
from .common import band_from, cfg_path, clamp01, finalize_score, ratio_above
from .types import CapabilityScore, Evidence


def score_distribution(
    snap: FeatureSnapshot, cfg: dict[str, Any] | None = None
) -> CapabilityScore:
    weights = cfg_path(cfg, "capabilities.distribution.weights", {}) or {}
    thr = cfg_path(cfg, "capabilities.distribution.thresholds", {}) or {}
    bands = cfg_path(cfg, "capabilities.distribution.label_bands", {}) or {}
    near_pct = float(cfg_path(cfg, "global.near_price_pct", 0.006))
    slope_eps = float(thr.get("slope_epsilon", 0.0))

    evs: list[Evidence] = []

    # 1) fair_value 下行
    fv_slope = snap.vwap_slope
    w = float(weights.get("fair_value_slope", 0.20))
    if fv_slope is None:
        evs.append(
            Evidence(
                rule_id="fair_value_slope", label="真实价值下行斜率",
                weight=w, hit=False, ratio=0.0, value=None,
                note="vwap 序列缺失",
            )
        )
    else:
        neg = -fv_slope
        hit = neg > slope_eps
        r = clamp01(neg * 100) if hit else 0.0
        evs.append(
            Evidence(
                rule_id="fair_value_slope", label="真实价值下行斜率",
                weight=w, hit=hit, ratio=r,
                value=round(fv_slope * 100, 3), threshold=slope_eps,
            )
        )

    # 2) POC 重心下移
    w = float(weights.get("poc_shift_down", 0.20))
    min_pct = float(thr.get("poc_shift_min_pct", 0.002))
    delta = snap.poc_shift_delta_pct
    if delta is None or snap.poc_shift_trend == "flat":
        evs.append(
            Evidence(
                rule_id="poc_shift_down", label="POC 重心下移",
                weight=w, hit=False, ratio=0.0, value=delta,
                note="poc_shift 序列缺失或无方向",
            )
        )
    else:
        hit = snap.poc_shift_trend == "down" and delta <= -min_pct
        # 越负越强
        neg = -delta if delta is not None else 0.0
        r = ratio_above(neg if neg > 0 else 0.0, min_pct * 2)
        evs.append(
            Evidence(
                rule_id="poc_shift_down", label="POC 重心下移",
                weight=w, hit=hit, ratio=r if hit else 0.0,
                value=round(delta * 100, 3), threshold=-round(min_pct * 100, 3),
            )
        )

    # 3) imbalance 红占比
    w = float(weights.get("imbalance_red", 0.15))
    red_th = float(thr.get("imbalance_red_ratio", 0.6))
    rr = snap.imbalance_red_ratio
    hit = rr >= red_th
    evs.append(
        Evidence(
            rule_id="imbalance_red", label="卖方能量条占比",
            weight=w, hit=hit, ratio=ratio_above(rr, red_th),
            value=round(rr, 3), threshold=red_th,
        )
    )

    # 4) CVD 斜率为负
    w = float(weights.get("cvd_slope_down", 0.15))
    hit = snap.cvd_slope_sign == "down"
    evs.append(
        Evidence(
            rule_id="cvd_slope_down", label="CVD 累积下降",
            weight=w, hit=hit, ratio=1.0 if hit else 0.0,
            value=snap.cvd_slope, threshold=0.0,
        )
    )

    # 5) 价格贴近阻力
    w = float(weights.get("near_resistance", 0.15))
    dist = snap.nearest_resistance_distance_pct
    if dist is None:
        evs.append(
            Evidence(
                rule_id="near_resistance", label="贴近阻力",
                weight=w, hit=False, ratio=0.0, value=None,
                note="无候选阻力位",
            )
        )
    else:
        hit = dist <= near_pct
        r = clamp01((near_pct - dist) / near_pct) if dist >= 0 else 0.0
        evs.append(
            Evidence(
                rule_id="near_resistance", label="贴近阻力",
                weight=w, hit=hit, ratio=r,
                value=round(dist * 100, 3),
                threshold=round(near_pct * 100, 3),
            )
        )

    # 6) 共振卖方向
    w = float(weights.get("resonance_sell", 0.15))
    min_n = int(thr.get("resonance_min_count", 2))
    buy_n = snap.resonance_buy_count
    sell_n = snap.resonance_sell_count
    net_sell = max(sell_n - buy_n, 0)
    hit = sell_n >= min_n and net_sell >= 1
    r = ratio_above(float(net_sell), float(min_n))
    evs.append(
        Evidence(
            rule_id="resonance_sell", label="共振卖方向",
            weight=w, hit=hit, ratio=r,
            value=f"buy={buy_n}, sell={sell_n}",
            threshold=min_n,
        )
    )

    score = finalize_score(evs)
    return CapabilityScore(
        name="distribution",
        score=score,
        band=band_from(score, bands, default="weak"),
        direction="bearish",
        evidence=evs,
    )


__all__ = ["score_distribution"]
