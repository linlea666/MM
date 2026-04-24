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
    CvdPoint,
    HeatmapBand,
    HvnNode,
    ImbalancePoint,
    InstVolPoint,
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


# ════════════════ 聚合 façade：一次注入全部 repo ════════════════


class AtomRepositories:
    """把 22 个 repo 打包成一个容器，供 parser/engine 注入。"""

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


__all__ = [
    "AbsoluteZoneRepository",
    "AtomRepositories",
    "CvdRepository",
    "HeatmapRepository",
    "HvnNodeRepository",
    "ImbalanceRepository",
    "InstVolRepository",
    "LiquidationFuelRepository",
    "MicroPocRepository",
    "OrderBlockRepository",
    "PocShiftRepository",
    "PowerImbalanceRepository",
    "ResonanceEventRepository",
    "SmartMoneyRepository",
    "SweepEventRepository",
    "TimeHeatmapRepository",
    "TrailingVwapRepository",
    "TrendExhaustionRepository",
    "TrendPurityRepository",
    "TrendSaturationRepository",
    "VacuumRepository",
    "VolumeProfileRepository",
    "VwapRepository",
]
