"""模块 1：主力行为雷达。

输入：FeatureSnapshot + 4 个 CapabilityScore
输出：BehaviorScore（主标签 + sub_scores + alerts）

映射策略：
1. main 主标签：按 accumulation / distribution / breakout / reversal 相对强弱挑 7 选 1
2. alerts：扫 yaml 配的 9 个 label（accumulate/distribute/support/.../brewing）
   命中的转换为 BehaviorAlertType 并给一个 0-100 的 strength
"""

from __future__ import annotations

from typing import Any

from backend.models import BehaviorAlert, BehaviorAlertType, BehaviorMain, BehaviorScore

from ..features import FeatureSnapshot
from ..scoring import CapabilityScore
from ..scoring.common import cfg_path

# yaml label → BehaviorAlertType
_LABEL_TO_ALERT: dict[str, BehaviorAlertType] = {
    "pump": "共振爆发",
    "dump": "共振爆发",
    "support": "护盘中",
    "suppress": "压盘中",
    "bull_trap": "诱多",
    "bear_trap": "诱空",
    "exhausted": "衰竭",
    "brewing": "变盘临近",
}


def _pick_main(
    caps: dict[str, CapabilityScore],
    cfg: dict[str, Any] | None,
) -> tuple[BehaviorMain, int]:
    """从 4 个 capability 分相对关系挑主标签。"""
    acc = caps["accumulation"].score
    dis = caps["distribution"].score
    rev = caps["reversal"].score

    strong_th = float(cfg_path(cfg, "capabilities.accumulation.label_bands.very_strong", 80))
    weak_th = float(cfg_path(cfg, "capabilities.accumulation.label_bands.strong", 60))
    gap = 15  # 强弱区分 gap

    if acc >= strong_th and acc - dis >= gap:
        return "强吸筹", int(acc)
    if dis >= strong_th and dis - acc >= gap:
        return "强派发", int(dis)
    if rev >= 60 and rev > acc and rev > dis:
        return "趋势反转", int(rev)
    if acc >= weak_th and acc > dis:
        return "弱吸筹", int(acc)
    if dis >= weak_th and dis > acc:
        return "弱派发", int(dis)
    if max(acc, dis) < 40:
        return "横盘震荡", int(max(acc, dis))
    return "无主导", int(max(acc, dis, rev))


