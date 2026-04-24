"""模块 3：主力参与确认。

判定维度（yaml.participation.levels）：
- resonance 数量 >= min_count        +1
- fair_value 偏离 >= pct             +1
- power_imbalance.ratio >= extreme   +1
- active_session 活跃度达阈值         +1

命中条数 → ParticipationLevel（4 档）
"""

from __future__ import annotations

from typing import Any

from backend.models import ParticipationGate, ParticipationLevel

from ..features import FeatureSnapshot
from ..scoring.common import cfg_path


def build_participation(
    snap: FeatureSnapshot, cfg: dict[str, Any] | None = None
) -> ParticipationGate:
    reson_min = int(cfg_path(cfg, "participation.resonance_min_count", 2))
    fv_pct = float(cfg_path(cfg, "participation.fair_value_diverge_pct", 0.005))
    pi_extreme = float(cfg_path(cfg, "participation.power_imbalance_extreme", 2.5))
    active_th = float(cfg_path(cfg, "participation.active_session_threshold", 0.5))
    levels_map = cfg_path(cfg, "participation.levels", {}) or {}

    evidence: list[str] = []
    hits = 0

    # 1) 共振
    total_reson = snap.resonance_count_recent
    if total_reson >= reson_min:
        hits += 1
        evidence.append(
            f"共振次数 {total_reson} ≥ {reson_min}（buy={snap.resonance_buy_count}, sell={snap.resonance_sell_count}）"
        )

    # 2) fair_value 偏离
    fv = snap.fair_value_delta_pct
    if fv is not None and abs(fv) >= fv_pct:
        hits += 1
        evidence.append(
            f"真实价值偏离 {round(fv * 100, 2)}% ≥ {round(fv_pct * 100, 2)}%"
        )

    # 3) power_imbalance 极端
    pi = snap.power_imbalance_last
    if pi is not None and pi.ratio >= pi_extreme:
        hits += 1
        evidence.append(f"能量条极端 ratio={round(pi.ratio, 2)} ≥ {pi_extreme}")

    # 4) 活跃时段
    if snap.current_hour_activity >= active_th:
        hits += 1
        evidence.append(
            f"时段活跃度 {round(snap.current_hour_activity, 2)} ≥ {active_th}"
        )

    # 映射到 level：从高到低找第一个命中数 >= 要求值的
    order: list[tuple[ParticipationLevel, int]] = sorted(
        [(k, int(v)) for k, v in levels_map.items()],
        key=lambda kv: -kv[1],
    )
    level: ParticipationLevel = "垃圾时间"
    for name, required in order:
        if hits >= required:
            level = name  # type: ignore[assignment]
            break

    # confidence：命中数 / 最大可能（4）
    confidence = round(min(hits / 4.0, 1.0), 2)
    if not evidence:
        evidence.append("无任何参与证据")

    return ParticipationGate(level=level, confidence=confidence, evidence=evidence)


__all__ = ["build_participation"]
