"""22 个原子数据的 repository（Kline 除外，在 kline.py）。

分类：
- 时序点（8 个）：主键 (symbol, tf, ts)
- 段式区间（5 个）：主键 (symbol, tf, start_time, type)
- 事件（2 个）：主键 (symbol, tf, ts, price, direction|type)
- 价位（5 个）：按 scope 全量替换
- 聚合（2 个）：主键 (symbol, tf[, hour])
"""

from __future__ import annotations

import json
from typing import Any

from backend.models import (
    AbsoluteZone,
    CascadeBand,
    ChochEvent,
    CvdPoint,
    DdToleranceSegment,
    HeatmapBand,
    HvnNode,
    ImbalancePoint,
    InstVolPoint,
    LiquidationFuelBand,
    LiquiditySweepEvent,
    MicroPocSegment,
    OrderBlock,
    PainDrawdownSegment,
    PocShiftPoint,
    PowerImbalancePoint,
    ResonanceEvent,
    RetailStopBand,
    RoiSegment,
    SmartMoneySegment,
    TimeHeatmapHour,
    TimeWindowSegment,
    TrailingVwapPoint,
    TrendExhaustionPoint,
    TrendPuritySegment,
    TrendSaturationStat,
    VacuumBand,
    VolumeProfileBucket,
    VwapPoint,
)

from .base import AtomRepository

# ════════════════ 时序点（8 个，kline 已单独） ════════════════


class CvdRepository(AtomRepository[CvdPoint]):
    TABLE = "atoms_cvd"
    MODEL = CvdPoint
    PRIMARY = ("symbol", "tf", "ts")
    COLUMNS = ("symbol", "tf", "ts", "value")


class ImbalanceRepository(AtomRepository[ImbalancePoint]):
    TABLE = "atoms_imbalance"
    MODEL = ImbalancePoint
    PRIMARY = ("symbol", "tf", "ts")
    COLUMNS = ("symbol", "tf", "ts", "value")


class InstVolRepository(AtomRepository[InstVolPoint]):
    TABLE = "atoms_inst_vol"
    MODEL = InstVolPoint
    PRIMARY = ("symbol", "tf", "ts")
    COLUMNS = ("symbol", "tf", "ts", "value")


class VwapRepository(AtomRepository[VwapPoint]):
    TABLE = "atoms_vwap"
    MODEL = VwapPoint
    PRIMARY = ("symbol", "tf", "ts")
    COLUMNS = ("symbol", "tf", "ts", "vwap")


class PocShiftRepository(AtomRepository[PocShiftPoint]):
    TABLE = "atoms_poc_shift"
    MODEL = PocShiftPoint
    PRIMARY = ("symbol", "tf", "ts")
    COLUMNS = ("symbol", "tf", "ts", "poc_price", "volume")


class TrailingVwapRepository(AtomRepository[TrailingVwapPoint]):
    TABLE = "atoms_trailing_vwap"
    MODEL = TrailingVwapPoint
    PRIMARY = ("symbol", "tf", "ts")
    COLUMNS = ("symbol", "tf", "ts", "resistance", "support")


class PowerImbalanceRepository(AtomRepository[PowerImbalancePoint]):
    TABLE = "atoms_power_imbalance"
    MODEL = PowerImbalancePoint
    PRIMARY = ("symbol", "tf", "ts")
    COLUMNS = ("symbol", "tf", "ts", "buy_vol", "sell_vol", "ratio")


class TrendExhaustionRepository(AtomRepository[TrendExhaustionPoint]):
    TABLE = "atoms_trend_exhaustion"
    MODEL = TrendExhaustionPoint
    PRIMARY = ("symbol", "tf", "ts")
    COLUMNS = ("symbol", "tf", "ts", "exhaustion", "type")


# ════════════════ 段式区间（5 个） ════════════════


class SmartMoneyRepository(AtomRepository[SmartMoneySegment]):
    TABLE = "atoms_smart_money"
    MODEL = SmartMoneySegment
    PRIMARY = ("symbol", "tf", "start_time", "type")
    COLUMNS = ("symbol", "tf", "start_time", "end_time", "avg_price", "type", "status")


class OrderBlockRepository(AtomRepository[OrderBlock]):
    TABLE = "atoms_order_blocks"
    MODEL = OrderBlock
    PRIMARY = ("symbol", "tf", "start_time", "type")
    COLUMNS = ("symbol", "tf", "start_time", "avg_price", "volume", "type")


class AbsoluteZoneRepository(AtomRepository[AbsoluteZone]):
    TABLE = "atoms_absolute_zones"
    MODEL = AbsoluteZone
    PRIMARY = ("symbol", "tf", "start_time", "type")
    COLUMNS = ("symbol", "tf", "start_time", "bottom_price", "top_price", "type")


class MicroPocRepository(AtomRepository[MicroPocSegment]):
    TABLE = "atoms_micro_poc"
    MODEL = MicroPocSegment
    PRIMARY = ("symbol", "tf", "start_time", "type")
    COLUMNS = (
        "symbol", "tf", "start_time", "end_time",
        "poc_price", "volume", "type",
    )


