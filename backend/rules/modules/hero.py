"""HeroStrip（顶部 4 维度结论条）。

这是 Step 3.5 RuleRunner 把各模块结果拼成一句话 + 星级 + 失效条件。
放在模块层是为了逻辑集中，不在 RuleRunner 里堆字符串。
"""

from __future__ import annotations

from backend.models import (
    BehaviorScore,
    HeroStrip,
    LevelLadder,
    LiquidityCompass,
    ParticipationGate,
    PhaseState,
    TradingPlan,
)

from ..features import ChochLatestView


def _risk_label(
    phase: PhaseState, participation: ParticipationGate, unstable: bool
) -> str:
    if unstable:
        return f"结构不稳（{phase.current}，参与 {participation.level}）"
    if participation.level == "垃圾时间":
        return "垃圾时间异动，可信度低"
    if participation.level == "疑似散户":
        return "散户推动为主"
    if phase.current == "趋势耗竭":
        return "趋势耗竭，警惕反转"
    return f"{phase.current}｜参与 {participation.level}"


def _market_structure(
    phase: PhaseState,
    levels: LevelLadder,
    liq: LiquidityCompass,
    choch: ChochLatestView | None,
    choch_alert_bars: int,
) -> str:
    """组装结构描述。choch 命中时以 ⚡ 闪电角标开头（右侧确认，优先级最高）。"""
    pieces: list[str] = []
    # V1.1 · ⚡ CHoCH/BOS：近 choch_alert_bars 根内的事件直接上角标
    if (
        choch is not None
        and choch_alert_bars > 0
        and choch.bars_since <= choch_alert_bars
    ):
        arrow = "↑" if choch.direction == "bullish" else "↓"
        pieces.append(
            f"⚡{choch.kind}{arrow} 破 {round(choch.level_price, 2)}"
        )
    pieces.append(phase.current)
    if levels.r1 and levels.s1:
        pieces.append(f"R1={levels.r1.price} / S1={levels.s1.price}")
    if liq.nearest_side and liq.nearest_distance_pct is not None:
        pieces.append(
            f"磁吸{'↑' if liq.nearest_side == 'above' else '↓'} {round(liq.nearest_distance_pct * 100, 2)}%"
        )
    return "｜".join(pieces)


def build_hero(
    *,
    behavior: BehaviorScore,
    phase: PhaseState,
    participation: ParticipationGate,
    levels: LevelLadder,
    liquidity: LiquidityCompass,
    plans: list[TradingPlan],
    choch_latest: ChochLatestView | None = None,
    choch_alert_bars: int = 3,
) -> HeroStrip:
    """组装 HeroStrip。

    V1.1 新增：``choch_latest`` / ``choch_alert_bars`` 两个可选参数
    （默认 None / 3，保持向后兼容 —— 未传时行为完全等同旧版）。
    """
    main_plan = plans[0] if plans else None

    main_behavior = f"{behavior.main}（{behavior.main_score}）"
    if behavior.alerts:
        main_behavior += f" · {behavior.alerts[0].type}"

    action_conclusion = (
        f"{main_plan.action}（{main_plan.stars}★）" if main_plan else "观望"
    )
    invalidation = main_plan.invalidation if main_plan else "等待更清晰信号"
    stars = main_plan.stars if main_plan else 0

    return HeroStrip(
        main_behavior=main_behavior,
        market_structure=_market_structure(
            phase, levels, liquidity, choch_latest, choch_alert_bars
        ),
        risk_status=_risk_label(phase, participation, phase.unstable),
        action_conclusion=action_conclusion,
        stars=stars,
        invalidation=invalidation,
    )


__all__ = ["build_hero"]
