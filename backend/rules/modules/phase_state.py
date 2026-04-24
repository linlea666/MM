"""模块 2：趋势阶段状态机（8 阶段）。

输入：FeatureSnapshot + 4 个 CapabilityScore
输出：PhaseState

注意：单次 tick 不保存历史，``bars_in_phase`` 恒 0；``prev_phase`` 由
``RuleRunner`` 跨 tick 传入，``unstable`` 仅由本 tick 的 ``phase_score`` 判定
（``phase_state_machine.phase_score_threshold``）。"""

from __future__ import annotations

from typing import Any

from backend.models import PhaseLabel, PhaseState

from ..features import FeatureSnapshot
from ..scoring import CapabilityScore
from ..scoring.common import cfg_path

# yaml phase key → 中文 PhaseLabel
_PHASE_LABEL: dict[str, PhaseLabel] = {
    "bottom_accumulation": "底部吸筹震荡",
    "top_distribution": "高位派发震荡",
    "real_breakout": "真突破启动",
    "trend_continuation": "趋势延续",
    "fake_breakout": "假突破猎杀",
    "trend_exhaustion": "趋势耗竭",
    "vacuum_acceleration": "黑洞加速",
    "chaotic": "无序震荡",
}

_PHASE_ORDER = [
    "real_breakout",
    "vacuum_acceleration",
    "fake_breakout",
    "trend_exhaustion",
    "top_distribution",
    "bottom_accumulation",
    "trend_continuation",
    "chaotic",
]


def _vacuum_breached(snap: FeatureSnapshot) -> bool:
    """当前价处在真空带内（已攻入）。"""
    return any(v.low <= snap.last_price <= v.high for v in snap.vacuums)


def _eval_phase(
    key: str,
    require: dict[str, Any],
    snap: FeatureSnapshot,
    caps: dict[str, CapabilityScore],
    participation_level: str | None,
) -> tuple[bool, int]:
    """返回 (是否命中, phase score 0-100)。"""
    if not require:
        return True, 50   # chaotic 兜底

    acc = caps["accumulation"].score
    dis = caps["distribution"].score
    brk = caps["breakout"].score
    rev = caps["reversal"].score
    sat = snap.trend_saturation.progress if snap.trend_saturation else 0.0
    ex = snap.trend_exhaustion_last.exhaustion if snap.trend_exhaustion_last else 0

    # 工具：读阈值 & 跟踪 misses
    hits = 0
    total = 0

    def _gte(val: float, key_in_req: str) -> bool:
        nonlocal hits, total
        if key_in_req not in require:
            return True
        total += 1
        ok = val >= float(require[key_in_req])
        if ok:
            hits += 1
        return ok

    def _lt(val: float, key_in_req: str) -> bool:
        nonlocal hits, total
        if key_in_req not in require:
            return True
        total += 1
        ok = val < float(require[key_in_req])
        if ok:
            hits += 1
        return ok

    def _gt(val: float, key_in_req: str) -> bool:
        nonlocal hits, total
        if key_in_req not in require:
            return True
        total += 1
        ok = val > float(require[key_in_req])
        if ok:
            hits += 1
        return ok

    def _between(val: float, key_in_req: str) -> bool:
        nonlocal hits, total
        if key_in_req not in require:
            return True
        total += 1
        lo, hi = require[key_in_req]
        ok = float(lo) <= val < float(hi)
        if ok:
            hits += 1
        return ok

    # 规则命中（全部需要才算 overall 命中）
    passes = True
    if not _gte(acc, "accumulation_score_gte"):
        passes = False
    if not _lt(acc, "accumulation_score_lt"):
        passes = False
    if not _gte(dis, "distribution_score_gte"):
        passes = False
    if not _lt(sat, "saturation_lt"):
        passes = False
    if not _gt(sat, "saturation_gt"):
        passes = False
    if not _gte(sat, "saturation_gte"):
        passes = False
    if not _gte(brk, "breakout_score_gte"):
        passes = False
    if not _lt(brk, "breakout_score_lt"):
        passes = False
    if not _between(brk, "breakout_score_between"):
        passes = False
    if not _gte(rev, "reversal_score_gte"):
        passes = False
    if not _lt(rev, "reversal_score_lt"):
        passes = False
    if not _gte(ex, "exhaustion_gte"):
        passes = False

    if "vacuum_breached" in require:
        total += 1
        vb = _vacuum_breached(snap)
        if require["vacuum_breached"] == vb:
            hits += 1
        else:
            passes = False

    if "participation" in require:
        total += 1
        ok = participation_level in set(require["participation"])
        if ok:
            hits += 1
        else:
            passes = False

    # phase score：命中的占比 × 100
    score = int((hits / total) * 100) if total else 50
    return passes, score


def build_phase_state(
    snap: FeatureSnapshot,
    caps: dict[str, CapabilityScore],
    cfg: dict[str, Any] | None = None,
    *,
    participation_level: str | None = None,
    prev_phase: PhaseLabel | None = None,
) -> PhaseState:
    phases_cfg = cfg_path(cfg, "phase_state_machine.phases", {}) or {}
    threshold = int(cfg_path(cfg, "phase_state_machine.phase_score_threshold", 60))

    results: list[tuple[str, bool, int]] = []
    for key in _PHASE_ORDER:
        require = (phases_cfg.get(key) or {}).get("require", {})
        passed, score = _eval_phase(key, require, snap, caps, participation_level)
        results.append((key, passed, score))

    # 优先挑命中的，按优先级顺序
    chosen_key = "chaotic"
    chosen_score = 0
    for key, passed, score in results:
        if passed:
            chosen_key = key
            chosen_score = score
            break

    # 次高候选作为 next_likely（命中分 ≥ threshold）
    next_key: str | None = None
    for key, passed, score in results:
        if key != chosen_key and passed:
            next_key = key
            break

    unstable = chosen_score < threshold
    return PhaseState(
        current=_PHASE_LABEL[chosen_key],
        current_score=chosen_score,
        prev_phase=prev_phase,
        next_likely=_PHASE_LABEL[next_key] if next_key else None,
        unstable=unstable,
        bars_in_phase=0,
    )


__all__ = ["build_phase_state"]
