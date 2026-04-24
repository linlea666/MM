"""22 个 parser 的 golden-sample 测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.collector.parsers import PARSER_REGISTRY, parse_all
from backend.collector.parsers.base import _as_int_ms

SAMPLES = Path(__file__).resolve().parents[2] / "docs" / "upstream-api" / "samples"


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
    assert len(PARSER_REGISTRY) == 22


def test_all_samples_parsed_nonempty(samples: dict[str, dict]):
    assert len(samples) == 22, f"missing samples: {set(PARSER_REGISTRY) - set(samples)}"
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
