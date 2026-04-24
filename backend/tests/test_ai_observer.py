"""V1.1 · Phase 9 · AI observer + storage + agents 集成测试。

重点：
- StubProvider 注入 fixture → observer 两层串通
- 升级判断：阈值达到 → Layer 3 触发；未达标 → 不触发
- force_trade_plan=True 强制触发
- 节流：相同 anchor_ts 再次调用返回缓存
- JSONL 落盘 & 回灌
"""

from __future__ import annotations

import pytest

from backend.ai.observer import AIObserver, ObserverSettings, build_observer_input, build_summary
from backend.ai.providers import StubProvider
from backend.ai.schemas import (
    AIObserverInput,
    MoneyFlowLayerOut,
    TradePlanLayerOut,
    TrendLayerOut,
)
from backend.ai.storage import AIObservationStore
from backend.rules.features import FeatureSnapshot


def _make_snap(**over) -> FeatureSnapshot:
    defaults: dict = dict(
        symbol="BTC",
        tf="30m",
        anchor_ts=1_700_000_000_000,
        last_price=40000.0,
        atr=120.0,
    )
    defaults.update(over)
    return FeatureSnapshot(**defaults)


def _fx_trend(conf: float = 0.7, direction: str = "bullish") -> TrendLayerOut:
    return TrendLayerOut(
        direction=direction,  # type: ignore[arg-type]
        stage="breakout",
        strength="moderate",
        confidence=conf,
        narrative="当前突破阶段，CVD 上行 streak=3",
        evidences=["CVD slope=12.5", "power_imbalance_streak=3 buy"],
    )


def _fx_mf(conf: float = 0.6, dominant: str = "smart_buy") -> MoneyFlowLayerOut:
    return MoneyFlowLayerOut(
        dominant_side=dominant,  # type: ignore[arg-type]
        pressure_above="40500 爆仓带 signal=5",
        support_below="39600 VA 下沿",
        key_bands=[],
        narrative="主力在下方 39600-39800 吸筹",
        confidence=conf,
        evidences=["cascade_long_fuel 39700 sig=5", "VP POC=40100"],
    )


def _fx_plan() -> TradePlanLayerOut:
    return TradePlanLayerOut(
        legs=[],
        conditions=["等待 CVD 回调验证"],
        risk_flags=["near_saturation"],
        confidence=0.4,
        narrative="条件未完全满足，建议观望",
    )


# ── 输入映射 ────────────────────────────────────────────────


def test_build_observer_input_minimal():
    snap = _make_snap()
    payload = build_observer_input(snap)
    assert isinstance(payload, AIObserverInput)
    assert payload.symbol == "BTC"
    assert payload.tf == "30m"
    assert payload.volume_profile is None
    assert payload.time_heatmap is None
    assert payload.stale_tables == []


# ── Observer 两层 + 升级判断 ─────────────────────────────────


@pytest.mark.asyncio
async def test_observer_runs_two_layers_by_default(tmp_path):
    """默认两层 flash，confidence 低 → 不升级 Layer 3。"""
    provider = StubProvider(
        fixtures={
            "TrendLayerOut": _fx_trend(conf=0.5),       # 低于阈值 0.7
            "MoneyFlowLayerOut": _fx_mf(conf=0.5),      # 低于阈值 0.6
            "TradePlanLayerOut": _fx_plan(),            # 不应被调用
        }
    )
    store = AIObservationStore(
        ring_size=10, jsonl_path=tmp_path / "ai_observations.jsonl"
    )
    observer = AIObserver(
        provider=provider,
        store=store,
        settings=ObserverSettings(
            enabled=True,
            min_interval_seconds=0,
            cache_ttl_seconds=0,
        ),
    )

    item = await observer.run(_make_snap())
    assert item.trend is not None
    assert item.money_flow is not None
    assert item.trade_plan is None  # 未升级
    assert "trend" in item.layers_used
    assert "money_flow" in item.layers_used
    assert "trade_plan" not in item.layers_used
    assert item.errors == {}
    assert store.size() == 1
    # jsonl 写盘
    assert (tmp_path / "ai_observations.jsonl").exists()


