"""indicator → parser 映射。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from backend.core.exceptions import ParseError
from backend.core.logging import Tags, get_logger

from .base import ParserFn, ParserResult
from .endpoints import (
    parse_absolute_zones,
    parse_cross_exchange_resonance,
    parse_fair_value,
    parse_fvg,
    parse_hvn_nodes,
    parse_imbalance,
    parse_inst_volume_profile,
    parse_liq_heatmap,
    parse_liq_vacuum,
    parse_liquidation_fuel,
    parse_liquidity_sweep,
    parse_micro_poc,
    parse_ob_decay,
    parse_poc_shift,
    parse_power_imbalance,
    parse_smart_money_cost,
    parse_time_heatmap,
    parse_trailing_vwap,
    parse_trend_exhaustion,
    parse_trend_price,
    parse_trend_purity,
    parse_trend_saturation,
)

logger = get_logger("collector.parser.registry")

PARSER_REGISTRY: Mapping[str, ParserFn] = {
    "smart_money_cost": parse_smart_money_cost,
    "liq_heatmap": parse_liq_heatmap,
    "absolute_zones": parse_absolute_zones,
    "fvg": parse_fvg,
    "cross_exchange_resonance": parse_cross_exchange_resonance,
    "fair_value": parse_fair_value,
    "inst_volume_profile": parse_inst_volume_profile,
    "trend_price": parse_trend_price,
    "ob_decay": parse_ob_decay,
    "micro_poc": parse_micro_poc,
    "trend_purity": parse_trend_purity,
    "poc_shift": parse_poc_shift,
    "trailing_vwap": parse_trailing_vwap,
    "trend_saturation": parse_trend_saturation,
    "liq_vacuum": parse_liq_vacuum,
    "imbalance": parse_imbalance,
    "power_imbalance": parse_power_imbalance,
    "trend_exhaustion": parse_trend_exhaustion,
    "liquidation_fuel": parse_liquidation_fuel,
    "hvn_nodes": parse_hvn_nodes,
    "liquidity_sweep": parse_liquidity_sweep,
    "time_heatmap": parse_time_heatmap,
}


def get_parser(indicator: str) -> ParserFn:
    if indicator not in PARSER_REGISTRY:
        raise ParseError(
            f"未知 indicator: {indicator}",
            detail={"available": sorted(PARSER_REGISTRY.keys())},
        )
    return PARSER_REGISTRY[indicator]


def parse_all(
    *,
    symbol: str,
    tf: str,
    indicator: str,
    payload: dict[str, Any],
) -> ParserResult:
    """安全 parse：parser 抛异常返回空结果并 WARNING。"""
    fn = get_parser(indicator)
    try:
        result = fn(symbol, tf, payload)
    except Exception as e:  # noqa: BLE001
        logger.warning(
            f"parser 失败 {indicator} {symbol} {tf}: {e}",
            extra={
                "tags": [Tags.PARSE_WARN],
                "context": {"symbol": symbol, "tf": tf, "indicator": indicator},
            },
            exc_info=True,
        )
        return ParserResult()
    return result
