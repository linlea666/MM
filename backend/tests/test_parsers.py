"""29 个 parser 的 golden-sample 测试（V1 22 + V1.1 扩展 7）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.collector.parsers import PARSER_REGISTRY, parse_all
from backend.collector.parsers.base import _as_int_ms

SAMPLES = Path(__file__).resolve().parents[2] / "docs" / "upstream-api" / "samples"

# V1.1 扩展指标（便于测试中单独断言）
V11_INDICATORS = {
    "inst_choch",
    "trend_roi_exhaustion",
    "max_pain_drawdown",
    "time_exhaustion_window",
    "max_drawdown_tolerance",
    "cascade_liquidation",
    "retail_stop_loss",
}


@pytest.fixture(scope="module")
def samples() -> dict[str, dict]:
    out = {}
    for name in PARSER_REGISTRY:
        f = SAMPLES / f"{name}.sample.json"
        if not f.exists():
            continue
        out[name] = json.loads(f.read_text())
    return out


def test_all_parsers_registered():
    assert len(PARSER_REGISTRY) == 29


def test_all_samples_parsed_nonempty(samples: dict[str, dict]):
    assert len(samples) == 29, f"missing samples: {set(PARSER_REGISTRY) - set(samples)}"
    for name, payload in samples.items():
        result = parse_all(
            symbol="BTC", tf="30m", indicator=name, payload=payload
        )
        assert result.total() > 0, f"{name} 解析为空"


def test_shared_series_parsed(samples: dict[str, dict]):
    """fair_value/fvg/imbalance/poc_shift/micro_poc/liquidity_sweep 都应拆出 4 系列。"""
    for ind in ("fair_value", "fvg", "imbalance", "poc_shift", "micro_poc", "liquidity_sweep"):
        result = parse_all(symbol="BTC", tf="30m", indicator=ind, payload=samples[ind])
        for key in ("cvd", "imbalance", "inst_vol", "vwap"):
            assert key in result.atoms, f"{ind} 缺 {key}"
            assert len(result.atoms[key]) > 0


def test_trend_saturation_parses_string_time(samples: dict[str, dict]):
    result = parse_all(
        symbol="BTC", tf="30m",
        indicator="trend_saturation", payload=samples["trend_saturation"],
    )
    assert "trend_saturation" in result.replace_scopes
    stat = result.atoms["trend_saturation"][0]
    assert stat.start_time > 1_500_000_000_000  # 合理 ms 时间戳


def test_absolute_zones_converts_order_blocks_to_zones(samples: dict[str, dict]):
    result = parse_all(
        symbol="BTC", tf="30m",
        indicator="absolute_zones", payload=samples["absolute_zones"],
    )
    assert "absolute_zones" in result.atoms
    z = result.atoms["absolute_zones"][0]
    assert z.bottom_price < z.top_price


def test_hvn_nodes_assigns_rank_by_volume(samples: dict[str, dict]):
    result = parse_all(
        symbol="BTC", tf="30m", indicator="hvn_nodes", payload=samples["hvn_nodes"]
    )
    nodes = sorted(result.atoms["hvn_nodes"], key=lambda n: n.rank)
    volumes = [n.volume for n in nodes]
    assert volumes == sorted(volumes, reverse=True)


def test_resonance_events_keeps_exchanges(samples: dict[str, dict]):
    result = parse_all(
        symbol="BTC", tf="30m",
        indicator="cross_exchange_resonance",
        payload=samples["cross_exchange_resonance"],
    )
    ev = result.atoms["resonance_events"][0]
    assert ev.direction in ("buy", "sell")
    assert ev.count >= 1
    assert len(ev.exchanges) >= 1


def test_liq_vacuum_normalizes_low_high(samples: dict[str, dict]):
    result = parse_all(
        symbol="BTC", tf="30m", indicator="liq_vacuum", payload=samples["liq_vacuum"]
    )
    for band in result.atoms["vacuum"]:
        assert band.low < band.high


def test_bad_payload_returns_empty():
    result = parse_all(symbol="BTC", tf="30m", indicator="smart_money_cost", payload={})
    assert result.total() == 0
    result = parse_all(symbol="BTC", tf="30m", indicator="fair_value", payload={"cvd_series": "not-a-list"})
    assert result.total() == 0


def test_as_int_ms_parses_formats():
    assert _as_int_ms(1_700_000_000_000) == 1_700_000_000_000
    assert _as_int_ms("2025-10-01 00:00:00") > 1_700_000_000_000
    assert _as_int_ms("2025-10-01T00:00:00+00:00") > 1_700_000_000_000


def test_unknown_indicator_rejected():
    from backend.core.exceptions import ParseError
    with pytest.raises(ParseError):
        parse_all(symbol="BTC", tf="30m", indicator="nope", payload={})


# ════════════════ V1.1 扩展 7 个指标的单测 ════════════════


def test_inst_choch_filters_known_types(samples):
    result = parse_all(
        symbol="BTC", tf="30m", indicator="inst_choch", payload=samples["inst_choch"]
    )
    assert "choch_events" in result.replace_scopes
    for ev in result.atoms["choch_events"]:
        assert ev.type in {
            "CHoCH_Bullish", "CHoCH_Bearish",
            "BOS_Bullish", "BOS_Bearish",
        }
        assert ev.level_price > 0
        assert ev.origin_ts > 1_500_000_000_000
        # timestamp 必须晚于 origin_ts（事件发生在前高/前低形成之后）
        assert ev.ts >= ev.origin_ts


def test_trend_roi_exhaustion_has_tiered_targets(samples):
    result = parse_all(
        symbol="BTC", tf="30m",
        indicator="trend_roi_exhaustion", payload=samples["trend_roi_exhaustion"],
    )
    segs = result.atoms["roi_segments"]
    assert len(segs) > 0
    # 在 Accumulation 段：limit_max > limit_avg > avg（越往上越极限）
    for s in segs:
        if s.type == "Accumulation":
            assert s.limit_max_price >= s.limit_avg_price >= s.avg_price
        else:  # Distribution
            assert s.limit_max_price <= s.limit_avg_price <= s.avg_price


def test_max_pain_drawdown_bounds(samples):
    result = parse_all(
        symbol="BTC", tf="30m",
        indicator="max_pain_drawdown", payload=samples["max_pain_drawdown"],
    )
    segs = result.atoms["pain_drawdown"]
    assert len(segs) > 0
    for s in segs:
        # pain_max 是实线极限，pain_avg 是半透明带；语义上 max 更激进
        if s.type == "Accumulation":
            # 吸筹段：洗盘是向下插针，pain_max < pain_avg < avg
            assert s.pain_max_price <= s.pain_avg_price <= s.avg_price
        else:
            # 派发段：反向插针向上
            assert s.pain_max_price >= s.pain_avg_price >= s.avg_price


def test_time_exhaustion_window_time_order(samples):
    result = parse_all(
        symbol="BTC", tf="30m",
        indicator="time_exhaustion_window", payload=samples["time_exhaustion_window"],
    )
    segs = result.atoms["time_windows"]
    assert len(segs) > 0
    for s in segs:
        # 极限死亡线一定晚于平均寿命虚线
        assert s.limit_max_time >= s.limit_avg_time
        # 两者都晚于起始
        assert s.limit_avg_time >= s.start_time


def test_max_drawdown_tolerance_trailing_shape(samples):
    result = parse_all(
        symbol="BTC", tf="30m",
        indicator="max_drawdown_tolerance", payload=samples["max_drawdown_tolerance"],
    )
    segs = result.atoms["dd_tolerance"]
    assert len(segs) > 0
    # 找一段有 trailing_line 的
    with_trailing = [s for s in segs if s.trailing_line]
    assert with_trailing, "至少应有一段 trailing_line"
    s = with_trailing[0]
    for pair in s.trailing_line:
        assert len(pair) == 2
        ts, price = pair
        assert ts > 0 and price > 0


def test_cascade_liquidation_band_structure(samples):
    result = parse_all(
        symbol="BTC", tf="30m",
        indicator="cascade_liquidation", payload=samples["cascade_liquidation"],
    )
    bands = result.atoms["cascade_bands"]
    assert len(bands) > 0
    for b in bands:
        assert b.bottom_price <= b.avg_price <= b.top_price
        assert b.signal_count >= 0
        assert b.type in {"Accumulation", "Distribution"}


def test_retail_stop_loss_band_structure(samples):
    result = parse_all(
        symbol="BTC", tf="30m",
        indicator="retail_stop_loss", payload=samples["retail_stop_loss"],
    )
    bands = result.atoms["retail_stop_bands"]
    assert len(bands) > 0
    # 散户止损带颗粒更细，数量通常比 cascade 多很多
    for b in bands:
        assert b.bottom_price <= b.avg_price <= b.top_price
        assert b.volume >= 0


def test_v11_parsers_all_replace_scoped(samples):
    """7 个新指标都必须用 replace_for（避免历史残留）。"""
    for ind in V11_INDICATORS:
        result = parse_all(symbol="BTC", tf="30m", indicator=ind, payload=samples[ind])
        assert result.replace_scopes, f"{ind} 应使用 replace_for 而非 upsert"
        for key, scope in result.replace_scopes.items():
            assert scope == {"symbol": "BTC", "tf": "30m"}, (
                f"{ind}.{key} scope 必须是 (symbol, tf)"
            )