@pytest.mark.asyncio
async def test_observer_auto_upgrades_trade_plan(tmp_path):
    """confidence 都达标 → 自动升级 Layer 3。"""
    provider = StubProvider(
        fixtures={
            "TrendLayerOut": _fx_trend(conf=0.8),
            "MoneyFlowLayerOut": _fx_mf(conf=0.7),
            "TradePlanLayerOut": _fx_plan(),
        }
    )
    store = AIObservationStore(ring_size=10, jsonl_path=tmp_path / "out.jsonl")
    observer = AIObserver(
        provider=provider,
        store=store,
        settings=ObserverSettings(enabled=True, min_interval_seconds=0),
    )
    item = await observer.run(_make_snap())
    assert item.trade_plan is not None
    assert set(item.layers_used) == {"trend", "money_flow", "trade_plan"}


@pytest.mark.asyncio
async def test_observer_force_trade_plan_bypasses_threshold(tmp_path):
    """force_trade_plan=True 跳过阈值判断。"""
    provider = StubProvider(
        fixtures={
            "TrendLayerOut": _fx_trend(conf=0.2),
            "MoneyFlowLayerOut": _fx_mf(conf=0.2, dominant="neutral"),
            "TradePlanLayerOut": _fx_plan(),
        }
    )
    store = AIObservationStore(ring_size=10)
    observer = AIObserver(
        provider=provider,
        store=store,
        settings=ObserverSettings(enabled=True, min_interval_seconds=0),
    )
    item = await observer.run(_make_snap(), trigger="manual", force_trade_plan=True)
    assert item.trade_plan is not None


@pytest.mark.asyncio
async def test_observer_throttles_same_anchor_ts(tmp_path):
    provider = StubProvider(
        fixtures={
            "TrendLayerOut": _fx_trend(conf=0.5),
            "MoneyFlowLayerOut": _fx_mf(conf=0.5),
        }
    )
    store = AIObservationStore(ring_size=10)
    observer = AIObserver(
        provider=provider,
        store=store,
        settings=ObserverSettings(
            enabled=True, min_interval_seconds=999, cache_ttl_seconds=999
        ),
    )
    snap = _make_snap()
    first = await observer.run(snap)
    second = await observer.run(snap)
    # 第二次应返回同一条（节流命中）
    assert first.ts == second.ts
    assert store.size() == 1


@pytest.mark.asyncio
async def test_observer_disabled_returns_empty():
    provider = StubProvider(fixtures={})
    store = AIObservationStore(ring_size=10)
    observer = AIObserver(
        provider=provider,
        store=store,
        settings=ObserverSettings(enabled=False),
    )
    item = await observer.run(_make_snap())
    assert item.trend is None
    assert item.money_flow is None
    assert item.note == "ai.enabled=false"
    assert store.size() == 0


@pytest.mark.asyncio
async def test_observer_partial_failure_preserves_other_layer(tmp_path):
    """trend 失败 → money_flow 仍正常。"""
    provider = StubProvider(
        fixtures={
            # 故意不给 TrendLayerOut → 触发 parse 错误
            "MoneyFlowLayerOut": _fx_mf(conf=0.5),
        }
    )
    store = AIObservationStore(ring_size=10)
    observer = AIObserver(
        provider=provider,
        store=store,
        settings=ObserverSettings(enabled=True, min_interval_seconds=0),
    )
    item = await observer.run(_make_snap())
    assert item.trend is None
    assert "trend" in item.errors
    assert item.money_flow is not None
    assert "money_flow" not in item.errors
    assert item.layers_used == ["money_flow"]


# ── 存储回灌 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_storage_jsonl_roundtrip(tmp_path):
    provider = StubProvider(
        fixtures={
            "TrendLayerOut": _fx_trend(),
            "MoneyFlowLayerOut": _fx_mf(),
        }
    )
    p = tmp_path / "ai.jsonl"
    store1 = AIObservationStore(ring_size=10, jsonl_path=p)
    observer = AIObserver(
        provider=provider,
        store=store1,
        settings=ObserverSettings(enabled=True, min_interval_seconds=0),
    )
    await observer.run(_make_snap(anchor_ts=1))
    await observer.run(_make_snap(anchor_ts=2))
    assert p.exists()

    # 新实例回灌
    store2 = AIObservationStore(ring_size=10, jsonl_path=p)
    loaded = await store2.load_tail_from_jsonl(limit=10)
    assert loaded == 2
    latest = await store2.latest()
    assert latest is not None
    assert latest.anchor_ts == 2


