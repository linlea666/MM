"""22 个 HFD endpoint 的 parser 实现。

每个 parser 函数签名：``(symbol: str, tf: str, payload: dict) -> ParserResult``
容错原则：单条脏数据跳过并记 DEBUG，不中断整批。
"""

from __future__ import annotations

from typing import Any

from backend.core.logging import Tags, get_logger
from backend.core.time_utils import iso_to_ms
from backend.models import (
    AbsoluteZone,
    HeatmapBand,
    HvnNode,
    LiquidationFuelBand,
    LiquiditySweepEvent,
    MicroPocSegment,
    OrderBlock,
    PocShiftPoint,
    PowerImbalancePoint,
    ResonanceEvent,
    SmartMoneySegment,
    TimeHeatmapHour,
    TrailingVwapPoint,
    TrendExhaustionPoint,
    TrendPuritySegment,
    TrendSaturationStat,
    VacuumBand,
    VolumeProfileBucket,
)

from .base import (
    ParserResult,
    _as_int_ms,
    _safe_dict,
    _safe_list,
)
from .shared import merge_result, parse_shared_series

logger = get_logger("collector.parser")


def _skip(logger_name: str, symbol: str, indicator: str, reason: str, err: Exception) -> None:
    logger.debug(
        f"parser skip row {indicator} {symbol}: {reason} ({err})",
        extra={
            "tags": [Tags.PARSE_WARN],
            "context": {"symbol": symbol, "indicator": indicator, "reason": reason},
        },
    )


# ════════════════ 共享 bundle 类（只有 4 系列） ════════════════


def _only_shared(
    symbol: str, tf: str, payload: dict, indicator: str
) -> ParserResult:
    return parse_shared_series(symbol=symbol, tf=tf, payload=payload)


def parse_fair_value(symbol: str, tf: str, payload: dict) -> ParserResult:
    return _only_shared(symbol, tf, payload, "fair_value")


def parse_fvg(symbol: str, tf: str, payload: dict) -> ParserResult:
    return _only_shared(symbol, tf, payload, "fvg")


def parse_imbalance(symbol: str, tf: str, payload: dict) -> ParserResult:
    return _only_shared(symbol, tf, payload, "imbalance")


# ════════════════ 共享 bundle + 自身事件/点列 ════════════════


def parse_liquidity_sweep(symbol: str, tf: str, payload: dict) -> ParserResult:
    result = parse_shared_series(symbol=symbol, tf=tf, payload=payload)
    events: list = []
    for row in _safe_list(payload, "liquidity_sweep"):
        if not isinstance(row, dict):
            continue
        try:
            events.append(
                LiquiditySweepEvent(
                    symbol=symbol,
                    tf=tf,
                    ts=_as_int_ms(row.get("time") or row.get("ts") or row.get("timestamp")),
                    price=float(row["price"]),
                    type=str(row["type"]),
                    volume=float(row["volume"]),
                )
            )
        except (KeyError, TypeError, ValueError) as e:
            _skip("sweep", symbol, "liquidity_sweep", "row_invalid", e)
    result.add("sweep_events", events)
    return result


def parse_micro_poc(symbol: str, tf: str, payload: dict) -> ParserResult:
    result = parse_shared_series(symbol=symbol, tf=tf, payload=payload)
    segments: list = []
    for row in _safe_list(payload, "micro_poc"):
        if not isinstance(row, dict):
            continue
        try:
            end_time = row.get("end_time")
            segments.append(
                MicroPocSegment(
                    symbol=symbol,
                    tf=tf,
                    start_time=_as_int_ms(row["start_time"]),
                    end_time=_as_int_ms(end_time) if end_time is not None else None,
                    poc_price=float(row["poc_price"]),
                    volume=float(row["volume"]),
                    type=str(row["type"]),
                )
            )
        except (KeyError, TypeError, ValueError) as e:
            _skip("micro_poc", symbol, "micro_poc", "row_invalid", e)
    result.add("micro_poc", segments)
    return result


def parse_poc_shift(symbol: str, tf: str, payload: dict) -> ParserResult:
    result = parse_shared_series(symbol=symbol, tf=tf, payload=payload)
    points: list = []
    for row in _safe_list(payload, "poc_shift"):
        if not isinstance(row, list) or len(row) < 3:
            continue
        try:
            points.append(
                PocShiftPoint(
                    symbol=symbol,
                    tf=tf,
                    ts=_as_int_ms(row[0]),
                    poc_price=float(row[1]),
                    volume=float(row[2]),
                )
            )
        except (TypeError, ValueError) as e:
            _skip("poc_shift", symbol, "poc_shift", "row_invalid", e)
    result.add("poc_shift", points)
    return result


