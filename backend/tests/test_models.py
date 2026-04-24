"""验证 23 原子模型 + AI 校验器。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.models import (
    AIEvidence,
    AIObservation,
    AbsoluteZone,
    BehaviorAlert,
    BehaviorScore,
    DashboardHealth,
    DashboardSnapshot,
    HeroStrip,
    Kline,
    LevelLadder,
    LiquidityCompass,
    ParticipationGate,
    PhaseState,
    PowerImbalancePoint,
    Subscription,
    TimeHeatmapHour,
    TradingPlan,
    TrendSaturationStat,
)


def test_kline_basic() -> None:
    k = Kline(
        symbol="BTC", tf="30m", ts=1_700_000_000_000,
        open=60000, high=60500, low=59800, close=60200, volume=12.3,
    )
    assert k.source == "binance"
    assert k.model_dump()["close"] == 60200


def test_kline_extra_field_forbidden() -> None:
    with pytest.raises(ValidationError):
        Kline(
            symbol="BTC", tf="30m", ts=1, open=1, high=1, low=1, close=1,
            volume=1, foo="bar",  # type: ignore[call-arg]
        )


def test_absolute_zone_distinct_from_order_block() -> None:
    az = AbsoluteZone(
        symbol="BTC", tf="30m", start_time=1, bottom_price=100,
        top_price=120, type="Accumulation",
    )
    assert az.bottom_price < az.top_price


def test_power_imbalance_zero_default() -> None:
    p = PowerImbalancePoint(
        symbol="BTC", tf="30m", ts=1, buy_vol=0, sell_vol=0, ratio=0,
    )
    assert p.ratio == 0


def test_time_heatmap_hour_range() -> None:
    TimeHeatmapHour(symbol="BTC", tf="4h", hour=0, accum=0, dist=0, total=0)
    TimeHeatmapHour(symbol="BTC", tf="4h", hour=23, accum=0, dist=0, total=0)
    with pytest.raises(ValidationError):
        TimeHeatmapHour(symbol="BTC", tf="4h", hour=24, accum=0, dist=0, total=0)


def test_subscription_default_active() -> None:
    s = Subscription(symbol="BTC", added_at=1)
    assert s.active is True
    assert s.display_order == 0


def test_trend_saturation_progress_can_exceed_100() -> None:
    """文档明确 progress 可 > 100，不应有上限校验。"""
    s = TrendSaturationStat(
        symbol="BTC", tf="30m", type="Accumulation",
        start_time=1, avg_vol=10, current_vol=15, progress=150.0,
    )
    assert s.progress == 150.0


def test_trading_plan_stars_range() -> None:
    TradingPlan(
        label="A", action="回踩做多", stars=4,
        premise="趋势延续", invalidation="跌破 60000",
    )
    with pytest.raises(ValidationError):
        TradingPlan(
            label="A", action="回踩做多", stars=6,
            premise="x", invalidation="y",
        )


def test_ai_observation_forbidden_words_chinese() -> None:
    with pytest.raises(ValidationError) as ei:
        AIObservation(
            type="opportunity_candidate",
            attention_level="medium",
            headline="建议入场做多",
            description="支撑明显",
            evidences=[
                AIEvidence(indicator="trend_purity", field="purity", value=80),
                AIEvidence(indicator="smart_money_cost", field="status", value="Ongoing"),
            ],
        )
    msg = str(ei.value)
    assert "禁止词" in msg or "入场" in msg or "做多" in msg


def test_ai_observation_forbidden_words_english() -> None:
    with pytest.raises(ValidationError):
        AIObservation(
            type="conflict_warning",
            attention_level="low",
            headline="entry plan ready",
            description="ok",
            evidences=[
                AIEvidence(indicator="cvd", field="value", value=1),
                AIEvidence(indicator="vwap", field="vwap", value=1),
            ],
        )


def test_ai_observation_requires_min_two_evidences() -> None:
    with pytest.raises(ValidationError):
        AIObservation(
            type="opportunity_candidate",
            attention_level="low",
            headline="留意筹码",
            description="单一信号",
            evidences=[AIEvidence(indicator="cvd", field="value", value=1)],
        )


def test_ai_observation_valid_passes() -> None:
    obs = AIObservation(
        type="opportunity_candidate",
        attention_level="low",
        headline="筹码堆积明显",
        description="筹码纯度较高且共振活跃",
        evidences=[
            AIEvidence(indicator="trend_purity", field="purity", value=72),
            AIEvidence(indicator="cross_exchange_resonance", field="count", value=3),
        ],
    )
    assert obs.attention_level == "low"


def test_dashboard_snapshot_minimal_compose() -> None:
    snap = DashboardSnapshot(
        timestamp=1,
        symbol="BTC",
        tf="30m",
        current_price=60000,
        hero=HeroStrip(
            main_behavior="强吸筹",
            market_structure="底部震荡",
            risk_status="安全",
            action_conclusion="回踩做多",
            stars=4,
            invalidation="跌破 59800",
        ),
        behavior=BehaviorScore(
            main="强吸筹", main_score=78,
            alerts=[BehaviorAlert(type="共振爆发", strength=70)],
        ),
        phase=PhaseState(current="底部吸筹震荡", current_score=72),
        participation=ParticipationGate(level="主力真参与", confidence=0.8),
        levels=LevelLadder(current_price=60000),
        liquidity=LiquidityCompass(),
        plans=[
            TradingPlan(
                label="A", action="回踩做多", stars=4,
                premise="阶段确认", invalidation="跌破 59800",
            ),
        ],
        health=DashboardHealth(fresh=True, last_collector_ts=1, stale_seconds=0),
    )
    assert snap.behavior.main_score == 78
    assert len(snap.plans) == 1
