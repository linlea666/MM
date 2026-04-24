"""共享 bundle 解析（cvd/imbalance/inst_vol/vwap 四系列）。

多个 endpoint（fair_value / fvg / imbalance / liquidity_sweep / micro_poc / poc_shift）
都会返回这 4 个系列。为避免重复逻辑，封装在这里，每个 endpoint parser 调用。
"""

from __future__ import annotations

from typing import Any

from backend.models import CvdPoint, ImbalancePoint, InstVolPoint, VwapPoint

from .base import ParserResult, _as_int_ms


def _parse_ts_value_series(
    payload: dict,
    field: str,
    symbol: str,
    tf: str,
    model_cls,
    value_field: str = "value",
):
    out = []
    for row in payload.get(field) or []:
        if not isinstance(row, list) or len(row) < 2:
            continue
        try:
            ts = _as_int_ms(row[0])
            val = float(row[1])
        except (TypeError, ValueError):
            continue
        out.append(
            model_cls(symbol=symbol, tf=tf, ts=ts, **{value_field: val})
        )
    return out


def parse_shared_series(
    *,
    symbol: str,
    tf: str,
    payload: dict[str, Any],
) -> ParserResult:
    """解析 cvd / imbalance / inst_vol / vwap 四系列。"""
    result = ParserResult()
    result.add(
        "cvd",
        _parse_ts_value_series(payload, "cvd_series", symbol, tf, CvdPoint),
    )
    result.add(
        "imbalance",
        _parse_ts_value_series(
            payload, "imbalance_series", symbol, tf, ImbalancePoint
        ),
    )
    result.add(
        "inst_vol",
        _parse_ts_value_series(payload, "inst_vol_series", symbol, tf, InstVolPoint),
    )
    result.add(
        "vwap",
        _parse_ts_value_series(
            payload, "vwap_series", symbol, tf, VwapPoint, value_field="vwap"
        ),
    )
    return result