class TrendPurityRepository(AtomRepository[TrendPuritySegment]):
    TABLE = "atoms_trend_purity"
    MODEL = TrendPuritySegment
    PRIMARY = ("symbol", "tf", "start_time", "type")
    COLUMNS = (
        "symbol", "tf", "start_time", "end_time",
        "avg_price", "buy_vol", "sell_vol", "total_vol", "purity", "type",
    )


# ════════════════ 事件（2 个） ════════════════


class ResonanceEventRepository(AtomRepository[ResonanceEvent]):
    TABLE = "atoms_resonance_events"
    MODEL = ResonanceEvent
    PRIMARY = ("symbol", "tf", "ts", "price", "direction")
    COLUMNS = ("symbol", "tf", "ts", "price", "direction", "count", "exchanges")

    @classmethod
    def _transform_write(cls, row, model_data):
        row["exchanges"] = json.dumps(model_data.get("exchanges") or [])
        return row

    @classmethod
    def _transform_read(cls, row):
        row["exchanges"] = json.loads(row.get("exchanges") or "[]")
        return row


class SweepEventRepository(AtomRepository[LiquiditySweepEvent]):
    TABLE = "atoms_sweep_events"
    MODEL = LiquiditySweepEvent
    PRIMARY = ("symbol", "tf", "ts", "price", "type")
    COLUMNS = ("symbol", "tf", "ts", "price", "type", "volume")


# ════════════════ 价位（5 个，replace_for 全量覆盖） ════════════════


class HeatmapRepository(AtomRepository[HeatmapBand]):
    TABLE = "atoms_heatmap"
    MODEL = HeatmapBand
    PRIMARY = ("symbol", "tf", "start_time", "price", "type")
    COLUMNS = ("symbol", "tf", "start_time", "price", "intensity", "type")


class VacuumRepository(AtomRepository[VacuumBand]):
    TABLE = "atoms_vacuum"
    MODEL = VacuumBand
    PRIMARY = ("symbol", "tf", "low", "high")
    COLUMNS = ("symbol", "tf", "low", "high")


class LiquidationFuelRepository(AtomRepository[LiquidationFuelBand]):
    TABLE = "atoms_liquidation_fuel"
    MODEL = LiquidationFuelBand
    PRIMARY = ("symbol", "tf", "bottom", "top")
    COLUMNS = ("symbol", "tf", "bottom", "top", "fuel")


class HvnNodeRepository(AtomRepository[HvnNode]):
    TABLE = "atoms_hvn_nodes"
    MODEL = HvnNode
    PRIMARY = ("symbol", "tf", "rank")
    COLUMNS = ("symbol", "tf", "rank", "price", "volume")


class VolumeProfileRepository(AtomRepository[VolumeProfileBucket]):
    TABLE = "atoms_volume_profile"
    MODEL = VolumeProfileBucket
    PRIMARY = ("symbol", "tf", "price")
    COLUMNS = ("symbol", "tf", "price", "accum", "dist", "total")


# ════════════════ 聚合（2 个） ════════════════


class TimeHeatmapRepository(AtomRepository[TimeHeatmapHour]):
    TABLE = "atoms_time_heatmap"
    MODEL = TimeHeatmapHour
    PRIMARY = ("symbol", "tf", "hour")
    COLUMNS = ("symbol", "tf", "hour", "accum", "dist", "total")


class TrendSaturationRepository(AtomRepository[TrendSaturationStat]):
    TABLE = "atoms_trend_saturation"
    MODEL = TrendSaturationStat
    PRIMARY = ("symbol", "tf")
    COLUMNS = (
        "symbol", "tf", "type", "start_time", "avg_vol", "current_vol", "progress",
    )


# ════════════════ V1.1 扩展（7 个） ════════════════


class ChochEventRepository(AtomRepository[ChochEvent]):
    """机构 CHoCH/BOS 事件。主键含 level_price 以避免同一 ts 多事件冲突。"""

    TABLE = "atoms_choch_events"
    MODEL = ChochEvent
    PRIMARY = ("symbol", "tf", "ts", "type", "level_price")
    COLUMNS = ("symbol", "tf", "ts", "price", "level_price", "origin_ts", "type")


class RoiSegmentRepository(AtomRepository[RoiSegment]):
    TABLE = "atoms_roi_segments"
    MODEL = RoiSegment
    PRIMARY = ("symbol", "tf", "start_time", "type")
    COLUMNS = (
        "symbol", "tf", "start_time", "end_time",
        "avg_price", "limit_avg_price", "limit_max_price",
        "type", "status",
    )


class PainDrawdownRepository(AtomRepository[PainDrawdownSegment]):
    TABLE = "atoms_pain_drawdown_segments"
    MODEL = PainDrawdownSegment
    PRIMARY = ("symbol", "tf", "start_time", "type")
    COLUMNS = (
        "symbol", "tf", "start_time", "end_time",
        "avg_price", "pain_avg_price", "pain_max_price",
        "type", "status",
    )