# ── 摘要派生 ────────────────────────────────────────────────


def test_build_summary():
    provider_item = _fx_trend()
    from backend.ai.schemas import AIObserverFeedItem

    item = AIObserverFeedItem(
        ts=1_700_000_000_000,
        symbol="BTC",
        tf="30m",
        anchor_ts=1_700_000_000_000,
        last_price=40000.0,
        trend=provider_item,
        money_flow=_fx_mf(),
        trade_plan=None,
    )
    summary = build_summary(item, now_ts=1_700_000_030_000)
    assert summary.trend_direction == "bullish"
    assert summary.money_flow_dominant == "smart_buy"
    assert summary.age_seconds == 30
    assert summary.has_trade_plan is False


# ── V1.1 · 统一模型 & thinking 开关回归 ─────────────────────────


def test_observer_settings_defaults_v11():
    """默认：model_tier=flash, thinking_enabled=False，timeout/temperature 按 tier 解析。"""
    s = ObserverSettings()
    assert s.model_tier == "flash"
    assert s.thinking_enabled is False
    assert s.current_timeout_s() == 20.0  # flash 默认
    assert s.current_temperature() == 0.2

    s2 = ObserverSettings(model_tier="pro")
    assert s2.current_timeout_s() == 45.0
    assert s2.current_temperature() == 0.15

    # thinking=True 时 timeout x2（无论 tier）
    s3 = ObserverSettings(model_tier="flash", thinking_enabled=True)
    assert s3.current_timeout_s() == 40.0


def test_build_from_rules_model_tier_normalization():
    """build_from_rules：大小写 / 非法 tier 都归一到 flash。"""
    from backend.ai.config import build_from_rules

    c1 = build_from_rules({})
    assert c1.model_tier == "flash"
    assert c1.thinking_enabled is False

    c2 = build_from_rules({"ai": {"model_tier": "Pro"}})
    assert c2.model_tier == "pro"

    c3 = build_from_rules({"ai": {"model_tier": "unknown_tier"}})
    assert c3.model_tier == "flash", "非法 tier 必须回落到 flash"

    c4 = build_from_rules({"ai": {"thinking_enabled": True, "model_tier": "pro"}})
    assert c4.thinking_enabled is True
    assert c4.model_tier == "pro"


@pytest.mark.asyncio
async def test_stub_provider_accepts_thinking_kwarg():
    """StubProvider 接收 thinking_enabled 不应抛。"""
    provider = StubProvider(
        fixtures={"TrendLayerOut": _fx_trend()},
    )
    # 直接调 complete_json，模拟 agent 透传路径
    resp = await provider.complete_json(
        messages=[{"role": "user", "content": "ping"}],
        schema=TrendLayerOut,
        model="stub-flash",
        thinking_enabled=True,
    )
    assert resp.parsed is not None


@pytest.mark.asyncio
async def test_observer_uses_unified_tier():
    """V1.1：observer 三层应全部用 settings.model_tier 对应的模型；
    即便 tier=pro 时 L1/L2 也走 pro（不再 hybrid）。"""
    provider = StubProvider(
        fixtures={
            "TrendLayerOut": _fx_trend(conf=0.85),
            "MoneyFlowLayerOut": _fx_mf(conf=0.85),
            "TradePlanLayerOut": _fx_plan(),
        }
    )
    store = AIObservationStore(ring_size=5, jsonl_path=None)
    observer = AIObserver(
        provider=provider,
        store=store,
        settings=ObserverSettings(
            enabled=True,
            min_interval_seconds=0,
            model_tier="pro",  # 统一走 pro
            thinking_enabled=True,
        ),
    )
    item = await observer.run(_make_snap(anchor_ts=42), force_trade_plan=True)
    assert item.trend is not None
    assert item.money_flow is not None
    assert item.trade_plan is not None
    # 三层的 model 应为 stub-pro（StubProvider.models["pro"]）
    assert item.models_used["trend"] == "stub-pro"
    assert item.models_used["money_flow"] == "stub-pro"
    assert item.models_used["trade_plan"] == "stub-pro"