# ════════════════ klines + 专属列表 ════════════════


def parse_smart_money_cost(symbol: str, tf: str, payload: dict) -> ParserResult:
    result = ParserResult()
    out: list = []
    for row in _safe_list(payload, "smart_money_cost"):
        if not isinstance(row, dict):
            continue
        try:
            out.append(
                SmartMoneySegment(
                    symbol=symbol,
                    tf=tf,
                    start_time=_as_int_ms(row["start_time"]),
                    end_time=_as_int_ms(row["end_time"]) if row.get("end_time") is not None else None,
                    avg_price=float(row["avg_price"]),
                    type=str(row["type"]),
                    status=str(row.get("status") or "Unknown"),
                )
            )
        except (KeyError, TypeError, ValueError) as e:
            _skip("smart_money", symbol, "smart_money_cost", "row_invalid", e)
    result.add("smart_money", out)
    return result


def _parse_order_blocks_avg(symbol: str, tf: str, payload: dict) -> list[OrderBlock]:
    out: list = []
    for row in _safe_list(payload, "order_blocks"):
        if not isinstance(row, dict):
            continue
        try:
            out.append(
                OrderBlock(
                    symbol=symbol,
                    tf=tf,
                    start_time=_as_int_ms(row["start_time"]),
                    avg_price=float(row["avg_price"]),
                    volume=float(row["volume"]),
                    type=str(row["type"]),
                )
            )
        except (KeyError, TypeError, ValueError) as e:
            _skip("ob_avg", symbol, "order_blocks", "row_invalid", e)
    return out


def _parse_volume_profile(symbol: str, tf: str, payload: dict) -> list[VolumeProfileBucket]:
    out: list = []
    for row in _safe_list(payload, "volume_profile"):
        if not isinstance(row, dict):
            continue
        try:
            out.append(
                VolumeProfileBucket(
                    symbol=symbol,
                    tf=tf,
                    price=float(row["price"]),
                    accum=float(row.get("accum") or 0),
                    dist=float(row.get("dist") or 0),
                    total=float(row.get("total") or 0),
                )
            )
        except (KeyError, TypeError, ValueError) as e:
            _skip("vol_profile", symbol, "volume_profile", "row_invalid", e)
    return out


def parse_trend_price(symbol: str, tf: str, payload: dict) -> ParserResult:
    """trend_price: order_blocks(avg) + volume_profile（可能空）。"""
    result = ParserResult()
    result.add("order_blocks", _parse_order_blocks_avg(symbol, tf, payload))
    vp = _parse_volume_profile(symbol, tf, payload)
    if vp:
        result.replace("volume_profile", {"symbol": symbol, "tf": tf}, vp)
    return result


def parse_ob_decay(symbol: str, tf: str, payload: dict) -> ParserResult:
    result = ParserResult()
    result.add("order_blocks", _parse_order_blocks_avg(symbol, tf, payload))
    return result


def parse_absolute_zones(symbol: str, tf: str, payload: dict) -> ParserResult:
    """absolute_zones: order_blocks(bottom/top) → absolute_zones。"""
    result = ParserResult()
    zones: list = []
    for row in _safe_list(payload, "order_blocks"):
        if not isinstance(row, dict):
            continue
        try:
            zones.append(
                AbsoluteZone(
                    symbol=symbol,
                    tf=tf,
                    start_time=_as_int_ms(row["start_time"]),
                    bottom_price=float(row["bottom_price"]),
                    top_price=float(row["top_price"]),
                    type=str(row["type"]),
                )
            )
        except (KeyError, TypeError, ValueError) as e:
            _skip("abs_zone", symbol, "absolute_zones", "row_invalid", e)
    result.add("absolute_zones", zones)
    return result


def parse_inst_volume_profile(symbol: str, tf: str, payload: dict) -> ParserResult:
    """volume_profile 全量替换。"""
    result = ParserResult()
    buckets = _parse_volume_profile(symbol, tf, payload)
    result.replace("volume_profile", {"symbol": symbol, "tf": tf}, buckets)
    # 有些响应同时带 order_blocks(avg)，顺手抓一下
    obs = _parse_order_blocks_avg(symbol, tf, payload)
    if obs:
        result.add("order_blocks", obs)
    return result