class TimeWindowRepository(AtomRepository[TimeWindowSegment]):
    TABLE = "atoms_time_windows"
    MODEL = TimeWindowSegment
    PRIMARY = ("symbol", "tf", "start_time", "type")
    COLUMNS = (
        "symbol", "tf", "start_time", "end_time", "last_update_time",
        "avg_price", "limit_avg_time", "limit_max_time",
        "type", "status",
    )


class DdToleranceRepository(AtomRepository[DdToleranceSegment]):
    """涨跌极限段：trailing_line/pierces 以 JSON 存储。"""

    TABLE = "atoms_dd_tolerance_segments"
    MODEL = DdToleranceSegment
    PRIMARY = ("symbol", "tf", "id")
    COLUMNS = (
        "symbol", "tf", "id", "start_time", "end_time",
        "limit_pct", "status", "trailing_line", "pierces",
    )

    @classmethod
    def _transform_write(cls, row, model_data):
        row["trailing_line"] = json.dumps(model_data.get("trailing_line") or [])
        row["pierces"] = json.dumps(model_data.get("pierces") or [])
        return row

    @classmethod
    def _transform_read(cls, row):
        row["trailing_line"] = json.loads(row.get("trailing_line") or "[]")
        row["pierces"] = json.loads(row.get("pierces") or "[]")
        return row


class CascadeBandRepository(AtomRepository[CascadeBand]):
    TABLE = "atoms_cascade_bands"
    MODEL = CascadeBand
    PRIMARY = ("symbol", "tf", "start_time", "type", "avg_price")
    COLUMNS = (
        "symbol", "tf", "start_time",
        "bottom_price", "top_price", "avg_price",
        "volume", "signal_count", "type",
    )


class RetailStopBandRepository(AtomRepository[RetailStopBand]):
    TABLE = "atoms_retail_stop_bands"
    MODEL = RetailStopBand
    PRIMARY = ("symbol", "tf", "start_time", "type", "avg_price")
    COLUMNS = (
        "symbol", "tf", "start_time",
        "bottom_price", "top_price", "avg_price",
        "volume", "type",
    )


# ════════════════ 聚合 façade：一次注入全部 repo ════════════════


class AtomRepositories:
    """把 22+7 个 repo 打包成一个容器，供 parser/engine 注入。"""

    def __init__(self, db) -> None:
        self.cvd = CvdRepository(db)
        self.imbalance = ImbalanceRepository(db)
        self.inst_vol = InstVolRepository(db)
        self.vwap = VwapRepository(db)
        self.poc_shift = PocShiftRepository(db)
        self.trailing_vwap = TrailingVwapRepository(db)
        self.power_imbalance = PowerImbalanceRepository(db)
        self.trend_exhaustion = TrendExhaustionRepository(db)

        self.smart_money = SmartMoneyRepository(db)
        self.order_blocks = OrderBlockRepository(db)
        self.absolute_zones = AbsoluteZoneRepository(db)
        self.micro_poc = MicroPocRepository(db)
        self.trend_purity = TrendPurityRepository(db)

        self.resonance_events = ResonanceEventRepository(db)
        self.sweep_events = SweepEventRepository(db)

        self.heatmap = HeatmapRepository(db)
        self.vacuum = VacuumRepository(db)
        self.liquidation_fuel = LiquidationFuelRepository(db)
        self.hvn_nodes = HvnNodeRepository(db)
        self.volume_profile = VolumeProfileRepository(db)

        self.time_heatmap = TimeHeatmapRepository(db)
        self.trend_saturation = TrendSaturationRepository(db)

        # V1.1 扩展 7 个
        self.choch_events = ChochEventRepository(db)
        self.roi_segments = RoiSegmentRepository(db)
        self.pain_drawdown = PainDrawdownRepository(db)
        self.time_windows = TimeWindowRepository(db)
        self.dd_tolerance = DdToleranceRepository(db)
        self.cascade_bands = CascadeBandRepository(db)
        self.retail_stop_bands = RetailStopBandRepository(db)


__all__ = [
    "AbsoluteZoneRepository",
    "AtomRepositories",
    "CascadeBandRepository",
    "ChochEventRepository",
    "CvdRepository",
    "DdToleranceRepository",
    "HeatmapRepository",
    "HvnNodeRepository",
    "ImbalanceRepository",
    "InstVolRepository",
    "LiquidationFuelRepository",
    "MicroPocRepository",
    "OrderBlockRepository",
    "PainDrawdownRepository",
    "PocShiftRepository",
    "PowerImbalanceRepository",
    "ResonanceEventRepository",
    "RetailStopBandRepository",
    "RoiSegmentRepository",
    "SmartMoneyRepository",
    "SweepEventRepository",
    "TimeHeatmapRepository",
    "TimeWindowRepository",
    "TrailingVwapRepository",
    "TrendExhaustionRepository",
    "TrendPurityRepository",
    "TrendSaturationRepository",
    "VacuumRepository",
    "VolumeProfileRepository",
    "VwapRepository",
]
