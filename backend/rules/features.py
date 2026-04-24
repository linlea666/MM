"""特征层：从 atoms_* 读一份 ``FeatureSnapshot``。

设计取舍：
1. **只读最近 N 根**：一次 tick 不做全表扫描，所有窗口统一用 ``lookback_bars``。
2. **不做重计算**：原始指标已由 HFD 算好，这里只取用。
3. **派生字段**：提供给 scorer 的"现成事实"（最近斜率 / 绿红占比 / 最近距离 / 刚穿越等），
   让 scorer 保持纯函数、无 SQL。
4. **pydantic 模型**：运行时校验 + 可序列化（Step 4 WebSocket 要直接推前端调试）。

性能目标：30m 单 symbol 单 tf 完整 extract ≤ 50ms（SQLite 本地）。
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.models import (
    AbsoluteZone,
    HeatmapBand,
    HvnNode,
    Kline,
    LiquidationFuelBand,
    LiquiditySweepEvent,
    MicroPocSegment,
    OrderBlock,
    PocShiftPoint,
    PowerImbalancePoint,
    ResonanceEvent,
    SmartMoneySegment,
    TrailingVwapPoint,
    TrendExhaustionPoint,
    TrendPuritySegment,
    TrendSaturationStat,
    VacuumBand,
    VwapPoint,
)
from backend.storage.db import Database

logger = logging.getLogger("rules.features")


# ════════════════════════════════════════════════════════════════════
# FeatureSnapshot：一次 tick 的完整"已知事实"
# ════════════════════════════════════════════════════════════════════


class FeatureSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # ── 锚点 ──
    symbol: str
    tf: str
    anchor_ts: int              # 最新 K 线开盘 ts
    last_price: float

    # ── K 线派生 ──
    atr: float | None = None    # 最近 14 根 ATR（近似）

    # ── 真实价值 / 成本 ──
    vwap_last: float | None = None
    vwap_slope: float | None = None          # (last - first) / first，百分比
    fair_value_delta_pct: float | None = None  # (price - vwap) / vwap
    smart_money_ongoing: SmartMoneySegment | None = None
    smart_money_all: list[SmartMoneySegment] = Field(default_factory=list)
    trailing_vwap_last: TrailingVwapPoint | None = None
    micro_poc_last: MicroPocSegment | None = None
    micro_pocs: list[MicroPocSegment] = Field(default_factory=list)
    trend_purity_last: TrendPuritySegment | None = None

    # ── 动能 / 方向 ──
    cvd_slope: float | None = None           # (last - first)；正 = 买盘累积
    cvd_slope_sign: Literal["up", "down", "flat"] = "flat"
    imbalance_green_ratio: float = 0.0       # 近 N 根 value>0 占比
    imbalance_red_ratio: float = 0.0
    poc_shift_delta_pct: float | None = None  # (last_poc - first_poc) / first_poc
    poc_shift_trend: Literal["up", "down", "flat"] = "flat"
    power_imbalance_last: PowerImbalancePoint | None = None
    trend_exhaustion_last: TrendExhaustionPoint | None = None

    # ── 主力 / 事件 ──
    resonance_count_recent: int = 0
    resonance_buy_count: int = 0
    resonance_sell_count: int = 0
    resonance_recent: list[ResonanceEvent] = Field(default_factory=list)
    sweep_count_recent: int = 0
    sweep_last: LiquiditySweepEvent | None = None
    whale_net_direction: Literal["buy", "sell", "neutral"] = "neutral"

    # ── 关键位原料 ──
    hvn_nodes: list[HvnNode] = Field(default_factory=list)
    absolute_zones: list[AbsoluteZone] = Field(default_factory=list)
    order_blocks: list[OrderBlock] = Field(default_factory=list)
    vacuums: list[VacuumBand] = Field(default_factory=list)
    heatmap: list[HeatmapBand] = Field(default_factory=list)
    liquidation_fuel: list[LiquidationFuelBand] = Field(default_factory=list)

    # ── 饱和 / 时间 ──
    trend_saturation: TrendSaturationStat | None = None
    current_hour_activity: float = 0.0   # time_heatmap 当前 hour 的 total/max
    active_session: bool = False

    # ── 派生：最近关键位 & 穿越 ──
    nearest_support_price: float | None = None
    nearest_support_distance_pct: float | None = None
    nearest_resistance_price: float | None = None
    nearest_resistance_distance_pct: float | None = None
    just_broke_resistance: bool = False
    just_broke_support: bool = False

    # ── 调试用：数据新鲜度 ──
    stale_tables: list[str] = Field(default_factory=list)  # 该 symbol/tf 缺数据的表
    generated_at: int = 0


# ════════════════════════════════════════════════════════════════════
# FeatureExtractor
# ════════════════════════════════════════════════════════════════════


class FeatureExtractor:
    """从 SQLite 的原子表读一份特征快照。

    典型用法：
        extractor = FeatureExtractor(db, config=svc.snapshot())
        snap = await extractor.extract("BTC", "30m")
    """

    def __init__(self, db: Database, *, config: dict[str, Any] | None = None) -> None:
        self._db = db
        cfg_global = (config or {}).get("global", {}) if config else {}
        self._lookback = int(cfg_global.get("lookback_bars", 120))
        self._recent = int(cfg_global.get("recent_window_bars", 8))
        self._near_pct = float(cfg_global.get("near_price_pct", 0.006))

    # ─────────────────────── 主入口 ───────────────────────

    async def extract(self, symbol: str, tf: str) -> FeatureSnapshot | None:
        """读一份快照；若 kline 表里没这个 symbol/tf 的数据，返回 None。"""
        import time

        t0 = time.perf_counter()
        stale: list[str] = []

        # 1) 锚点：最新 kline
        klines = await self._fetch_recent_klines(symbol, tf, self._lookback)
        if not klines:
            logger.warning(
                f"无 K 线可用 {symbol}/{tf}",
                extra={"tags": ["RULES"], "context": {"symbol": symbol, "tf": tf}},
            )
            return None
        last_kline = klines[-1]
        anchor_ts = last_kline.ts
        last_price = last_kline.close
        atr = _estimate_atr(klines, period=14)

        # 2) 时序点类特征
        vwap_points = await self._fetch_points(symbol, tf, "atoms_vwap", ["ts", "vwap"], self._lookback)
        cvd_points = await self._fetch_points(symbol, tf, "atoms_cvd", ["ts", "value"], self._lookback)
        imb_points = await self._fetch_points(symbol, tf, "atoms_imbalance", ["ts", "value"], self._lookback)
        poc_points = await self._fetch_points(symbol, tf, "atoms_poc_shift", ["ts", "poc_price", "volume"], self._lookback)
        if not vwap_points: stale.append("atoms_vwap")
        if not cvd_points: stale.append("atoms_cvd")
        if not imb_points: stale.append("atoms_imbalance")
        if not poc_points: stale.append("atoms_poc_shift")

        # 3) 段式 / 事件 / 价位
        smart_money_all = await self._fetch_smart_money(symbol, tf)
        absolute_zones = await self._fetch_absolute_zones(symbol, tf)
        order_blocks = await self._fetch_order_blocks(symbol, tf)
        micro_pocs = await self._fetch_micro_pocs(symbol, tf)
        trend_purity_last = await self._fetch_latest_trend_purity(symbol, tf)
        resonance_recent = await self._fetch_resonance_recent(symbol, tf, self._recent, anchor_ts, tf_ms=_tf_to_ms(tf))
        sweep_recent = await self._fetch_sweep_recent(symbol, tf, self._recent, anchor_ts, tf_ms=_tf_to_ms(tf))
        hvn_nodes = await self._fetch_hvn_nodes(symbol, tf)
        vacuums = await self._fetch_vacuums(symbol, tf)
        heatmap = await self._fetch_heatmap(symbol, tf)
        liquidation_fuel = await self._fetch_liquidation_fuel(symbol, tf)
        trend_saturation = await self._fetch_trend_saturation(symbol, tf)
        trailing_vwap_last = await self._fetch_latest_trailing_vwap(symbol, tf)
        power_imbalance_last = await self._fetch_latest_power_imbalance(symbol, tf)
        trend_exhaustion_last = await self._fetch_latest_trend_exhaustion(symbol, tf)
        time_heatmap = await self._fetch_time_heatmap(symbol, tf)
        micro_poc_last = micro_pocs[-1] if micro_pocs else None

        # 4) 派生
        vwap_last = vwap_points[-1].vwap if vwap_points else None
        vwap_slope = _slope_pct([p.vwap for p in vwap_points]) if len(vwap_points) >= 2 else None
        fair_value_delta_pct = None
        if vwap_last and vwap_last > 0:
            fair_value_delta_pct = (last_price - vwap_last) / vwap_last

        cvd_slope = None
        cvd_sign: Literal["up", "down", "flat"] = "flat"
        if len(cvd_points) >= 2:
            cvd_slope = cvd_points[-1].value - cvd_points[0].value
            if cvd_slope > 0:
                cvd_sign = "up"
            elif cvd_slope < 0:
                cvd_sign = "down"

        # imbalance 是稀疏事件：大部分 K 线 value=0，占比要按"非零"做分母，
        # 否则静默期被 0 稀释，判定恒为 0。
        imb_window = imb_points[-self._recent:] if imb_points else []
        imb_green = sum(1 for p in imb_window if p.value > 0)
        imb_red = sum(1 for p in imb_window if p.value < 0)
        imb_nonzero = imb_green + imb_red
        imb_denom = imb_nonzero or 1

        poc_trend: Literal["up", "down", "flat"] = "flat"
        poc_delta_pct = None
        if len(poc_points) >= 2:
            first_poc = poc_points[0].poc_price
            last_poc = poc_points[-1].poc_price
            if first_poc > 0:
                poc_delta_pct = (last_poc - first_poc) / first_poc
            if last_poc > first_poc:
                poc_trend = "up"
            elif last_poc < first_poc:
                poc_trend = "down"

        smart_money_ongoing = None
        for seg in reversed(smart_money_all):
            if seg.status == "Ongoing":
                smart_money_ongoing = seg
                break

        sweep_last = sweep_recent[-1] if sweep_recent else None

        buy_count = sum(1 for r in resonance_recent if r.direction == "buy")
        sell_count = sum(1 for r in resonance_recent if r.direction == "sell")
        net_dir: Literal["buy", "sell", "neutral"] = "neutral"
        if buy_count >= sell_count + 2:
            net_dir = "buy"
        elif sell_count >= buy_count + 2:
            net_dir = "sell"

        cur_hour_activity, active_session = _time_activity(time_heatmap, anchor_ts, threshold=0.5)

        # 5) 最近关键位 & 刚穿越判定
        (
            near_s_price, near_s_dist,
            near_r_price, near_r_dist,
            broke_r, broke_s,
        ) = _nearest_levels_and_pierce(
            last_price=last_price,
            klines=klines,
            recent_window=self._recent,
            hvn_nodes=hvn_nodes,
            absolute_zones=absolute_zones,
            order_blocks=order_blocks,
            micro_pocs=micro_pocs,
        )

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        snap = FeatureSnapshot(
            symbol=symbol,
            tf=tf,
            anchor_ts=anchor_ts,
            last_price=last_price,
            atr=atr,
            vwap_last=vwap_last,
            vwap_slope=vwap_slope,
            fair_value_delta_pct=fair_value_delta_pct,
            smart_money_ongoing=smart_money_ongoing,
            smart_money_all=smart_money_all,
            trailing_vwap_last=trailing_vwap_last,
            micro_poc_last=micro_poc_last,
            micro_pocs=micro_pocs,
            trend_purity_last=trend_purity_last,
            cvd_slope=cvd_slope,
            cvd_slope_sign=cvd_sign,
            imbalance_green_ratio=(imb_green / imb_denom) if imb_nonzero else 0.0,
            imbalance_red_ratio=(imb_red / imb_denom) if imb_nonzero else 0.0,
            poc_shift_delta_pct=poc_delta_pct,
            poc_shift_trend=poc_trend,
            power_imbalance_last=power_imbalance_last,
            trend_exhaustion_last=trend_exhaustion_last,
            resonance_count_recent=len(resonance_recent),
            resonance_buy_count=buy_count,
            resonance_sell_count=sell_count,
            resonance_recent=resonance_recent,
            sweep_count_recent=len(sweep_recent),
            sweep_last=sweep_last,
            whale_net_direction=net_dir,
            hvn_nodes=hvn_nodes,
            absolute_zones=absolute_zones,
            order_blocks=order_blocks,
            vacuums=vacuums,
            heatmap=heatmap,
            liquidation_fuel=liquidation_fuel,
            trend_saturation=trend_saturation,
            current_hour_activity=cur_hour_activity,
            active_session=active_session,
            nearest_support_price=near_s_price,
            nearest_support_distance_pct=near_s_dist,
            nearest_resistance_price=near_r_price,
            nearest_resistance_distance_pct=near_r_dist,
            just_broke_resistance=broke_r,
            just_broke_support=broke_s,
            stale_tables=stale,
            generated_at=anchor_ts,
        )
        logger.debug(
            f"features {symbol}/{tf} ok {elapsed_ms}ms stale={stale}",
            extra={"tags": ["RULES"], "context": {"symbol": symbol, "tf": tf, "elapsed_ms": elapsed_ms}},
        )
        return snap

    # ─────────────────────── 取数辅助 ───────────────────────

    async def _fetch_recent_klines(self, symbol: str, tf: str, n: int) -> list[Kline]:
        rows = await self._db.fetchall(
            "SELECT symbol, tf, ts, open, high, low, close, volume, source "
            "FROM atoms_klines WHERE symbol=? AND tf=? "
            "ORDER BY ts DESC LIMIT ?",
            (symbol, tf, n),
        )
        # 反转成 ASC
        return [Kline(**dict(r)) for r in reversed(rows)]

    async def _fetch_points(
        self, symbol: str, tf: str, table: str, cols: list[str], n: int
    ) -> list:
        cols_sql = ", ".join(cols)
        rows = await self._db.fetchall(
            f"SELECT {cols_sql} FROM {table} WHERE symbol=? AND tf=? "
            f"ORDER BY ts DESC LIMIT ?",
            (symbol, tf, n),
        )
        # 映射到对应 Pydantic model
        cls_map = {
            "atoms_vwap": VwapPoint,
            "atoms_cvd": _CvdLite,
            "atoms_imbalance": _ImbLite,
            "atoms_poc_shift": PocShiftPoint,
        }
        cls = cls_map[table]
        out = []
        for r in reversed(rows):
            d = dict(r)
            d["symbol"] = symbol
            d["tf"] = tf
            out.append(cls(**d))
        return out

    async def _fetch_smart_money(self, symbol: str, tf: str) -> list[SmartMoneySegment]:
        rows = await self._db.fetchall(
            "SELECT symbol, tf, start_time, end_time, avg_price, type, status "
            "FROM atoms_smart_money WHERE symbol=? AND tf=? ORDER BY start_time ASC",
            (symbol, tf),
        )
        return [SmartMoneySegment(**dict(r)) for r in rows]

    async def _fetch_absolute_zones(self, symbol: str, tf: str) -> list[AbsoluteZone]:
        rows = await self._db.fetchall(
            "SELECT symbol, tf, start_time, bottom_price, top_price, type "
            "FROM atoms_absolute_zones WHERE symbol=? AND tf=? ORDER BY start_time ASC",
            (symbol, tf),
        )
        return [AbsoluteZone(**dict(r)) for r in rows]

    async def _fetch_order_blocks(self, symbol: str, tf: str) -> list[OrderBlock]:
        rows = await self._db.fetchall(
            "SELECT symbol, tf, start_time, avg_price, volume, type "
            "FROM atoms_order_blocks WHERE symbol=? AND tf=? ORDER BY start_time ASC",
            (symbol, tf),
        )
        return [OrderBlock(**dict(r)) for r in rows]

    async def _fetch_micro_pocs(self, symbol: str, tf: str) -> list[MicroPocSegment]:
        rows = await self._db.fetchall(
            "SELECT symbol, tf, start_time, end_time, poc_price, volume, type "
            "FROM atoms_micro_poc WHERE symbol=? AND tf=? ORDER BY start_time ASC",
            (symbol, tf),
        )
        return [MicroPocSegment(**dict(r)) for r in rows]

    async def _fetch_latest_trend_purity(
        self, symbol: str, tf: str
    ) -> TrendPuritySegment | None:
        row = await self._db.fetchone(
            "SELECT symbol, tf, start_time, end_time, avg_price, buy_vol, sell_vol, "
            "total_vol, purity, type FROM atoms_trend_purity "
            "WHERE symbol=? AND tf=? ORDER BY start_time DESC LIMIT 1",
            (symbol, tf),
        )
        return TrendPuritySegment(**dict(row)) if row else None

    async def _fetch_resonance_recent(
        self, symbol: str, tf: str, n: int, anchor_ts: int, tf_ms: int
    ) -> list[ResonanceEvent]:
        import json

        start_ts = anchor_ts - (n * tf_ms)
        rows = await self._db.fetchall(
            "SELECT symbol, tf, ts, price, direction, count, exchanges "
            "FROM atoms_resonance_events "
            "WHERE symbol=? AND tf=? AND ts >= ? ORDER BY ts ASC",
            (symbol, tf, start_ts),
        )
        out: list[ResonanceEvent] = []
        for r in rows:
            d = dict(r)
            raw = d.get("exchanges") or "[]"
            if isinstance(raw, str):
                try:
                    d["exchanges"] = json.loads(raw)
                except json.JSONDecodeError:
                    d["exchanges"] = []
            out.append(ResonanceEvent(**d))
        return out

    async def _fetch_sweep_recent(
        self, symbol: str, tf: str, n: int, anchor_ts: int, tf_ms: int
    ) -> list[LiquiditySweepEvent]:
        start_ts = anchor_ts - (n * tf_ms)
        rows = await self._db.fetchall(
            "SELECT symbol, tf, ts, price, type, volume FROM atoms_sweep_events "
            "WHERE symbol=? AND tf=? AND ts >= ? ORDER BY ts ASC",
            (symbol, tf, start_ts),
        )
        return [LiquiditySweepEvent(**dict(r)) for r in rows]

    async def _fetch_hvn_nodes(self, symbol: str, tf: str) -> list[HvnNode]:
        rows = await self._db.fetchall(
            "SELECT symbol, tf, rank, price, volume FROM atoms_hvn_nodes "
            "WHERE symbol=? AND tf=? ORDER BY rank ASC",
            (symbol, tf),
        )
        return [HvnNode(**dict(r)) for r in rows]

    async def _fetch_vacuums(self, symbol: str, tf: str) -> list[VacuumBand]:
        rows = await self._db.fetchall(
            "SELECT symbol, tf, low, high FROM atoms_vacuum WHERE symbol=? AND tf=? "
            "ORDER BY low ASC",
            (symbol, tf),
        )
        return [VacuumBand(**dict(r)) for r in rows]

    async def _fetch_heatmap(self, symbol: str, tf: str) -> list[HeatmapBand]:
        rows = await self._db.fetchall(
            "SELECT symbol, tf, start_time, price, intensity, type FROM atoms_heatmap "
            "WHERE symbol=? AND tf=? ORDER BY price ASC",
            (symbol, tf),
        )
        return [HeatmapBand(**dict(r)) for r in rows]

    async def _fetch_liquidation_fuel(
        self, symbol: str, tf: str
    ) -> list[LiquidationFuelBand]:
        rows = await self._db.fetchall(
            "SELECT symbol, tf, bottom, top, fuel FROM atoms_liquidation_fuel "
            "WHERE symbol=? AND tf=? ORDER BY bottom ASC",
            (symbol, tf),
        )
        return [LiquidationFuelBand(**dict(r)) for r in rows]

    async def _fetch_trend_saturation(
        self, symbol: str, tf: str
    ) -> TrendSaturationStat | None:
        row = await self._db.fetchone(
            "SELECT symbol, tf, type, start_time, avg_vol, current_vol, progress "
            "FROM atoms_trend_saturation WHERE symbol=? AND tf=?",
            (symbol, tf),
        )
        return TrendSaturationStat(**dict(row)) if row else None

    async def _fetch_latest_trailing_vwap(
        self, symbol: str, tf: str
    ) -> TrailingVwapPoint | None:
        row = await self._db.fetchone(
            "SELECT symbol, tf, ts, resistance, support FROM atoms_trailing_vwap "
            "WHERE symbol=? AND tf=? ORDER BY ts DESC LIMIT 1",
            (symbol, tf),
        )
        return TrailingVwapPoint(**dict(row)) if row else None

    async def _fetch_latest_power_imbalance(
        self, symbol: str, tf: str
    ) -> PowerImbalancePoint | None:
        # 大部分 K 线 ratio=0；取最近一个 **非零** 的
        row = await self._db.fetchone(
            "SELECT symbol, tf, ts, buy_vol, sell_vol, ratio "
            "FROM atoms_power_imbalance "
            "WHERE symbol=? AND tf=? AND ratio != 0 "
            "ORDER BY ts DESC LIMIT 1",
            (symbol, tf),
        )
        return PowerImbalancePoint(**dict(row)) if row else None

    async def _fetch_latest_trend_exhaustion(
        self, symbol: str, tf: str
    ) -> TrendExhaustionPoint | None:
        row = await self._db.fetchone(
            "SELECT symbol, tf, ts, exhaustion, type FROM atoms_trend_exhaustion "
            "WHERE symbol=? AND tf=? ORDER BY ts DESC LIMIT 1",
            (symbol, tf),
        )
        return TrendExhaustionPoint(**dict(row)) if row else None

    async def _fetch_time_heatmap(self, symbol: str, tf: str) -> dict[int, float]:
        rows = await self._db.fetchall(
            "SELECT hour, total FROM atoms_time_heatmap WHERE symbol=? AND tf=?",
            (symbol, tf),
        )
        return {int(r["hour"]): float(r["total"]) for r in rows}


# ════════════════════════════════════════════════════════════════════
# 小辅助
# ════════════════════════════════════════════════════════════════════


class _CvdLite(BaseModel):
    """Cvd 数据可能没 symbol/tf（我们用 lightweight 版本）。"""

    model_config = ConfigDict(extra="ignore")
    ts: int
    value: float


class _ImbLite(BaseModel):
    model_config = ConfigDict(extra="ignore")
    ts: int
    value: float


_TF_MS = {
    "1m": 60_000,
    "3m": 3 * 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "30m": 30 * 60_000,
    "1h": 60 * 60_000,
    "2h": 2 * 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "6h": 6 * 60 * 60_000,
    "12h": 12 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
}


def _tf_to_ms(tf: str) -> int:
    return _TF_MS.get(tf, 30 * 60_000)


def _estimate_atr(klines: list[Kline], *, period: int = 14) -> float | None:
    """简化 ATR：最近 N 根 high-low 的均值（不用真 TR，但用于规则足够）。"""
    if not klines:
        return None
    window = klines[-period:]
    if not window:
        return None
    return sum(k.high - k.low for k in window) / len(window)


def _slope_pct(values: list[float]) -> float | None:
    """简化斜率：(last - first) / first。"""
    if len(values) < 2:
        return None
    first = values[0]
    if first == 0:
        return None
    return (values[-1] - first) / abs(first)


def _time_activity(
    heatmap: dict[int, float], anchor_ts: int, *, threshold: float = 0.5
) -> tuple[float, bool]:
    """返回 (当前小时活跃度[0-1], 是否活跃段)。"""
    if not heatmap:
        return 0.0, False
    mx = max(heatmap.values()) or 1.0
    # anchor_ts 转 UTC 小时
    import datetime as _dt

    hour = _dt.datetime.fromtimestamp(anchor_ts / 1000, tz=_dt.UTC).hour
    cur = heatmap.get(hour, 0.0) / mx
    return cur, cur >= threshold


def _nearest_levels_and_pierce(
    *,
    last_price: float,
    klines: list[Kline],
    recent_window: int,
    hvn_nodes: list[HvnNode],
    absolute_zones: list[AbsoluteZone],
    order_blocks: list[OrderBlock],
    micro_pocs: list[MicroPocSegment],
) -> tuple[float | None, float | None, float | None, float | None, bool, bool]:
    """汇总候选价位 → 找上下最近一档 → 判断最近 N 根是否刚穿越。"""
    candidates: list[float] = []
    for h in hvn_nodes:
        candidates.append(h.price)
    for a in absolute_zones:
        candidates.append(a.bottom_price)
        candidates.append(a.top_price)
    for o in order_blocks:
        candidates.append(o.avg_price)
    for m in micro_pocs:
        candidates.append(m.poc_price)

    supports = [p for p in candidates if p < last_price]
    resistances = [p for p in candidates if p > last_price]

    nearest_s = max(supports) if supports else None
    nearest_r = min(resistances) if resistances else None
    near_s_dist = (last_price - nearest_s) / last_price if nearest_s else None
    near_r_dist = (nearest_r - last_price) / last_price if nearest_r else None

    # 穿越检测：遍历 **所有候选价位**（不按当前分类过滤），
    # 因为一个被刚刚从下向上穿越的价位，即使当前已变 support，依然应该
    # 触发 "just broke resistance"（反之亦然）。
    broke_r = False
    broke_s = False
    if len(klines) >= 2 and candidates:
        for prev, cur in zip(klines[-recent_window:-1], klines[-recent_window + 1:]):
            for level in candidates:
                if prev.close < level <= cur.close:
                    broke_r = True
                if prev.close > level >= cur.close:
                    broke_s = True
            if broke_r and broke_s:
                break

    return (nearest_s, near_s_dist, nearest_r, near_r_dist, broke_r, broke_s)


__all__ = [
    "FeatureExtractor",
    "FeatureSnapshot",
]
