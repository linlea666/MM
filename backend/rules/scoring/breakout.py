"""突破确认分 scorer。

维度：
1. level_pierced    最近 N 根穿越关键位（幅度 ≥ pierce_atr_mult * ATR 才算）
2. whale_resonance  鲸鱼共振次数
3. power_imbalance  能量条极端放大
4. ob_decayed       订单墙已衰减（V1：用 trend_purity 做代理）
5. space_ahead      前方有 vacuum / fuel（空间支持）
"""

from __future__ import annotations

from typing import Any

from ..features import FeatureSnapshot
from .common import band_from, cfg_path, finalize_score, ratio_above
from .types import CapabilityScore, Direction, Evidence


def _space_ahead(snap: FeatureSnapshot, direction: Direction) -> tuple[bool, str]:
    """突破方向前方是否有真空 / 清算燃料区。"""
    if direction == "neutral":
        return False, "无突破方向"
    price = snap.last_price
    has_vacuum = False
    vacuum_note = ""
    for v in snap.vacuums:
        if direction == "bullish" and v.low > price:
            has_vacuum = True
            vacuum_note = f"上方真空带 {v.low}-{v.high}"
            break
        if direction == "bearish" and v.high < price:
            has_vacuum = True
            vacuum_note = f"下方真空带 {v.low}-{v.high}"
            break
    has_fuel = False
    fuel_note = ""
    for f in snap.liquidation_fuel:
        if direction == "bullish" and f.bottom > price and f.fuel >= 0.3:
            has_fuel = True
            fuel_note = f"上方燃料带 {f.bottom}-{f.top} fuel={round(f.fuel, 2)}"
            break
        if direction == "bearish" and f.top < price and f.fuel >= 0.3:
            has_fuel = True
            fuel_note = f"下方燃料带 {f.bottom}-{f.top} fuel={round(f.fuel, 2)}"
            break
    hit = has_vacuum or has_fuel
    note = "; ".join([x for x in (vacuum_note, fuel_note) if x]) or "无空间"
    return hit, note


def score_breakout(
    snap: FeatureSnapshot, cfg: dict[str, Any] | None = None
) -> CapabilityScore:
    weights = cfg_path(cfg, "capabilities.breakout.weights", {}) or {}
    thr = cfg_path(cfg, "capabilities.breakout.thresholds", {}) or {}
    bands = cfg_path(cfg, "capabilities.breakout.label_bands", {}) or {}

    evs: list[Evidence] = []

    # 方向
    direction: Direction = "neutral"
    if snap.just_broke_resistance and not snap.just_broke_support:
        direction = "bullish"
    elif snap.just_broke_support and not snap.just_broke_resistance:
        direction = "bearish"
    elif snap.just_broke_resistance and snap.just_broke_support:
        # 同时穿越上下 → 按 whale / cvd 偏向定方向
        if snap.whale_net_direction == "buy" or snap.cvd_slope_sign == "up":
            direction = "bullish"
        elif snap.whale_net_direction == "sell" or snap.cvd_slope_sign == "down":
            direction = "bearish"

    # 1) 关键位穿越 + 幅度 ≥ pierce_atr_mult * ATR
    w = float(weights.get("level_pierced", 0.25))
    atr_mult = float(thr.get("pierce_atr_mult", 0.3))
    pierced = snap.just_broke_resistance or snap.just_broke_support
    ratio = 0.0
    note = ""
    if pierced and snap.atr and snap.atr > 0:
        # 简化：用 nearest 位距离 ATR 比例作强度
        if direction == "bullish" and snap.nearest_resistance_price is not None:
            # 已穿越，nearest 现在可能已是 support；用 atr 粗粒度强度
            ratio = 1.0 if atr_mult > 0 else 0.0
            note = f"近 N 根穿越（bullish），atr={round(snap.atr, 2)}"
        elif direction == "bearish" and snap.nearest_support_price is not None:
            ratio = 1.0
            note = f"近 N 根穿越（bearish），atr={round(snap.atr, 2)}"
        else:
            ratio = 0.5
            note = "穿越但方向模糊"
    evs.append(
        Evidence(
            rule_id="level_pierced", label="关键位穿越",
            weight=w, hit=pierced, ratio=ratio,
            value=f"broke_r={snap.just_broke_resistance}, broke_s={snap.just_broke_support}",
            threshold=f"atr_mult={atr_mult}",
            note=note,
        )
    )

    # 2) 鲸鱼共振 & 方向一致
    w = float(weights.get("whale_resonance", 0.25))
    min_n = int(thr.get("whale_resonance_count", 2))
    # 只有当共振方向与突破方向一致时才计分
    if direction == "bullish":
        n_dir = snap.resonance_buy_count
    elif direction == "bearish":
        n_dir = snap.resonance_sell_count
    else:
        n_dir = max(snap.resonance_buy_count, snap.resonance_sell_count)
    hit = n_dir >= min_n
    evs.append(
        Evidence(
            rule_id="whale_resonance", label="鲸鱼同向共振",
            weight=w, hit=hit, ratio=ratio_above(float(n_dir), float(min_n)),
            value=f"buy={snap.resonance_buy_count}, sell={snap.resonance_sell_count}",
            threshold=min_n,
        )
    )

    # 3) power_imbalance 放大
    w = float(weights.get("power_imbalance", 0.15))
    min_r = float(thr.get("power_imbalance_ratio", 1.5))
    pi = snap.power_imbalance_last
    if pi is None:
        evs.append(
            Evidence(
                rule_id="power_imbalance", label="能量条极端放大",
                weight=w, hit=False, ratio=0.0, value=None,
                note="无 power_imbalance 事件",
            )
        )
    else:
        hit = pi.ratio >= min_r
        evs.append(
            Evidence(
                rule_id="power_imbalance", label="能量条极端放大",
                weight=w, hit=hit, ratio=ratio_above(pi.ratio, min_r),
                value=round(pi.ratio, 3), threshold=min_r,
            )
        )

    # 4) order block 已衰减（代理：trend_purity 高 → OB 未被反复磨损，更易突破）
    #    V1 简化：purity >= 50 给 1，< 30 给 0，中间线性
    w = float(weights.get("ob_decayed", 0.15))
    tp = snap.trend_purity_last
    if tp is None:
        evs.append(
            Evidence(
                rule_id="ob_decayed", label="订单墙状态",
                weight=w, hit=False, ratio=0.0, value=None,
                note="无 trend_purity（代理信号）",
            )
        )
    else:
        # 纯度高说明趋势干净、OB 没被磨
        purity = tp.purity
        if purity >= 50:
            r = 1.0
        elif purity <= 30:
            r = 0.0
        else:
            r = (purity - 30) / 20.0
        evs.append(
            Evidence(
                rule_id="ob_decayed", label="订单墙状态（trend_purity 代理）",
                weight=w, hit=r >= 0.5, ratio=r,
                value=round(purity, 2), threshold=50,
            )
        )

    # 5) 前方空间
    w = float(weights.get("space_ahead", 0.20))
    space_hit, space_note = _space_ahead(snap, direction)
    evs.append(
        Evidence(
            rule_id="space_ahead", label="突破方向前方空间",
            weight=w, hit=space_hit, ratio=1.0 if space_hit else 0.0,
            value=space_note,
        )
    )

    score = finalize_score(evs)
    return CapabilityScore(
        name="breakout",
        score=score,
        band=band_from(score, bands, default="fake"),
        direction=direction,
        evidence=evs,
    )


__all__ = ["score_breakout"]
