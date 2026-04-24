"""突破确认分 scorer。

维度：
1. level_pierced    事件窗 ``recent_window_bars`` 内穿越关键位（幅度 ≥ ``pierce_atr_mult`` × ATR 才算真突破）
2. whale_resonance  鲸鱼共振次数（事件窗内同向计数）
3. power_imbalance  能量条连续放大（官方"连续 3 根"口径，详见 power_imbalance.md）
4. ob_decayed       订单墙已衰减（V1：用 trend_purity 做代理，阈值见 ``ob_decay_threshold``）
5. space_ahead      前方有 vacuum / fuel（空间支持）
6. bos_confirm      V1.1：⚡ 机构 BOS 结构延续事件（docs：inst_choch 右侧确认）
                    —— 默认 weight=0（保守修改：现有配置不受影响）。
                    启用时请同比减小其他维度权重，使总权重 = 1.0。
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
    # —— pierce_atr_ratio = 本次穿越幅度 / ATR（特征层已算好）。
    # ratio = pierce_atr_ratio / (pierce_atr_mult * 2)，在 atr_mult 位置得 0.5 分，
    # 2 * atr_mult 位置得满分；<atr_mult 视为擦线。
    w = float(weights.get("level_pierced", 0.25))
    atr_mult = float(thr.get("pierce_atr_mult", 0.3))
    pierced = snap.just_broke_resistance or snap.just_broke_support
    ratio = 0.0
    note = ""
    if pierced and snap.pierce_atr_ratio is not None and atr_mult > 0:
        target = 2.0 * atr_mult
        ratio = max(0.0, min(1.0, snap.pierce_atr_ratio / target))
        # 未达到 atr_mult 视为擦线 → hit=False（ratio 可能仍 >0，但 hit 收紧）
        passed = snap.pierce_atr_ratio >= atr_mult
        note = (
            f"pierce/ATR={round(snap.pierce_atr_ratio, 3)}"
            f"（阈 {atr_mult}）{'通过' if passed else '擦线'}"
        )
        hit_pierce = passed
    elif pierced:
        # ATR 缺失或 atr_mult=0：退化为布尔穿越，给 0.5
        ratio = 0.5
        note = "穿越但 ATR 缺失，无法验证幅度"
        hit_pierce = True
    else:
        hit_pierce = False
    evs.append(
        Evidence(
            rule_id="level_pierced", label="关键位穿越",
            weight=w, hit=hit_pierce, ratio=ratio,
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
    # 官方口径（docs/upstream-api/endpoints/power_imbalance.md §大屏使用）：
    #   连续 3 根 ratio > 3 且同向 → "逼空/逼多" → 真突破力量确认
    # 所以评分分两档：
    #   streak ≥ 3 且同突破方向 → 满分
    #   仅最新一根 ratio ≥ min_r → 中分
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
        aligned = (
            (direction == "bullish" and snap.power_imbalance_streak_side == "buy")
            or (direction == "bearish" and snap.power_imbalance_streak_side == "sell")
            or direction == "neutral"
        )
        if snap.power_imbalance_streak >= 3 and aligned:
            r = 1.0
            hit = True
            note = f"连续 {snap.power_imbalance_streak} 根 ratio≥阈，side={snap.power_imbalance_streak_side}"
        else:
            r = ratio_above(pi.ratio, min_r)
            hit = pi.ratio >= min_r
            note = f"streak={snap.power_imbalance_streak} side={snap.power_imbalance_streak_side}"
        evs.append(
            Evidence(
                rule_id="power_imbalance", label="能量条极端放大",
                weight=w, hit=hit, ratio=r,
                value=round(pi.ratio, 3), threshold=min_r,
                note=note,
            )
        )

    # 4) order block 已衰减（代理：trend_purity 高 → OB 未被反复磨损，更易突破）
    # yaml 里 ob_decay_threshold 原意是 "OB 剩余可用度 < (1-threshold) 视为已衰减"，
    # 默认 0.6 → 纯度 ≥ 60 判未衰减。这里把 ob_decay_threshold × 100 作为 purity 满分线，
    # 0 作为零分线，线性映射；hit=ratio ≥ 0.5。
    w = float(weights.get("ob_decayed", 0.15))
    ob_threshold = float(thr.get("ob_decay_threshold", 0.6))
    purity_full = max(1.0, ob_threshold * 100.0)  # 避免 threshold=0 除零
    tp = snap.trend_purity_last
    if tp is None:
        evs.append(
            Evidence(
                rule_id="ob_decayed", label="订单墙状态",
                weight=w, hit=False, ratio=0.0, value=None,
                threshold=f"purity≥{purity_full}",
                note="无 trend_purity（代理信号）",
            )
        )
    else:
        purity = tp.purity
        r = max(0.0, min(1.0, purity / purity_full))
        evs.append(
            Evidence(
                rule_id="ob_decayed", label="订单墙状态（trend_purity 代理）",
                weight=w, hit=r >= 0.5, ratio=r,
                value=round(purity, 2), threshold=purity_full,
                note=f"ob_decay_threshold={ob_threshold}（→ purity 满分线 {purity_full}）",
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

    # 6) V1.1 · BOS 右侧结构延续（docs/upstream-api/endpoints/inst_choch.md）
    # 官方口径：⚡ BOS = 机构带量突破前高/前低，趋势延续确立，无需等收线。
    # 覆盖 direction：BOS_Bullish → bullish，BOS_Bearish → bearish。
    # 权重默认 0（保守修改），启用时同比减其他维度使总权重=1。
    w = float(weights.get("bos_confirm", 0.0))
    max_bars = int(thr.get("bos_max_bars_since", 3))
    ch = snap.choch_latest
    if ch is not None and (not ch.is_choch) and ch.bars_since <= max_bars and max_bars > 0:
        r = max(0.0, 1.0 - (ch.bars_since / max_bars))
        bos_dir: Direction = "bullish" if ch.direction == "bullish" else "bearish"
        # BOS 最强证据：命中即覆盖 direction（带量突破 = 真金白银）
        direction = bos_dir
        evs.append(
            Evidence(
                rule_id="bos_confirm", label="⚡ BOS 结构延续",
                weight=w, hit=True, ratio=r,
                value=f"{ch.type} @ level={ch.level_price}",
                threshold=f"bars_since≤{max_bars}",
                note=f"bars_since={ch.bars_since}，direction={ch.direction}",
            )
        )
    else:
        evs.append(
            Evidence(
                rule_id="bos_confirm", label="⚡ BOS 结构延续",
                weight=w, hit=False, ratio=0.0, value=None,
                note="近窗无 BOS 事件或已超时",
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