def parse_trend_purity(symbol: str, tf: str, payload: dict) -> ParserResult:
    result = ParserResult()
    out: list = []
    for row in _safe_list(payload, "trend_purity"):
        if not isinstance(row, dict):
            continue
        try:
            out.append(
                TrendPuritySegment(
                    symbol=symbol,
                    tf=tf,
                    start_time=_as_int_ms(row["start_time"]),
                    end_time=_as_int_ms(row["end_time"]) if row.get("end_time") is not None else None,
                    avg_price=float(row["avg_price"]),
                    buy_vol=float(row["buy_vol"]),
                    sell_vol=float(row["sell_vol"]),
                    total_vol=float(row.get("total_vol") or (row["buy_vol"] + row["sell_vol"])),
                    purity=float(row["purity"]),
                    type=str(row["type"]),
                )
            )
        except (KeyError, TypeError, ValueError) as e:
            _skip("trend_purity", symbol, "trend_purity", "row_invalid", e)
    result.add("trend_purity", out)
    return result


def parse_trailing_vwap(symbol: str, tf: str, payload: dict) -> ParserResult:
    result = ParserResult()
    out: list = []
    for row in _safe_list(payload, "trailing_vwap"):
        if not isinstance(row, dict):
            continue
        try:
            out.append(
                TrailingVwapPoint(
                    symbol=symbol,
                    tf=tf,
                    ts=_as_int_ms(row["timestamp"]),
                    resistance=float(row["resistance"]) if row.get("resistance") is not None else None,
                    support=float(row["support"]) if row.get("support") is not None else None,
                )
            )
        except (KeyError, TypeError, ValueError) as e:
            _skip("trailing_vwap", symbol, "trailing_vwap", "row_invalid", e)
    result.add("trailing_vwap", out)
    return result


def parse_power_imbalance(symbol: str, tf: str, payload: dict) -> ParserResult:
    result = ParserResult()
    out: list = []
    for row in _safe_list(payload, "power_imbalance"):
        if not isinstance(row, dict):
            continue
        try:
            out.append(
                PowerImbalancePoint(
                    symbol=symbol,
                    tf=tf,
                    ts=_as_int_ms(row["timestamp"]),
                    buy_vol=float(row.get("buy_vol") or 0),
                    sell_vol=float(row.get("sell_vol") or 0),
                    ratio=float(row.get("ratio") or 0),
                )
            )
        except (KeyError, TypeError, ValueError) as e:
            _skip("power_imb", symbol, "power_imbalance", "row_invalid", e)
    result.add("power_imbalance", out)
    return result


def parse_trend_exhaustion(symbol: str, tf: str, payload: dict) -> ParserResult:
    result = ParserResult()
    out: list = []
    for row in _safe_list(payload, "trend_exhaustion"):
        if not isinstance(row, dict):
            continue
        try:
            out.append(
                TrendExhaustionPoint(
                    symbol=symbol,
                    tf=tf,
                    ts=_as_int_ms(row["timestamp"]),
                    exhaustion=float(row.get("exhaustion") or 0),
                    type=str(row.get("type") or "Unknown"),
                )
            )
        except (KeyError, TypeError, ValueError) as e:
            _skip("trend_ex", symbol, "trend_exhaustion", "row_invalid", e)
    result.add("trend_exhaustion", out)
    return result


def parse_cross_exchange_resonance(symbol: str, tf: str, payload: dict) -> ParserResult:
    result = ParserResult()
    out: list = []
    for row in _safe_list(payload, "cross_exchange_resonance"):
        if not isinstance(row, dict):
            continue
        try:
            exchanges = row.get("exchanges") or []
            if not isinstance(exchanges, list):
                exchanges = []
            out.append(
                ResonanceEvent(
                    symbol=symbol,
                    tf=tf,
                    ts=_as_int_ms(row["timestamp"]),
                    price=float(row["price"]),
                    direction=str(row["direction"]),
                    count=int(row.get("count") or len(exchanges)),
                    exchanges=[str(x) for x in exchanges],
                )
            )
        except (KeyError, TypeError, ValueError) as e:
            _skip("resonance", symbol, "cross_exchange_resonance", "row_invalid", e)
    result.add("resonance_events", out)
    return result


def parse_time_heatmap(symbol: str, tf: str, payload: dict) -> ParserResult:
    result = ParserResult()
    out: list = []
    for row in _safe_list(payload, "time_heatmap"):
        if not isinstance(row, dict):
            continue
        try:
            out.append(
                TimeHeatmapHour(
                    symbol=symbol,
                    tf=tf,
                    hour=int(row["hour"]),
                    accum=float(row.get("accum") or 0),
                    dist=float(row.get("dist") or 0),
                    total=float(row.get("total") or 0),
                )
            )
        except (KeyError, TypeError, ValueError) as e:
            _skip("time_heat", symbol, "time_heatmap", "row_invalid", e)
    if out:
        result.replace("time_heatmap", {"symbol": symbol, "tf": tf}, out)
    return result


