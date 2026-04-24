"""反转概率分 scorer。

维度：
1. sweep_recent       最近 N 根 sweep 事件
2. exhaustion_high    trend_exhaustion 达到警戒
3. fair_value_diverge 价格与真实价值显著偏离
4. liq_pierce_recover 刺穿清算带后回到带内（V1：sweep + exhaustion 组合近似）
"""

from __future__ import annotations

from typing import Any

from ..features import FeatureSnapshot
from .common import band_from, cfg_path, finalize_score, ratio_above
from .types import CapabilityScore, Direction, Evidence


def score_reversal(
    snap: FeatureSnapshot, cfg: dict[str, Any] | None = None
) -> CapabilityScore:
    weights = cfg_path(cfg, "capabilities.reversal.weights", {}) or {}
    thr = cfg_path(cfg, "capabilities.reversal.thresholds", {}) or {}
    bands = cfg_path(cfg, "capabilities.reversal.label_bands", {}) or {}

    evs: list[Evidence] = []

    # 1) 最近 sweep
    w = float(weights.get("sweep_recent", 0.30))
    n = snap.sweep_count_recent
    hit = n >= 1
    evs.append(
        Evidence(
            rule_id="sweep_recent", label="最近猎杀事件",
            weight=w, hit=hit, ratio=ratio_above(float(n), 2.0),
            value=n, threshold=1,
        )
    )

    # 2) 耗竭高位
    w = float(weights.get("exhaustion_high", 0.25))
    alert = int(thr.get("exhaustion_alert", 5))
    te = snap.trend_exhaustion_last
    if te is None:
        evs.append(
            Evidence(
                rule_id="exhaustion_high", label="趋势耗竭警戒",
                weight=w, hit=False, ratio=0.0, value=None,
                note="无 trend_exhaustion 事件",
            )
        )
    else:
        hit_ex = te.exhaustion >= alert
        evs.append(
            Evidence(
                rule_id="exhaustion_high", label="趋势耗竭警戒",
                weight=w, hit=hit_ex, ratio=ratio_above(float(te.exhaustion), float(alert)),
                value=f"ex={te.exhaustion} type={te.type}", threshold=alert,
            )
        )

    # 3) fair_value 偏离
    w = float(weights.get("fair_value_diverge", 0.20))
    d_th = float(thr.get("fair_value_diverge_pct", 0.01))
    fv_delta = snap.fair_value_delta_pct
    if fv_delta is None:
        evs.append(
            Evidence(
                rule_id="fair_value_diverge", label="真实价值偏离",
                weight=w, hit=False, ratio=0.0, value=None,
                note="vwap 缺失",
            )
        )
    else:
        abs_delta = abs(fv_delta)
        hit_fv = abs_delta >= d_th
        evs.append(
            Evidence(
                rule_id="fair_value_diverge", label="真实价值偏离",
                weight=w, hit=hit_fv, ratio=ratio_above(abs_delta, d_th * 2),
                value=round(fv_delta * 100, 3), threshold=round(d_th * 100, 3),
                note="|price - vwap| / vwap（越大越背离）",
            )
        )

    # 4) liq 刺穿 + 回收（近似：sweep_last 类型与 nearest_level 同向 + 最近已穿越）
    w = float(weights.get("liq_pierce_recover", 0.25))
    r = 0.0
    note = ""
    hit_lr = False
    if snap.sweep_last is not None:
        # HFD 约定（backend/models.py）：
        #   bullish_sweep = 扫下方多头止损后上行 → 下刺穿 + 收回 → 看涨反转
        #   bearish_sweep = 扫上方空头止损后下行 → 上刺穿 + 收回 → 看跌反转
        if snap.sweep_last.type == "bearish_sweep" and snap.just_broke_resistance:
            hit_lr = True
            r = 1.0
            note = "上方猎杀 + 刺穿阻力（回收待确认）"
        elif snap.sweep_last.type == "bullish_sweep" and snap.just_broke_support:
            hit_lr = True
            r = 1.0
            note = "下方猎杀 + 刺穿支撑（回收待确认）"
    evs.append(
        Evidence(
            rule_id="liq_pierce_recover", label="刺穿清算带后回收",
            weight=w, hit=hit_lr, ratio=r,
            value=snap.sweep_last.type if snap.sweep_last else None,
            note=note or "无猎杀/穿越组合",
        )
    )

    # 反转方向推断
    direction: Direction = "neutral"
    if te is not None and te.type.lower().startswith(("dist",)):
        direction = "bearish"   # 派发耗竭 → 反转下行
    elif te is not None and te.type.lower().startswith(("accum",)):
        direction = "bullish"   # 吸筹耗竭 → 反转上行
    # fair_value 强力背离也能反推
    if fv_delta is not None:
        if fv_delta > 0 and direction == "neutral":
            direction = "bearish"   # 价格高于真实价值 → 回归下行
        elif fv_delta < 0 and direction == "neutral":
            direction = "bullish"

    score = finalize_score(evs)
    return CapabilityScore(
        name="reversal",
        score=score,
        band=band_from(score, bands, default="medium"),
        direction=direction,
        evidence=evs,
    )


__all__ = ["score_reversal"]