def _check_labels(
    snap: FeatureSnapshot,
    caps: dict[str, CapabilityScore],
    cfg: dict[str, Any] | None,
) -> list[tuple[str, int]]:
    """对 yaml 定义的 9 个 label 逐条判定，返回命中 (label, strength)。"""
    labels_cfg = cfg_path(cfg, "main_force_radar.labels", {}) or {}
    hits: list[tuple[str, int]] = []

    acc = caps["accumulation"].score
    dis = caps["distribution"].score
    brk = caps["breakout"].score

    # accumulate / distribute
    cfg_acc = (labels_cfg.get("accumulate") or {}).get("require", {})
    if acc >= float(cfg_acc.get("accumulation_score_gte", 60)) and dis < float(
        cfg_acc.get("distribution_score_lt", 30)
    ):
        hits.append(("accumulate", int(acc)))

    cfg_dis = (labels_cfg.get("distribute") or {}).get("require", {})
    if dis >= float(cfg_dis.get("distribution_score_gte", 60)) and acc < float(
        cfg_dis.get("accumulation_score_lt", 30)
    ):
        hits.append(("distribute", int(dis)))

    # support / suppress —— 贴近关键位 + whale 方向 + imbalance 一致
    near_pct = float(cfg_path(cfg, "global.near_price_pct", 0.006))
    near_s = snap.nearest_support_distance_pct is not None and snap.nearest_support_distance_pct <= near_pct
    near_r = snap.nearest_resistance_distance_pct is not None and snap.nearest_resistance_distance_pct <= near_pct
    if near_s and snap.whale_net_direction == "buy" and snap.imbalance_green_ratio > snap.imbalance_red_ratio:
        hits.append(("support", 70))
    if near_r and snap.whale_net_direction == "sell" and snap.imbalance_red_ratio > snap.imbalance_green_ratio:
        hits.append(("suppress", 70))

    # pump / dump —— 共振次数 + 方向 + breakout 强
    cfg_pump = (labels_cfg.get("pump") or {}).get("require", {})
    min_reson = int(cfg_pump.get("resonance_count_gte", 3))
    brk_th = float(cfg_pump.get("breakout_score_gte", 60))
    if (
        snap.resonance_buy_count >= min_reson
        and snap.whale_net_direction == "buy"
        and brk >= brk_th
    ):
        hits.append(("pump", min(100, int(brk + snap.resonance_buy_count * 3))))
    if (
        snap.resonance_sell_count >= min_reson
        and snap.whale_net_direction == "sell"
        and brk >= brk_th
    ):
        hits.append(("dump", min(100, int(brk + snap.resonance_sell_count * 3))))

    # bull_trap / bear_trap —— 刚穿越 + whale 反方向 + power_imbalance 反向
    pi_reverse_hit = snap.power_imbalance_last is not None and snap.power_imbalance_last.ratio >= 1.5
    if snap.just_broke_resistance and snap.whale_net_direction == "sell" and pi_reverse_hit:
        hits.append(("bull_trap", 75))
    if snap.just_broke_support and snap.whale_net_direction == "buy" and pi_reverse_hit:
        hits.append(("bear_trap", 75))

    # exhausted —— exhaustion 高 + saturation 高
    cfg_ex = (labels_cfg.get("exhausted") or {}).get("require", {})
    ex_th = int(cfg_ex.get("exhaustion_gte", 7))
    sat_th = float(cfg_ex.get("saturation_gte", 70))
    te = snap.trend_exhaustion_last
    ts = snap.trend_saturation
    if te and te.exhaustion >= ex_th and ts and ts.progress >= sat_th:
        hits.append(("exhausted", min(100, int(te.exhaustion * 10 + (ts.progress - sat_th)))))

    # brewing —— cvd 收敛 + 真空带近 + 活跃时段
    cvd_converge = snap.cvd_slope is not None and abs(snap.cvd_slope) < 1e6  # 粗阈值
    vacuum_near = any(v.low <= snap.last_price * 1.01 and v.high >= snap.last_price * 0.99 for v in snap.vacuums)
    if cvd_converge and vacuum_near and snap.active_session:
        hits.append(("brewing", 65))

    return hits


def build_main_force_radar(
    snap: FeatureSnapshot,
    caps: dict[str, CapabilityScore],
    cfg: dict[str, Any] | None = None,
) -> BehaviorScore:
    main, main_score = _pick_main(caps, cfg)

    # sub_scores：4 个能力分
    sub = {
        "吸筹": int(caps["accumulation"].score),
        "派发": int(caps["distribution"].score),
        "突破": int(caps["breakout"].score),
        "反转": int(caps["reversal"].score),
    }

    # alerts：label 命中 → alert 类型
    alerts: list[BehaviorAlert] = []
    seen: set[BehaviorAlertType] = set()
    priority = cfg_path(cfg, "main_force_radar.priority_order", []) or []
    hits = _check_labels(snap, caps, cfg)
    # 按 priority 排序，再去重相同 alert 类型
    hits_sorted = sorted(
        hits,
        key=lambda x: priority.index(x[0]) if x[0] in priority else 99,
    )
    for label, strength in hits_sorted:
        alert_type = _LABEL_TO_ALERT.get(label)
        if alert_type and alert_type not in seen:
            alerts.append(BehaviorAlert(type=alert_type, strength=strength))
            seen.add(alert_type)

    # sweep 事件直接进 alert
    if snap.sweep_count_recent >= 1 and "猎杀进行中" not in seen:
        alerts.append(BehaviorAlert(type="猎杀进行中", strength=min(100, snap.sweep_count_recent * 30)))

    return BehaviorScore(
        main=main,
        main_score=main_score,
        sub_scores=sub,
        alerts=alerts,
    )


__all__ = ["build_main_force_radar"]
