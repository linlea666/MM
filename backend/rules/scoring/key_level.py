"""关键位强度评分（对单个 level 打分）。

一个 level 可能由多个来源（HVN + 密集博弈 + 清算带等）叠加支撑，
评分 = Σ(source.weight) + purity_bonus + ob_decay_bonus，总分封顶 100。

测试次数衰减 / 状态衰减保留钩子，Step 3.4 关键位模块构造 LevelCandidate 时会填充。
"""

from __future__ import annotations

from typing import Any

from ..features import FeatureSnapshot
from .common import band_from, cfg_path, clamp01
from .types import Evidence, LevelCandidate, LevelScore


def score_level(
    level: LevelCandidate,
    snap: FeatureSnapshot,
    cfg: dict[str, Any] | None = None,
    *,
    test_count: int = 1,
    state: str = "first_test",
) -> LevelScore:
    """按来源权重聚合该 level 的强度分。

    Args:
        test_count: 被测试次数（1..N），用来做衰减
        state: first_test / multi_test / worn_out
    """
    source_weights = cfg_path(cfg, "capabilities.key_level_strength.source_weights", {}) or {}
    purity_max = float(cfg_path(cfg, "capabilities.key_level_strength.purity_bonus_max", 10))
    ob_bonus_max = float(cfg_path(cfg, "capabilities.key_level_strength.ob_decay_bonus_max", 10))
    bands = cfg_path(cfg, "capabilities.key_level_strength.label_bands", {}) or {}
    test_decay = cfg_path(cfg, "capabilities.key_level_strength.test_count_decay", {}) or {}
    state_decay = cfg_path(cfg, "capabilities.key_level_strength.state_decay", {}) or {}

    evs: list[Evidence] = []

    # 1) 来源加权累积
    base = 0.0
    for src in level.sources:
        w = float(source_weights.get(src.kind, src.weight) or src.weight)
        base += w
        evs.append(
            Evidence(
                rule_id=f"source_{src.kind}",
                label=f"来源 {src.kind}",
                weight=w / 100.0, hit=True, ratio=1.0,
                value=src.value,
                note=f"kind={src.kind} weight={w}",
            )
        )
    base = min(base, 100.0)

    # 2) trend_purity 加分
    tp = snap.trend_purity_last
    purity_bonus = 0.0
    if tp and tp.purity > 0:
        purity_bonus = clamp01(tp.purity / 100.0) * purity_max
        evs.append(
            Evidence(
                rule_id="purity_bonus", label="纯度加分",
                weight=purity_max / 100.0, hit=True, ratio=purity_bonus / purity_max,
                value=round(tp.purity, 2),
                note="trend_purity.purity",
            )
        )

    # 3) ob_decay 加分（V1：若该 level 来源里有 trend_price，则给一半上限）
    ob_bonus = 0.0
    if any(s.kind == "trend_price" for s in level.sources):
        ob_bonus = ob_bonus_max * 0.5
        evs.append(
            Evidence(
                rule_id="ob_decay_bonus", label="订单墙未衰减",
                weight=ob_bonus_max / 100.0, hit=True, ratio=0.5,
                value="has trend_price source",
                note="V1 简化：有 trend_price 来源即给上限一半",
            )
        )

    subtotal = base + purity_bonus + ob_bonus

    # 4) 测试次数衰减
    test_decay_factor = 1.0
    key = str(test_count) if test_count <= 3 else "4+"
    if key in test_decay:
        test_decay_factor = float(test_decay[key])
    elif test_count in test_decay:
        test_decay_factor = float(test_decay[test_count])

    # 5) 状态衰减
    state_decay_factor = float(state_decay.get(state, 1.0))

    final = subtotal * test_decay_factor * state_decay_factor
    final = min(max(final, 0.0), 100.0)

    if test_decay_factor < 1.0:
        evs.append(
            Evidence(
                rule_id="test_decay", label=f"被测次数衰减 x{test_decay_factor}",
                weight=1.0, hit=True, ratio=test_decay_factor,
                value=test_count,
            )
        )
    if state_decay_factor < 1.0:
        evs.append(
            Evidence(
                rule_id="state_decay", label=f"状态衰减 x{state_decay_factor}",
                weight=1.0, hit=True, ratio=state_decay_factor,
                value=state,
            )
        )

    band = band_from(final, bands, default="weak")
    return LevelScore(
        price=level.price,
        side=level.side,
        score=round(final, 2),
        band=band,
        sources=list(level.sources),
        evidence=evs,
    )


__all__ = ["score_level"]