def parse_trend_saturation(symbol: str, tf: str, payload: dict) -> ParserResult:
    result = ParserResult()
    d = _safe_dict(payload, "trend_saturation")
    if d is None:
        return result
    try:
        raw_start = d.get("start_time")
        if isinstance(raw_start, str) and raw_start:
            start_ms = iso_to_ms(raw_start)
        elif raw_start is not None:
            start_ms = _as_int_ms(raw_start)
        else:
            start_ms = 0
        stat = TrendSaturationStat(
            symbol=symbol,
            tf=tf,
            type=str(d.get("type") or "Unknown"),
            start_time=start_ms,
            avg_vol=float(d.get("avg_vol") or 0),
            current_vol=float(d.get("current_vol") or 0),
            progress=float(d.get("progress") or 0),
        )
        # 单行记录，用 replace_for 保证新鲜
        result.replace("trend_saturation", {"symbol": symbol, "tf": tf}, [stat])
    except (TypeError, ValueError) as e:
        _skip("trend_sat", symbol, "trend_saturation", "row_invalid", e)
    return result


def parse_liq_heatmap(symbol: str, tf: str, payload: dict) -> ParserResult:
    result = ParserResult()
    bands: list = []
    for row in _safe_list(payload, "heatmap_data"):
        if not isinstance(row, dict):
            continue
        try:
            bands.append(
                HeatmapBand(
                    symbol=symbol,
                    tf=tf,
                    start_time=_as_int_ms(row["start_time"]),
                    price=float(row["price"]),
                    intensity=float(row["intensity"]),
                    type=str(row["type"]),
                )
            )
        except (KeyError, TypeError, ValueError) as e:
            _skip("heatmap", symbol, "liq_heatmap", "row_invalid", e)
    result.replace("heatmap", {"symbol": symbol, "tf": tf}, bands)
    return result


def parse_liq_vacuum(symbol: str, tf: str, payload: dict) -> ParserResult:
    result = ParserResult()
    bands: list = []
    for row in _safe_list(payload, "liq_vacuum"):
        if not isinstance(row, list) or len(row) < 2:
            continue
        try:
            low, high = float(row[0]), float(row[1])
            if low > high:
                low, high = high, low
            bands.append(VacuumBand(symbol=symbol, tf=tf, low=low, high=high))
        except (TypeError, ValueError) as e:
            _skip("vacuum", symbol, "liq_vacuum", "row_invalid", e)
    result.replace("vacuum", {"symbol": symbol, "tf": tf}, bands)
    return result


def parse_liquidation_fuel(symbol: str, tf: str, payload: dict) -> ParserResult:
    result = ParserResult()
    bands: list = []
    for row in _safe_list(payload, "liquidation_fuel"):
        if not isinstance(row, dict):
            continue
        try:
            bottom, top = float(row["bottom"]), float(row["top"])
            if bottom > top:
                bottom, top = top, bottom
            bands.append(
                LiquidationFuelBand(
                    symbol=symbol,
                    tf=tf,
                    bottom=bottom,
                    top=top,
                    fuel=float(row["fuel"]),
                )
            )
        except (KeyError, TypeError, ValueError) as e:
            _skip("fuel", symbol, "liquidation_fuel", "row_invalid", e)
    result.replace("liquidation_fuel", {"symbol": symbol, "tf": tf}, bands)
    return result


def parse_hvn_nodes(symbol: str, tf: str, payload: dict) -> ParserResult:
    result = ParserResult()
    rows = _safe_list(payload, "hvn_nodes")
    cleaned = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            cleaned.append(
                {"price": float(row["price"]), "volume": float(row["volume"])}
            )
        except (KeyError, TypeError, ValueError) as e:
            _skip("hvn", symbol, "hvn_nodes", "row_invalid", e)
    cleaned.sort(key=lambda d: d["volume"], reverse=True)
    nodes = [
        HvnNode(symbol=symbol, tf=tf, rank=i + 1, price=d["price"], volume=d["volume"])
        for i, d in enumerate(cleaned)
    ]
    result.replace("hvn_nodes", {"symbol": symbol, "tf": tf}, nodes)
    return result


__all__ = [
    "parse_absolute_zones",
    "parse_cross_exchange_resonance",
    "parse_fair_value",
    "parse_fvg",
    "parse_hvn_nodes",
    "parse_imbalance",
    "parse_inst_volume_profile",
    "parse_liq_heatmap",
    "parse_liq_vacuum",
    "parse_liquidation_fuel",
    "parse_liquidity_sweep",
    "parse_micro_poc",
    "parse_ob_decay",
    "parse_poc_shift",
    "parse_power_imbalance",
    "parse_smart_money_cost",
    "parse_time_heatmap",
    "parse_trailing_vwap",
    "parse_trend_exhaustion",
    "parse_trend_price",
    "parse_trend_purity",
    "parse_trend_saturation",
]
