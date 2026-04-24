"""反转概率分 scorer。

维度：
1. sweep_recent       事件窗内 sweep 事件（``recent_window_bars``）
2. exhaustion_high    trend_exhaustion 连续 N 根同 type 同 ≥ 阈值（官方口径）
3. fair_value_diverge 价格与真实价值显著偏离
4. liq_pierce_recover 刺穿清算带后在 ``liq_recover_bars`` 根内回到带内
5. choch_reversal     V1.1：⚡ 机构 CHoCH 结构反转事件（docs：inst_choch 右侧确认）
6. time_exhausted     V1.1：趋势时间极限（docs：time_exhaustion_window；死亡线已过/已跨虚线）
7. dd_pierce          V1.1：移动护城河 📌（docs：max_drawdown_tolerance；黄色图钉命中 = 强反转）
                      —— 第 5-7 维默认 weight=0（保守修改：现有配置不受影响）。
                      启用时请同比减小其他维度权重，使总权重 = 1.0。
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
    # 官方（docs/upstream-api/endpoints/trend_exhaustion.md §大屏使用）：
    #   连续 3 根 exhaustion ≥ 5 同 type → 强反转预警
    # streak ≥ exhaustion_consecutive_min 且 type 一致 → 满分；
    # 否则退化为单根 exhaustion ≥ alert。
    w = float(weights.get("exhaustion_high", 0.25))
    alert = float(thr.get("exhaustion_alert", 5))
    consec_min = int(thr.get("exhaustion_consecutive_min", 3))
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
        if snap.exhaustion_streak >= consec_min and snap.exhaustion_streak_type != "none":
            r = 1.0
            hit_ex = True
            note = (
                f"连续 {snap.exhaustion_streak} 根 exhaustion≥{alert}，"
                f"type={snap.exhaustion_streak_type}（满足 {consec_min}）"
            )
        else:
            r = ratio_above(float(te.exhaustion), float(alert))
            hit_ex = te.exhaustion >= alert
            note = (
                f"streak={snap.exhaustion_streak}/{consec_min}，"
                f"type={snap.exhaustion_streak_type}"
            )
        evs.append(
            Evidence(
                rule_id="exhaustion_high", label="趋势耗竭警戒",
                weight=w, hit=hit_ex, ratio=r,
                value=f"ex={te.exhaustion} type={te.type}",
                threshold=alert,
                note=note,
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

    # 4) liq 刺穿 + 回收
    # HFD 约定（backend/models.py）：
    #   bullish_sweep = 扫下方多头止损后上行 → 下刺穿 + 收回 → 看涨反转
    #   bearish_sweep = 扫上方空头止损后下行 → 上刺穿 + 收回 → 看跌反转
    # 特征层已基于 liq_recover_bars（thresholds.liq_recover_bars）判定是否回收。
    w = float(weights.get("liq_pierce_recover", 0.25))
    r = 0.0
    note = ""
    hit_lr = False
    recover_bars = int(thr.get("liq_recover_bars", 3))
    if snap.sweep_last is not None:
        if snap.pierce_recovered:
            hit_lr = True
            r = 1.0
            note = f"{snap.sweep_last.type}：{recover_bars} 根内已回收"
        elif (
            (snap.sweep_last.type == "bearish_sweep" and snap.just_broke_resistance)
            or (snap.sweep_last.type == "bullish_sweep" and snap.just_broke_support)
        ):
            # 刺穿成立但尚未验证回收：给 0.5
            hit_lr = False
            r = 0.5
            note = f"{snap.sweep_last.type}：刺穿成立，回收待确认（{recover_bars} 根窗）"
    evs.append(
        Evidence(
            rule_id="liq_pierce_recover", label="刺穿清算带后回收",
            weight=w, hit=hit_lr, ratio=r,
            value=snap.sweep_last.type if snap.sweep_last else None,
            threshold=f"recover_bars={recover_bars}",
            note=note or "无猎杀/穿越组合",
        )
    )

    # 5) V1.1 · CHoCH 右侧结构反转（docs/upstream-api/endpoints/inst_choch.md）
    # 官方口径：⚡ CHoCH = 机构真金白银砸穿前高/前低，趋势反转确立，
    # 无需等收线。越新的 CHoCH 可信度越高 → bars_since 越小 ratio 越高。
    # 权重默认 0（保守修改），启用时同比减其他维度使总权重=1。
    w = float(weights.get("choch_reversal", 0.0))
    max_bars = int(thr.get("choch_max_bars_since", 3))
    ch = snap.choch_latest
    choch_hit = False
    choch_dir: Direction = "neutral"
    if ch is not None and ch.is_choch and ch.bars_since <= max_bars and max_bars > 0:
        # 线性衰减：bars_since=0 满分；=max_bars 触界；>max_bars 已过滤
        r = max(0.0, 1.0 - (ch.bars_since / max_bars))
        choch_hit = True
        choch_dir = "bullish" if ch.direction == "bullish" else "bearish"
        evs.append(
            Evidence(
                rule_id="choch_reversal", label="⚡ CHoCH 结构反转",
                weight=w, hit=True, ratio=r,
                value=f"{ch.type} @ level={ch.level_price}",
                threshold=f"bars_since≤{max_bars}",
                note=f"bars_since={ch.bars_since}，direction={ch.direction}",
            )
        )
    else:
        evs.append(
            Evidence(
                rule_id="choch_reversal", label="⚡ CHoCH 结构反转",
                weight=w, hit=False, ratio=0.0, value=None,
                note="近窗无 CHoCH 事件或已超时",
            )
        )

    # 6) V1.1 · 趋势时间极限（docs/upstream-api/endpoints/time_exhaustion_window.md）
    # 官方口径："越过虚线防阳痿，利润落袋保平安；撞上黄墙死线到，立刻跑路防瀑布。"
    # 映射：bars_to_max ≤ 0（死亡线已过）→ ratio 1.0；bars_to_avg ≤ 0 → 0.5。
    w = float(weights.get("time_exhausted", 0.0))
    sp = snap.segment_portrait
    if sp is not None and (sp.bars_to_avg is not None or sp.bars_to_max is not None):
        if sp.bars_to_max is not None and sp.bars_to_max <= 0:
            r = 1.0
            note = f"已撞死亡线 bars_to_max={sp.bars_to_max}"
            hit_te_time = True
        elif sp.bars_to_avg is not None and sp.bars_to_avg <= 0:
            r = 0.5
            note = f"已越中年虚线 bars_to_avg={sp.bars_to_avg}"
            hit_te_time = True
        else:
            r = 0.0
            note = f"未越虚线 bars_to_avg={sp.bars_to_avg} bars_to_max={sp.bars_to_max}"
            hit_te_time = False
        evs.append(
            Evidence(
                rule_id="time_exhausted", label="趋势时间极限",
                weight=w, hit=hit_te_time, ratio=r,
                value=f"to_avg={sp.bars_to_avg} to_max={sp.bars_to_max}",
                note=note,
            )
        )
    else:
        evs.append(
            Evidence(
                rule_id="time_exhausted", label="趋势时间极限",
                weight=w, hit=False, ratio=0.0, value=None,
                note="无 segment_portrait / time 维度缺失",
            )
        )

    # 7) V1.1 · 移动护城河 📌 图钉（docs/upstream-api/endpoints/max_drawdown_tolerance.md）
    # 官方口径："黄色图钉一出现，反转在即赶紧闪"—— pierce_count ≥ 1 视作强反转信号。
    w = float(weights.get("dd_pierce", 0.0))
    if sp is not None and sp.dd_pierce_count is not None:
        pc = int(sp.dd_pierce_count)
        if pc >= 1:
            evs.append(
                Evidence(
                    rule_id="dd_pierce", label="📌 护城河刺穿",
                    weight=w, hit=True, ratio=1.0,
                    value=pc, threshold=1,
                    note="黄色图钉已出现，趋势动能衰竭",
                )
            )
        else:
            evs.append(
                Evidence(
                    rule_id="dd_pierce", label="📌 护城河刺穿",
                    weight=w, hit=False, ratio=0.0, value=pc, threshold=1,
                    note="护城河未破",
                )
            )
    else:
        evs.append(
            Evidence(
                rule_id="dd_pierce", label="📌 护城河刺穿",
                weight=w, hit=False, ratio=0.0, value=None,
                note="无 segment_portrait / dd 维度缺失",
            )
        )

    # 反转方向推断
    # docs/upstream-api/endpoints/trend_exhaustion.md §大屏使用：
    #   Distribution 耗竭 = 派发方能量耗尽 → 底部反转预警 → bullish
    #   Accumulation 耗竭 = 吸筹方能量耗尽 → 顶部反转预警 → bearish
    # 官方指标手册「能量耗竭」同样口径：
    #   红柱（派发方投入天量资金却跌不动）→ 抄底看涨
    #   绿柱（吸筹方投入天量资金却涨不动）→ 摸顶看跌
    # V1.1 · CHoCH 事件是"右侧真金白银"确认，优先级最高：
    #   - 若 CHoCH 命中 → 直接覆盖 te/fv 推断
    #   - 否则保持原有 te → fv 的推断顺序（100% 兼容现有 snap 行为）
    direction: Direction = "neutral"
    if te is not None and te.type.lower().startswith(("dist",)):
        direction = "bullish"   # 派发耗竭 → 底部反转上行
    elif te is not None and te.type.lower().startswith(("accum",)):
        direction = "bearish"   # 吸筹耗竭 → 顶部反转下行
    # fair_value 强力背离也能反推
    if fv_delta is not None:
        if fv_delta > 0 and direction == "neutral":
            direction = "bearish"   # 价格高于真实价值 → 回归下行
        elif fv_delta < 0 and direction == "neutral":
            direction = "bullish"
    # CHoCH 最强证据：命中即覆盖（真金白银砸穿前高/前低）
    if choch_hit and choch_dir != "neutral":
        direction = choch_dir

    score = finalize_score(evs)
    return CapabilityScore(
        name="reversal",
        score=score,
        band=band_from(score, bands, default="medium"),
        direction=direction,
        evidence=evs,
    )


__all__ = ["score_reversal"]
