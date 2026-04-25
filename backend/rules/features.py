"""特征层：从 atoms_* 读一份 ``FeatureSnapshot``。

设计取舍：
1. **双窗口**：
   - ``lookback_bars``（默认 120）—— "结构"窗：CVD/VWAP/POC 斜率这类"要稳"的趋势特征。
   - ``recent_window_bars``（默认 8）—— "事件"窗：共振 / 猎杀 / imbalance 绿红占比这类
     "要快"的短期行为。
   两套窗口的语义差异在每个 evidence 的 note / label 里都显式标注，避免前端误读。
   另有独立的小窗 ``exhaustion_window_bars`` / ``power_imbalance_window_bars``（默认 3），
   对应官方"连续 3 根"硬口径。
2. **不做重计算**：原始指标已由 HFD 算好，这里只取用。
3. **派生字段**：提供给 scorer 的"现成事实"（斜率 / 占比 / 距离 / 刚穿越 / 连续 streak 等），
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
    CascadeBand,
    ChochEvent,
    DdToleranceSegment,
    HeatmapBand,
    HvnNode,
    Kline,
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
    TimeWindowSegment,
    TrailingVwapPoint,
    TrendExhaustionPoint,
    TrendPuritySegment,
    TrendSaturationStat,
    VacuumBand,
    VolumeProfileBucket,
    VwapPoint,
)
from backend.storage.db import Database

logger = logging.getLogger("rules.features")


# ════════════════════════════════════════════════════════════════════
# V1.1 派生视图：数字化 + 白话化的指标投影（直接给前端 / AI 读）
# ════════════════════════════════════════════════════════════════════


class ChochLatestView(BaseModel):
    """⚡ 机构破坏/突破事件的数字化视图。

    对应官方 inst_choch 的"真金白银砸穿前高/前低"—— 用于驱动大屏 ⚡ 角标 + AI 观察。
    """

    model_config = ConfigDict(extra="forbid")

    ts: int                 # 事件触发时间
    price: float            # 触发价
    level_price: float      # 被砸穿的前高/前低
    origin_ts: int          # 该前高/前低的形成时间
    type: str               # 原始标签：CHoCH_Bullish / CHoCH_Bearish / BOS_Bullish / BOS_Bearish
    kind: Literal["CHoCH", "BOS"]
    direction: Literal["bullish", "bearish"]
    is_choch: bool
    distance_pct: float     # (level_price - last_price) / last_price（带正负，+ = 在上方）
    bars_since: int         # 距当前 anchor 多少根 K 线


class BandView(BaseModel):
    """💣 爆仓带 / 散户止损带 的统一数字化视图。

    `side` 的白话口径：
      - ``long_fuel``  —— 多头燃料（下方红带，Accumulation 语义）
      - ``short_fuel`` —— 空头燃料（上方绿带，Distribution 语义）
    `above_price` 独立记录价位实际相对位置（一般 long_fuel 在下、short_fuel 在上，
    但价格异常穿越时两者可以不一致，保留原始事实供 scorer/AI 判断）。
    """

    model_config = ConfigDict(extra="forbid")

    start_time: int
    avg_price: float
    top_price: float
    bottom_price: float
    volume: float
    type: str               # 原始 Accumulation / Distribution
    side: Literal["long_fuel", "short_fuel"]
    above_price: bool       # 带是否在当前价上方
    distance_pct: float     # (avg_price - last_price) / last_price（带正负）
    signal_count: int | None = None     # cascade 专有（💣 强度），retail 无


class SegmentPortrait(BaseModel):
    """波段四维 JOIN 画像（best_effort：ROI / Pain / Time / DdTolerance 任意 1-4 维都出）。

    锚点策略：
      1. 以 Ongoing 状态 + start_time 最大 的段作为主锚点；
      2. ROI / Pain / Time 三张表共享 (start_time, type) 主键，JOIN 同锚；
      3. DdTolerance 主键用官方 id，关联策略：以 (status=Ongoing, end_time 最新) 的 dd 段挂靠；
      4. 任一维度缺失，对应字段留 None，通过 ``sources`` 字段声明"哪几维有数据"。
    """

    model_config = ConfigDict(extra="forbid")

    start_time: int | None = None
    type: str | None = None                    # Accumulation / Distribution
    status: str | None = None                  # Ongoing / Ended

    # ROI 维度（"还能走多远"）
    roi_avg_price: float | None = None         # 波段平均价（锚）
    roi_limit_avg_price: float | None = None   # 平均目标价（粗虚线）
    roi_limit_max_price: float | None = None   # 极限目标价（亮色实线）

    # Pain 维度（洗盘容忍深度）
    pain_avg_price: float | None = None        # 半透明带（洗盘容忍）
    pain_max_price: float | None = None        # 实线极限防线

    # Time 维度（时间死亡线）
    time_avg_ts: int | None = None             # 平均寿命虚线（ms epoch）
    time_max_ts: int | None = None             # 死亡线实线（ms epoch）
    bars_to_avg: int | None = None             # 距离 avg 虚线还有几根（<0 已越过）
    bars_to_max: int | None = None             # 距离死亡线还有几根（<0 已越过）

    # DdTolerance 维度（移动护城河）
    dd_limit_pct: float | None = None          # 允许的最大回撤比例
    dd_trailing_current: float | None = None   # 当前护城河价位（trailing_line 最新一点）
    dd_pierce_count: int = 0                   # 📌 黄色图钉刺穿次数

    sources: list[Literal["roi", "pain", "time", "dd_tolerance"]] = Field(default_factory=list)


class VolumeProfileNode(BaseModel):
    """筹码分布单桶（价位 + 成交细节）的派生视图。

    与 ``VolumeProfileBucket`` 一一对应，但保证字段命名与前端/AI 口径一致
    （不直接 re-export atom，避免后续 atom schema 演进波及 UI）。
    """

    model_config = ConfigDict(extra="forbid")

    price: float
    accum: float              # 主动买量
    dist: float               # 主动卖量
    total: float              # 总成交量
    dominant_side: Literal["buy", "sell", "balanced"]
    purity_ratio: float       # abs(accum-dist)/total，越高越"纯"


class VolumeProfileView(BaseModel):
    """Volume Profile 的数字化视图（给前端/AI 直接读）。

    关键字段：
      - ``poc_price``：换手量最大价位（Point of Control，筹码峰的峰顶）
      - ``value_area_low/high``：覆盖 70% 总量的价格区间（机构主力换手区）
      - ``last_price_position``：当前价相对 VA 的位置，驱动作战判断
      - ``top_nodes``：TopN 筹码峰（默认 5 个，按 total 降序）
    """

    model_config = ConfigDict(extra="forbid")

    poc_price: float
    poc_total: float
    value_area_low: float
    value_area_high: float
    value_area_volume_ratio: float       # 实际覆盖比例（接近 0.70）
    total_volume: float
    last_price_position: Literal["below_va", "in_va", "above_va"]
    poc_distance_pct: float              # (poc_price - last_price) / last_price
    top_nodes: list[VolumeProfileNode] = Field(default_factory=list)


class TimeHeatmapView(BaseModel):
    """资金时间热力图（24 小时活跃度）的数字化视图。

    解决原 ``current_hour_activity`` 只有一个标量、无法判断"高柱/低柱时段"
    的缺陷。Phase 9 Layer 2 用 ``peak_hours / dead_hours`` 做"主力上下班"
    过滤，避免垃圾时间的假突破被高估。
    """

    model_config = ConfigDict(extra="forbid")

    current_hour: int                    # 当前 UTC 小时（0-23）
    current_activity: float              # 当前小时活跃度（相对峰值归一化 0-1）
    current_rank: int                    # 当前小时活跃度排名（1=最高，24=最低）
    peak_hours: list[int] = Field(default_factory=list)     # 活跃度 TopN 小时
    dead_hours: list[int] = Field(default_factory=list)     # 活跃度 Bottom N 小时
    is_active_session: bool              # current_activity ≥ 阈值


# ── V1.1 · Step 7 · 动能能量柱 + 目标投影 ─────────────────────────

class ContribItem(BaseModel):
    """单条证据贡献（前端 tooltip 用）。

    `side` 表示该贡献分计入哪一侧得分：
      - ``long``  仅累加到 ``score_long``
      - ``short`` 仅累加到 ``score_short``
      - ``both``  双侧都加（极少；目前没用到，预留）
      - ``none``  仅信息展示，不计分
    """

    model_config = ConfigDict(extra="forbid")

    label: str           # 例 "power_imbalance" / "cvd_slope"
    value: str           # 原始值文本，例 "ratio=2.40 streak=3"
    delta: int           # 该分量贡献分（带正负，便于 UI 推导）
    side: Literal["long", "short", "both", "none"]


class OverrideEvent(BaseModel):
    """事件抢跑：CHoCH / Sweep / Pierce 在最近 N 根内触发的反向/同向警告。

    抢跑事件 **只在 UI 闪电高亮**，不强行翻转 score 主方向；保留双信号留给
    用户/AI 判断（详见 MOMENTUM-PULSE.md §2.4 铁律）。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["CHoCH", "BOS", "Sweep", "Pierce"]
    direction: Literal["bullish", "bearish"]
    bars_since: int                  # 距 anchor 几根（≥0）
    detail: str                      # 白话："⚡ CHoCH↑ 破 93,800 · 3 根前"


class MomentumPulseView(BaseModel):
    """动能能量柱视图（Card A）。

    口径：``score_long`` / ``score_short`` 各自独立 0~100，**不互减不归一**，
    UI 同时展示两条柱（多空可同时存在 / 同时为弱）。``dominant_side`` 仅在
    两侧差距 ≥ ``min_dominant_gap`` 时才给出方向，否则 ``neutral``。
    """

    model_config = ConfigDict(extra="forbid")

    score_long: int                  # 0~100
    score_short: int                 # 0~100
    dominant_side: Literal["long", "short", "neutral"]
    streak_bars: int                 # 主导侧的 power_imbalance 同向连续根数
    streak_side: Literal["buy", "sell", "none"]
    fatigue_state: Literal["fresh", "mid", "exhausted"]
    fatigue_decay: float             # 0~1，confidence 折扣（exhausted=最大）
    override: OverrideEvent | None = None
    contributions: list[ContribItem] = Field(default_factory=list)
    note: str = ""                   # 一句话白话（"多头烧油 65 / 空头 12 · streak 3 · fresh"）


class TargetItem(BaseModel):
    """目标投影中的单个磁吸价位（Card B 的一条）。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "roi", "pain", "cascade_band", "heatmap", "vacuum", "nearest_level"
    ]
    side: Literal["above", "below"]
    tier: Literal["T1", "T2"]
    price: float
    distance_pct: float              # 带正负（above 为正 / below 为负）
    confidence: float                # 0~1
    bars_to_arrive: int | None       # |Δprice| / atr 估算；ATR 缺则 None
    evidence: str                    # 白话来源说明


class TargetProjectionView(BaseModel):
    """目标投影视图（Card B）。

    `above` / `below` 已按 |distance_pct| 升序排序（近的在前）。
    `note` 写死「磁吸价位地图，不构成预测」用于 UI 角标，避免被误读。
    """

    model_config = ConfigDict(extra="forbid")

    above: list[TargetItem] = Field(default_factory=list)
    below: list[TargetItem] = Field(default_factory=list)
    max_distance_pct: float          # 截断阈值（来自配置）
    note: str = "📍 目标 = 磁吸价位地图，不构成预测"


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
    # cvd 用结构窗 lookback_bars：趋势指标，需"稳"不需"快"。
    cvd_slope: float | None = None           # lookback 窗口内 (last - first)；正 = 买盘累积
    cvd_slope_sign: Literal["up", "down", "flat"] = "flat"
    cvd_range: float | None = None           # lookback 窗口 max(cvd) - min(cvd)（跨币种归一化基准）
    cvd_converge_ratio: float | None = None  # |cvd_slope| / cvd_range，越小越收敛；≈0 表示多空完全对冲
    # imbalance 用事件窗 recent_window_bars：短期行为占比。
    imbalance_green_ratio: float = 0.0       # 事件窗内 value>0 占比（过滤零值后）
    imbalance_red_ratio: float = 0.0
    # 动能一致性：综合 imbalance + cvd 方向，给 OnePass / scorer 用一个标签
    # 直接判定"两者一致 vs 互相打架"。常见组合：
    #   agree_up    —— imbalance 偏绿 + cvd 上行
    #   agree_down  —— imbalance 偏红 + cvd 下行
    #   conflict    —— 两者方向相反（口径冲突，应警惕假信号 / 数据 stale）
    #   neutral     —— 任一为空 / 无明显方向
    momentum_consistency: Literal["agree_up", "agree_down", "conflict", "neutral"] = "neutral"
    poc_shift_delta_pct: float | None = None  # lookback 窗首尾 poc 百分比变化（结构窗）
    poc_shift_trend: Literal["up", "down", "flat"] = "flat"

    # power_imbalance / trend_exhaustion 官方口径都是 "近 3 根连续" 判定
    # （docs/upstream-api/endpoints/power_imbalance.md + trend_exhaustion.md）。
    # 所以既保留最新一条（沿用旧字段），也给出窗口序列 + streak 统计。
    power_imbalance_last: PowerImbalancePoint | None = None
    power_imbalance_recent: list[PowerImbalancePoint] = Field(default_factory=list)
    power_imbalance_streak: int = 0                         # 近窗从新→旧连续 |ratio|≥阈值 的根数
    power_imbalance_streak_side: Literal["buy", "sell", "none"] = "none"

    trend_exhaustion_last: TrendExhaustionPoint | None = None
    trend_exhaustion_recent: list[TrendExhaustionPoint] = Field(default_factory=list)
    exhaustion_streak: int = 0                              # 近窗从新→旧连续 exhaustion≥阈值 的根数
    exhaustion_streak_type: Literal["Accumulation", "Distribution", "none"] = "none"

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
    current_hour_activity: float = 0.0   # time_heatmap 当前 hour 的 total/max（保留旧字段 · 向后兼容）
    active_session: bool = False         # current_hour_activity ≥ 阈值（保留旧字段 · 向后兼容）

    # ── V1.1 · Stage 0 沉睡资产激活 ──
    # 筹码分布：POC + Value Area + TopN 峰，给 AI Layer 2 的"主力动向"喂料。
    volume_profile: VolumeProfileView | None = None
    # 时间热力图 24h：peak/dead 小时分布，过滤"垃圾时间"假突破。
    time_heatmap_view: TimeHeatmapView | None = None

    # ── 派生：最近关键位 & 穿越 ──
    nearest_support_price: float | None = None
    nearest_support_distance_pct: float | None = None
    nearest_resistance_price: float | None = None
    nearest_resistance_distance_pct: float | None = None
    just_broke_resistance: bool = False
    just_broke_support: bool = False
    pierce_atr_ratio: float | None = None   # 最近穿越幅度 / ATR（无穿越 → None）
    pierce_recovered: bool = False          # 最近 sweep/穿越后，K 线在 liq_recover_bars 内回到带内

    # ── V1.1 扩展（7 个新指标 → 数字化视图）──
    # 事件型：⚡ 机构破坏/突破
    choch_latest: ChochLatestView | None = None
    choch_recent: list[ChochLatestView] = Field(default_factory=list)
    # 价位带：💣 爆仓带 / 散户止损带（按强度 TopN 排序，TopN 由 global.band_topn 控制）
    cascade_bands: list[BandView] = Field(default_factory=list)
    retail_stop_bands: list[BandView] = Field(default_factory=list)
    # 波段四维 JOIN 画像（ROI / Pain / Time / DdTolerance，best_effort）
    segment_portrait: SegmentPortrait | None = None

    # ── V1.1 · Step 7 · 动能能量柱 + 目标投影（基于上述字段派生） ──
    momentum_pulse: MomentumPulseView | None = None
    target_projection: TargetProjectionView | None = None

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
        # 官方文档里"近 3 根"类硬口径：留成配置项，默认 3。
        self._exhaustion_window = int(cfg_global.get("exhaustion_window_bars", 3))
        self._power_imbalance_window = int(cfg_global.get("power_imbalance_window_bars", 3))
        # V1.1：爆仓带 / 散户止损带 TopN（多空各取 N），默认 5 覆盖主要战场。
        self._band_topn = int(cfg_global.get("band_topn", 5))
        # 给 features 层暴露一份 cfg，便于读取 scorer 侧阈值（exhaustion_alert 等）
        self._cfg = config or {}

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
        # power_imbalance / trend_exhaustion 按"近 N 根"窗口拉序列（ASC）
        power_imbalance_recent = await self._fetch_recent_power_imbalance(
            symbol, tf, self._power_imbalance_window
        )
        power_imbalance_last = (
            # 保留旧语义：窗口内最近一条非零；全为 0 则 None。
            next(
                (p for p in reversed(power_imbalance_recent) if p.ratio != 0),
                None,
            )
        )
        # 事实 stale：拉到的近 N 根 buy/sell/ratio 全为 0，等价"无数据"，
        # 显式加进 stale_tables 让 OnePass / 前端做降级处理（避免被误读为"无失衡"
        # = "动能枯竭"，这两者下游含义完全不同）。
        if power_imbalance_recent and all(
            p.buy_vol == 0 and p.sell_vol == 0 and p.ratio == 0
            for p in power_imbalance_recent
        ):
            if "atoms_power_imbalance" not in stale:
                stale.append("atoms_power_imbalance")
        trend_exhaustion_recent = await self._fetch_recent_trend_exhaustion(
            symbol, tf, self._exhaustion_window
        )
        trend_exhaustion_last = (
            trend_exhaustion_recent[-1] if trend_exhaustion_recent else None
        )
        if trend_exhaustion_recent and all(
            p.exhaustion == 0 for p in trend_exhaustion_recent
        ):
            if "atoms_trend_exhaustion" not in stale:
                stale.append("atoms_trend_exhaustion")
        time_heatmap = await self._fetch_time_heatmap(symbol, tf)
        volume_profile_buckets = await self._fetch_volume_profile(symbol, tf)
        micro_poc_last = micro_pocs[-1] if micro_pocs else None

        # 4) 派生
        vwap_last = vwap_points[-1].vwap if vwap_points else None
        vwap_slope = _slope_pct([p.vwap for p in vwap_points]) if len(vwap_points) >= 2 else None
        fair_value_delta_pct = None
        if vwap_last and vwap_last > 0:
            fair_value_delta_pct = (last_price - vwap_last) / vwap_last

        cvd_slope = None
        cvd_sign: Literal["up", "down", "flat"] = "flat"
        cvd_range: float | None = None
        cvd_converge_ratio: float | None = None
        if len(cvd_points) >= 2:
            cvd_slope = cvd_points[-1].value - cvd_points[0].value
            if cvd_slope > 0:
                cvd_sign = "up"
            elif cvd_slope < 0:
                cvd_sign = "down"
            # 用窗口内 max-min 作为归一化基准，口径跨币种/跨 tf 可比。
            # range=0 说明 cvd 完全横盘（也是收敛），此时 converge_ratio=0。
            vals = [p.value for p in cvd_points]
            cvd_range = max(vals) - min(vals)
            if cvd_range > 0:
                cvd_converge_ratio = abs(cvd_slope) / cvd_range
            else:
                cvd_converge_ratio = 0.0

        # imbalance 是稀疏事件：大部分 K 线 value=0，占比要按"非零"做分母，
        # 否则静默期被 0 稀释，判定恒为 0。
        imb_window = imb_points[-self._recent:] if imb_points else []
        imb_green = sum(1 for p in imb_window if p.value > 0)
        imb_red = sum(1 for p in imb_window if p.value < 0)
        imb_nonzero = imb_green + imb_red
        imb_denom = imb_nonzero or 1
        green_ratio = (imb_green / imb_denom) if imb_nonzero else 0.0
        red_ratio = (imb_red / imb_denom) if imb_nonzero else 0.0

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

        active_threshold = float(
            self._cfg.get("participation", {})
                     .get("active_session_threshold", 0.5)
            if isinstance(self._cfg, dict) else 0.5
        )
        time_heatmap_view = _derive_time_heatmap_view(
            time_heatmap, anchor_ts, active_threshold=active_threshold
        )
        # 保留旧字段口径（current_hour_activity / active_session）：多处 module/test
        # 直接读这俩标量，暂不拆迁；新模块一律从 time_heatmap_view 取。
        cur_hour_activity, active_session = _time_activity(
            time_heatmap, anchor_ts, threshold=active_threshold
        )

        vp_topn = int(
            self._cfg.get("features", {})
                     .get("volume_profile_topn", 5)
            if isinstance(self._cfg, dict) else 5
        )
        va_ratio = float(
            self._cfg.get("features", {})
                     .get("volume_profile_va_ratio", 0.70)
            if isinstance(self._cfg, dict) else 0.70
        )
        volume_profile_view = _derive_volume_profile_view(
            volume_profile_buckets, last_price, va_ratio=va_ratio, top_n=vp_topn
        )

        # 5) 最近关键位 & 刚穿越判定 + 穿越幅度 + sweep 回收
        (
            near_s_price, near_s_dist,
            near_r_price, near_r_dist,
            broke_r, broke_s,
            pierce_magnitude,
            pierce_ref_level,
        ) = _nearest_levels_and_pierce(
            last_price=last_price,
            klines=klines,
            recent_window=self._recent,
            hvn_nodes=hvn_nodes,
            absolute_zones=absolute_zones,
            order_blocks=order_blocks,
            micro_pocs=micro_pocs,
            anchor_ts=anchor_ts,
            atr=atr,
        )
        pierce_atr_ratio = None
        if pierce_magnitude is not None and atr and atr > 0:
            pierce_atr_ratio = pierce_magnitude / atr

        # 6) power_imbalance 连续 N 根 streak（同向）
        pi_extreme = float(
            self._cfg.get("participation", {}).get("power_imbalance_extreme", 2.5)
            if isinstance(self._cfg, dict) else 2.5
        )
        pi_streak, pi_side = _streak_same_side_power_imbalance(
            power_imbalance_recent, threshold=pi_extreme
        )

        # 7) trend_exhaustion 连续 N 根 streak（同 type）
        ex_alert = float(
            (self._cfg.get("capabilities", {})
                       .get("reversal", {})
                       .get("thresholds", {})
                       .get("exhaustion_alert", 5))
            if isinstance(self._cfg, dict) else 5
        )
        ex_streak, ex_type = _streak_same_type_exhaustion(
            trend_exhaustion_recent, threshold=ex_alert
        )

        # 8) sweep 刺穿后 liq_recover_bars 内是否回到带内
        liq_recover_bars = int(
            (self._cfg.get("capabilities", {})
                       .get("reversal", {})
                       .get("thresholds", {})
                       .get("liq_recover_bars", 3))
            if isinstance(self._cfg, dict) else 3
        )
        pierce_recovered = _pierce_recovered(
            klines=klines,
            sweep_last=sweep_recent[-1] if sweep_recent else None,
            liq_recover_bars=liq_recover_bars,
        )

        # 9) V1.1 扩展：7 个新指标 → 数字化视图
        tf_ms = _tf_to_ms(tf)
        # 9.1 ⚡ CHoCH 事件：近窗（事件窗）
        choch_raw = await self._fetch_choch_recent(
            symbol, tf, anchor_ts=anchor_ts, n=self._recent, tf_ms=tf_ms
        )
        choch_views = [
            _choch_to_view(ev, last_price=last_price, anchor_ts=anchor_ts, tf_ms=tf_ms)
            for ev in choch_raw
        ]
        choch_latest = choch_views[-1] if choch_views else None

        # 9.2 💣 爆仓带 TopN（多空各 N，按 signal_count DESC, volume DESC）
        cascade_raw = await self._fetch_cascade_bands(symbol, tf, topn=self._band_topn)
        cascade_views = [
            _band_to_view(
                b, last_price=last_price,
                volume=b.volume, signal_count=b.signal_count,
            )
            for b in cascade_raw
        ]

        # 9.3 散户止损带 TopN（多空各 N，按 volume DESC —— 颜色深浅）
        retail_raw = await self._fetch_retail_stop_bands(symbol, tf, topn=self._band_topn)
        retail_views = [
            _band_to_view(
                b, last_price=last_price,
                volume=b.volume, signal_count=None,
            )
            for b in retail_raw
        ]

        # 9.4 波段四维画像（ROI / Pain / Time / DdTolerance best_effort）
        segment_portrait = await self._build_segment_portrait(
            symbol, tf, anchor_ts=anchor_ts, tf_ms=tf_ms
        )

        # 9.5 动能一致性：imbalance 占比 vs cvd 斜率方向交叉判断。
        # 阈值留宽（imbalance 占比差 ≥ 0.2 才算"有偏"，cvd 用符号即可），
        # 避免把噪声判成 conflict。
        momentum_consistency: Literal[
            "agree_up", "agree_down", "conflict", "neutral"
        ] = "neutral"
        if imb_nonzero and cvd_slope is not None:
            imb_lead: Literal["buy", "sell", "neutral"] = "neutral"
            if green_ratio - red_ratio >= 0.2:
                imb_lead = "buy"
            elif red_ratio - green_ratio >= 0.2:
                imb_lead = "sell"
            cvd_lead: Literal["buy", "sell", "neutral"] = "neutral"
            if cvd_slope > 0:
                cvd_lead = "buy"
            elif cvd_slope < 0:
                cvd_lead = "sell"
            if imb_lead == "buy" and cvd_lead == "buy":
                momentum_consistency = "agree_up"
            elif imb_lead == "sell" and cvd_lead == "sell":
                momentum_consistency = "agree_down"
            elif imb_lead != "neutral" and cvd_lead != "neutral" and imb_lead != cvd_lead:
                momentum_consistency = "conflict"

        # 9.6 V1.1 · Step 7：动能能量柱 + 目标投影派生（详见 MOMENTUM-PULSE.md）
        #
        # 这两个 view 完全基于上文已经准备好的字段（power_imbalance / cvd / resonance /
        # exhaustion / saturation / choch / sweep / pierce / cascade / segment / vacuum /
        # heatmap / nearest_*），不读 DB；放在 snap 组装之前，便于后续单测可单独调用
        # 这两个派生函数，避免再次跑完整 extract。
        momentum_pulse = _derive_momentum_pulse(
            cfg=self._cfg,
            anchor_ts=anchor_ts,
            tf_ms=tf_ms,
            stale_tables=stale,
            power_imbalance_last=power_imbalance_last,
            power_imbalance_streak=pi_streak,
            power_imbalance_streak_side=pi_side,
            cvd_slope=cvd_slope,
            cvd_slope_sign=cvd_sign,
            imbalance_green_ratio=green_ratio,
            imbalance_red_ratio=red_ratio,
            resonance_buy_count=buy_count,
            resonance_sell_count=sell_count,
            trend_exhaustion_last=trend_exhaustion_last,
            exhaustion_streak=ex_streak,
            exhaustion_streak_type=ex_type,
            trend_saturation=trend_saturation,
            choch_latest=choch_latest,
            sweep_last=sweep_last,
            just_broke_resistance=broke_r,
            just_broke_support=broke_s,
            pierce_atr_ratio=pierce_atr_ratio,
        )
        target_projection = _derive_target_projection(
            cfg=self._cfg,
            last_price=last_price,
            atr=atr,
            segment_portrait=segment_portrait,
            cascade_views=cascade_views,
            heatmap=heatmap,
            vacuums=vacuums,
            nearest_support_price=near_s_price,
            nearest_resistance_price=near_r_price,
            momentum_pulse=momentum_pulse,
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
            cvd_range=cvd_range,
            cvd_converge_ratio=cvd_converge_ratio,
            imbalance_green_ratio=green_ratio,
            imbalance_red_ratio=red_ratio,
            momentum_consistency=momentum_consistency,
            poc_shift_delta_pct=poc_delta_pct,
            poc_shift_trend=poc_trend,
            power_imbalance_last=power_imbalance_last,
            power_imbalance_recent=power_imbalance_recent,
            power_imbalance_streak=pi_streak,
            power_imbalance_streak_side=pi_side,
            trend_exhaustion_last=trend_exhaustion_last,
            trend_exhaustion_recent=trend_exhaustion_recent,
            exhaustion_streak=ex_streak,
            exhaustion_streak_type=ex_type,
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
            volume_profile=volume_profile_view,
            time_heatmap_view=time_heatmap_view,
            nearest_support_price=near_s_price,
            nearest_support_distance_pct=near_s_dist,
            nearest_resistance_price=near_r_price,
            nearest_resistance_distance_pct=near_r_dist,
            just_broke_resistance=broke_r,
            just_broke_support=broke_s,
            pierce_atr_ratio=pierce_atr_ratio,
            pierce_recovered=pierce_recovered,
            choch_latest=choch_latest,
            choch_recent=choch_views,
            cascade_bands=cascade_views,
            retail_stop_bands=retail_views,
            segment_portrait=segment_portrait,
            momentum_pulse=momentum_pulse,
            target_projection=target_projection,
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

    async def _fetch_recent_power_imbalance(
        self, symbol: str, tf: str, n: int
    ) -> list[PowerImbalancePoint]:
        """取最近 N 根 power_imbalance（含 ratio=0，ASC）。

        为什么不过滤 0：官方口径「连续 3 根 ratio≥阈值」要按真实时间相邻关系判定，
        过滤 0 会把非连续的事件误认为连续。
        """
        rows = await self._db.fetchall(
            "SELECT symbol, tf, ts, buy_vol, sell_vol, ratio "
            "FROM atoms_power_imbalance "
            "WHERE symbol=? AND tf=? ORDER BY ts DESC LIMIT ?",
            (symbol, tf, n),
        )
        return [PowerImbalancePoint(**dict(r)) for r in reversed(rows)]

    async def _fetch_recent_trend_exhaustion(
        self, symbol: str, tf: str, n: int
    ) -> list[TrendExhaustionPoint]:
        rows = await self._db.fetchall(
            "SELECT symbol, tf, ts, exhaustion, type FROM atoms_trend_exhaustion "
            "WHERE symbol=? AND tf=? ORDER BY ts DESC LIMIT ?",
            (symbol, tf, n),
        )
        return [TrendExhaustionPoint(**dict(r)) for r in reversed(rows)]

    async def _fetch_time_heatmap(self, symbol: str, tf: str) -> dict[int, float]:
        rows = await self._db.fetchall(
            "SELECT hour, total FROM atoms_time_heatmap WHERE symbol=? AND tf=?",
            (symbol, tf),
        )
        return {int(r["hour"]): float(r["total"]) for r in rows}

    async def _fetch_volume_profile(
        self, symbol: str, tf: str
    ) -> list[VolumeProfileBucket]:
        """筹码分布所有桶（按价格 ASC，便于 VA 扩展算法线性扫描）。"""
        rows = await self._db.fetchall(
            "SELECT symbol, tf, price, accum, dist, total "
            "FROM atoms_volume_profile WHERE symbol=? AND tf=? ORDER BY price ASC",
            (symbol, tf),
        )
        return [VolumeProfileBucket(**dict(r)) for r in rows]

    # ─────────────────────── V1.1 取数 ───────────────────────

    async def _fetch_choch_recent(
        self, symbol: str, tf: str, *, anchor_ts: int, n: int, tf_ms: int
    ) -> list[ChochEvent]:
        """近窗内的 CHoCH/BOS 事件（ASC）。

        窗口边界与 resonance/sweep 保持一致：``[anchor_ts - n*tf_ms, anchor_ts]``，
        便于 scorer/AI 做"此刻发生了什么"的即时观察。
        """
        start_ts = anchor_ts - (n * tf_ms)
        rows = await self._db.fetchall(
            "SELECT symbol, tf, ts, price, level_price, origin_ts, type "
            "FROM atoms_choch_events "
            "WHERE symbol=? AND tf=? AND ts >= ? ORDER BY ts ASC",
            (symbol, tf, start_ts),
        )
        return [ChochEvent(**dict(r)) for r in rows]

    async def _fetch_cascade_bands(
        self, symbol: str, tf: str, *, topn: int
    ) -> list[CascadeBand]:
        """💣 爆仓带 TopN（多空各 N）。

        排序：先 signal_count DESC（💣 强度），次 volume DESC（资金量）。
        UNION 写法避免 Python 侧二次排序，SQL 单次回表即可。
        """
        if topn <= 0:
            return []
        rows = await self._db.fetchall(
            "SELECT * FROM (\n"
            "  SELECT symbol, tf, start_time, bottom_price, top_price, avg_price, "
            "         volume, signal_count, type FROM atoms_cascade_bands "
            "  WHERE symbol=? AND tf=? AND type='Accumulation' "
            "  ORDER BY signal_count DESC, volume DESC LIMIT ?\n"
            ") UNION ALL SELECT * FROM (\n"
            "  SELECT symbol, tf, start_time, bottom_price, top_price, avg_price, "
            "         volume, signal_count, type FROM atoms_cascade_bands "
            "  WHERE symbol=? AND tf=? AND type='Distribution' "
            "  ORDER BY signal_count DESC, volume DESC LIMIT ?\n"
            ")",
            (symbol, tf, topn, symbol, tf, topn),
        )
        return [CascadeBand(**dict(r)) for r in rows]

    async def _fetch_retail_stop_bands(
        self, symbol: str, tf: str, *, topn: int
    ) -> list[RetailStopBand]:
        """散户止损带 TopN（多空各 N，按 volume DESC —— 带颜色越深越肥）。"""
        if topn <= 0:
            return []
        rows = await self._db.fetchall(
            "SELECT * FROM (\n"
            "  SELECT symbol, tf, start_time, bottom_price, top_price, avg_price, "
            "         volume, type FROM atoms_retail_stop_bands "
            "  WHERE symbol=? AND tf=? AND type='Accumulation' "
            "  ORDER BY volume DESC LIMIT ?\n"
            ") UNION ALL SELECT * FROM (\n"
            "  SELECT symbol, tf, start_time, bottom_price, top_price, avg_price, "
            "         volume, type FROM atoms_retail_stop_bands "
            "  WHERE symbol=? AND tf=? AND type='Distribution' "
            "  ORDER BY volume DESC LIMIT ?\n"
            ")",
            (symbol, tf, topn, symbol, tf, topn),
        )
        return [RetailStopBand(**dict(r)) for r in rows]

    async def _fetch_latest_roi(
        self, symbol: str, tf: str
    ) -> RoiSegment | None:
        """锚点用：优先 Ongoing，fallback 到 start_time 最大。"""
        row = await self._db.fetchone(
            "SELECT symbol, tf, start_time, end_time, avg_price, "
            "       limit_avg_price, limit_max_price, type, status "
            "FROM atoms_roi_segments WHERE symbol=? AND tf=? "
            "ORDER BY (status='Ongoing') DESC, start_time DESC LIMIT 1",
            (symbol, tf),
        )
        return RoiSegment(**dict(row)) if row else None

    async def _fetch_roi_by_key(
        self, symbol: str, tf: str, start_time: int, type_: str
    ) -> RoiSegment | None:
        row = await self._db.fetchone(
            "SELECT symbol, tf, start_time, end_time, avg_price, "
            "       limit_avg_price, limit_max_price, type, status "
            "FROM atoms_roi_segments WHERE symbol=? AND tf=? "
            "AND start_time=? AND type=?",
            (symbol, tf, start_time, type_),
        )
        return RoiSegment(**dict(row)) if row else None

    async def _fetch_pain_by_key(
        self, symbol: str, tf: str, start_time: int, type_: str
    ) -> PainDrawdownSegment | None:
        row = await self._db.fetchone(
            "SELECT symbol, tf, start_time, end_time, avg_price, "
            "       pain_avg_price, pain_max_price, type, status "
            "FROM atoms_pain_drawdown_segments WHERE symbol=? AND tf=? "
            "AND start_time=? AND type=?",
            (symbol, tf, start_time, type_),
        )
        return PainDrawdownSegment(**dict(row)) if row else None

    async def _fetch_time_by_key(
        self, symbol: str, tf: str, start_time: int, type_: str
    ) -> TimeWindowSegment | None:
        row = await self._db.fetchone(
            "SELECT symbol, tf, start_time, end_time, last_update_time, avg_price, "
            "       limit_avg_time, limit_max_time, type, status "
            "FROM atoms_time_windows WHERE symbol=? AND tf=? "
            "AND start_time=? AND type=?",
            (symbol, tf, start_time, type_),
        )
        return TimeWindowSegment(**dict(row)) if row else None

    async def _fetch_latest_dd_tolerance(
        self, symbol: str, tf: str
    ) -> DdToleranceSegment | None:
        """dd_tolerance 主键用官方 id，与 ROI 主键不同；用 status+end_time 作为"最新段"。"""
        row = await self._db.fetchone(
            "SELECT symbol, tf, id, start_time, end_time, limit_pct, status, "
            "       trailing_line, pierces "
            "FROM atoms_dd_tolerance_segments WHERE symbol=? AND tf=? "
            "ORDER BY (status='Ongoing') DESC, end_time DESC LIMIT 1",
            (symbol, tf),
        )
        if not row:
            return None
        import json as _json

        d = dict(row)
        d["trailing_line"] = _json.loads(d.get("trailing_line") or "[]")
        d["pierces"] = _json.loads(d.get("pierces") or "[]")
        return DdToleranceSegment(**d)

    async def _build_segment_portrait(
        self, symbol: str, tf: str, *, anchor_ts: int, tf_ms: int
    ) -> SegmentPortrait | None:
        """波段四维 best_effort 画像。

        设计原则：
          - 以 ROI 为锚（Ongoing 优先），其他三维按 (start_time, type) JOIN；
          - ROI / Pain / Time 共享主键，可以精确 JOIN；
          - DdTolerance 主键不同，以"最新 Ongoing 段"挂靠；
          - 任一维缺失字段留 None，``sources`` 汇报实际到手的维度；
          - 4 个维度全空 → 返回 None（避免空壳）。
        """
        sources: list[str] = []

        roi = await self._fetch_latest_roi(symbol, tf)
        pain = None
        time_seg = None
        if roi is not None:
            sources.append("roi")
            pain = await self._fetch_pain_by_key(symbol, tf, roi.start_time, roi.type)
            time_seg = await self._fetch_time_by_key(symbol, tf, roi.start_time, roi.type)
            if pain is not None:
                sources.append("pain")
            if time_seg is not None:
                sources.append("time")

        dd = await self._fetch_latest_dd_tolerance(symbol, tf)
        if dd is not None:
            sources.append("dd_tolerance")

        if not sources:
            return None

        # Time 维度的距离换算：当前 anchor_ts 到 avg/max 还有几根 K 线。
        bars_to_avg: int | None = None
        bars_to_max: int | None = None
        if time_seg is not None and tf_ms > 0:
            bars_to_avg = (time_seg.limit_avg_time - anchor_ts) // tf_ms
            bars_to_max = (time_seg.limit_max_time - anchor_ts) // tf_ms

        # DdTolerance 护城河当前位 = trailing_line 最新一点的 price（[ts, price]）
        dd_current: float | None = None
        dd_pierces_ct = 0
        if dd is not None:
            tl = dd.trailing_line or []
            if tl:
                # 选 ts 最大的那条；trailing_line 元素形如 [ts, price]。
                latest = max(tl, key=lambda p: p[0] if len(p) >= 2 else 0)
                if len(latest) >= 2:
                    dd_current = float(latest[1])
            dd_pierces_ct = len(dd.pierces or [])

        return SegmentPortrait(
            start_time=roi.start_time if roi else None,
            type=roi.type if roi else None,
            status=roi.status if roi else None,
            roi_avg_price=roi.avg_price if roi else None,
            roi_limit_avg_price=roi.limit_avg_price if roi else None,
            roi_limit_max_price=roi.limit_max_price if roi else None,
            pain_avg_price=pain.pain_avg_price if pain else None,
            pain_max_price=pain.pain_max_price if pain else None,
            time_avg_ts=time_seg.limit_avg_time if time_seg else None,
            time_max_ts=time_seg.limit_max_time if time_seg else None,
            bars_to_avg=bars_to_avg,
            bars_to_max=bars_to_max,
            dd_limit_pct=dd.limit_pct if dd else None,
            dd_trailing_current=dd_current,
            dd_pierce_count=dd_pierces_ct,
            sources=sources,  # type: ignore[arg-type]
        )


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


def _derive_time_heatmap_view(
    heatmap: dict[int, float],
    anchor_ts: int,
    *,
    active_threshold: float = 0.5,
    peak_n: int = 3,
    dead_n: int = 2,
) -> TimeHeatmapView | None:
    """把 24h 热力图派生成给前端/AI 读的视图。

    - ``peak_hours`` / ``dead_hours`` 都按 total 排序后取 TopN / BottomN；
    - ``current_rank`` 按 total DESC 排名（1 = 最活跃），缺当前小时时取 24；
    - heatmap 为空时返回 None（上层判断并降级）。
    """
    if not heatmap:
        return None
    import datetime as _dt

    hour = _dt.datetime.fromtimestamp(anchor_ts / 1000, tz=_dt.UTC).hour
    mx = max(heatmap.values()) or 1.0
    current_activity = heatmap.get(hour, 0.0) / mx

    # 按活跃度降序 → 排名 / peak / dead
    sorted_desc = sorted(heatmap.items(), key=lambda kv: kv[1], reverse=True)
    peak_hours = [h for h, _ in sorted_desc[:peak_n]]
    dead_hours = [h for h, _ in sorted_desc[-dead_n:][::-1]]  # 反转：最"冷"在前

    rank = 24
    for idx, (h, _) in enumerate(sorted_desc, start=1):
        if h == hour:
            rank = idx
            break

    return TimeHeatmapView(
        current_hour=hour,
        current_activity=current_activity,
        current_rank=rank,
        peak_hours=peak_hours,
        dead_hours=dead_hours,
        is_active_session=current_activity >= active_threshold,
    )


def _derive_volume_profile_view(
    buckets: list[VolumeProfileBucket],
    last_price: float,
    *,
    va_ratio: float = 0.70,
    top_n: int = 5,
) -> VolumeProfileView | None:
    """把筹码分布桶派生成前端/AI 可读的视图。

    Value Area 算法（经典 70% VA）：从 POC 开始双向扩展，每步选择
    两侧加一桶中"能覆盖更多成交量"的一侧，直至累计覆盖 ``va_ratio``。
    """
    if not buckets:
        return None
    total = sum(b.total for b in buckets)
    if total <= 0:
        return None

    by_price = sorted(buckets, key=lambda b: b.price)
    prices = [b.price for b in by_price]
    totals = [b.total for b in by_price]
    n = len(by_price)

    # 找 POC：total 最大
    poc_idx = max(range(n), key=lambda i: totals[i])
    poc_bucket = by_price[poc_idx]

    # 70% VA：从 POC 双向扩展
    low_idx = poc_idx
    high_idx = poc_idx
    accumulated = totals[poc_idx]
    target = total * va_ratio
    while accumulated < target and (low_idx > 0 or high_idx < n - 1):
        left = totals[low_idx - 1] if low_idx > 0 else -1.0
        right = totals[high_idx + 1] if high_idx < n - 1 else -1.0
        if left < 0 and right < 0:
            break
        if left >= right:
            low_idx -= 1
            accumulated += totals[low_idx]
        else:
            high_idx += 1
            accumulated += totals[high_idx]

    va_low = prices[low_idx]
    va_high = prices[high_idx]

    if last_price < va_low:
        position: Literal["below_va", "in_va", "above_va"] = "below_va"
    elif last_price > va_high:
        position = "above_va"
    else:
        position = "in_va"

    # TopN 筹码峰（按 total DESC）
    sorted_by_total = sorted(by_price, key=lambda b: b.total, reverse=True)
    top_nodes: list[VolumeProfileNode] = []
    for b in sorted_by_total[: max(0, top_n)]:
        if b.total <= 0:
            continue
        if b.accum > b.dist:
            side: Literal["buy", "sell", "balanced"] = "buy"
        elif b.dist > b.accum:
            side = "sell"
        else:
            side = "balanced"
        purity = abs(b.accum - b.dist) / b.total if b.total > 0 else 0.0
        top_nodes.append(
            VolumeProfileNode(
                price=b.price,
                accum=b.accum,
                dist=b.dist,
                total=b.total,
                dominant_side=side,
                purity_ratio=purity,
            )
        )

    poc_distance_pct = 0.0
    if last_price > 0:
        poc_distance_pct = (poc_bucket.price - last_price) / last_price

    return VolumeProfileView(
        poc_price=poc_bucket.price,
        poc_total=poc_bucket.total,
        value_area_low=va_low,
        value_area_high=va_high,
        value_area_volume_ratio=accumulated / total if total > 0 else 0.0,
        total_volume=total,
        last_price_position=position,
        poc_distance_pct=poc_distance_pct,
        top_nodes=top_nodes,
    )


def _nearest_levels_and_pierce(
    *,
    last_price: float,
    klines: list[Kline],
    recent_window: int,
    hvn_nodes: list[HvnNode],
    absolute_zones: list[AbsoluteZone],
    order_blocks: list[OrderBlock],
    micro_pocs: list[MicroPocSegment],
    anchor_ts: int | None = None,
    atr: float | None = None,
) -> tuple[
    float | None, float | None,          # nearest support price / distance
    float | None, float | None,          # nearest resistance price / distance
    bool, bool,                           # just_broke_resistance / support
    float | None, float | None,          # pierce_magnitude / pierce_ref_level
]:
    """汇总候选价位 → 找上下最近一档 → 判断最近 N 根是否刚穿越。

    额外返回穿越幅度（max(|cur.close - level|) over pierced levels）+ 参考价位，
    供 scorer 结合 ATR 判断"真突破 / 擦线"。

    **2026-04 修复**：过滤"当前 K 线自指" 候选，避免出现「nearest_resistance =
    当前 K 线 high、nearest_support = 当前 K 线 low」这种伪关键位（典型症状：
    距现价 < 0.1% 且 just_broke_resistance/support 同时为 true）。
      1. 过滤 absolute_zones 中 ``start_time >= anchor_ts`` 的 zone（当前 K 线
         本期生成的 zone bottom/top 就是 K 线 low/high，没有"关键位"含义）。
      2. 仅在最终选出的 nearest_* 价位通过最小距离阈值（``max(0.3%, 0.5×ATR/price)``）
         时才返回；否则视为"无近端关键位"，置 None。
    `micro_pocs` 中 ongoing 的最后一段保留（POC 是成交集中价位，与 K 线 high/low
    含义不同，仍是合理"动态磁吸位"）。
    """
    candidates: list[float] = []
    for h in hvn_nodes:
        candidates.append(h.price)
    for a in absolute_zones:
        if anchor_ts is not None and a.start_time >= anchor_ts:
            continue
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

    if last_price > 0:
        atr_pct = (atr / last_price) if (atr is not None and atr > 0) else 0.0
        min_dist_pct = max(0.003, 0.5 * atr_pct)
        if nearest_s is not None and near_s_dist is not None and near_s_dist < min_dist_pct:
            nearest_s = None
            near_s_dist = None
        if nearest_r is not None and near_r_dist is not None and near_r_dist < min_dist_pct:
            nearest_r = None
            near_r_dist = None

    # 穿越检测：遍历 **所有候选价位**（不按当前分类过滤），
    # 因为一个被刚刚从下向上穿越的价位，即使当前已变 support，依然应该
    # 触发 "just broke resistance"（反之亦然）。
    # 用单一窗口 + 相邻配对，保证 len(klines) < recent_window 时仍得到正确的连续 (prev, cur) 对。
    broke_r = False
    broke_s = False
    pierce_magnitude: float | None = None
    pierce_level: float | None = None
    window = klines[-recent_window:] if recent_window > 0 else klines
    if len(window) >= 2 and candidates:
        for prev, cur in zip(window, window[1:]):
            for level in candidates:
                if prev.close < level <= cur.close:
                    broke_r = True
                    mag = cur.close - level
                    if pierce_magnitude is None or mag > pierce_magnitude:
                        pierce_magnitude = mag
                        pierce_level = level
                if prev.close > level >= cur.close:
                    broke_s = True
                    mag = level - cur.close
                    if pierce_magnitude is None or mag > pierce_magnitude:
                        pierce_magnitude = mag
                        pierce_level = level

    return (
        nearest_s, near_s_dist,
        nearest_r, near_r_dist,
        broke_r, broke_s,
        pierce_magnitude, pierce_level,
    )


def _streak_same_side_power_imbalance(
    points: list[PowerImbalancePoint], *, threshold: float
) -> tuple[int, Literal["buy", "sell", "none"]]:
    """从最新一根往前数，连续 |ratio|≥threshold 且 **同侧**（buy_vol/sell_vol）的根数。"""
    if not points:
        return 0, "none"
    streak = 0
    side: Literal["buy", "sell", "none"] = "none"
    for p in reversed(points):
        cur_side: Literal["buy", "sell", "none"]
        if abs(p.ratio) < threshold:
            break
        cur_side = "buy" if p.buy_vol > p.sell_vol else "sell" if p.sell_vol > p.buy_vol else "none"
        if cur_side == "none":
            break
        if side == "none":
            side = cur_side
        elif cur_side != side:
            break
        streak += 1
    return streak, side


def _streak_same_type_exhaustion(
    points: list[TrendExhaustionPoint], *, threshold: float
) -> tuple[int, Literal["Accumulation", "Distribution", "none"]]:
    """从最新一根往前数，连续 exhaustion≥threshold 且 type 相同的根数。"""
    if not points:
        return 0, "none"
    streak = 0
    ty: Literal["Accumulation", "Distribution", "none"] = "none"
    for p in reversed(points):
        if p.exhaustion < threshold:
            break
        cur: Literal["Accumulation", "Distribution", "none"]
        t_lower = p.type.lower()
        if t_lower.startswith("accum"):
            cur = "Accumulation"
        elif t_lower.startswith("dist"):
            cur = "Distribution"
        else:
            break
        if ty == "none":
            ty = cur
        elif cur != ty:
            break
        streak += 1
    return streak, ty


def _choch_to_view(
    ev: ChochEvent, *, last_price: float, anchor_ts: int, tf_ms: int
) -> ChochLatestView:
    """把原子 ``ChochEvent`` 投影成数字化视图。

    - distance_pct 用 level_price（被砸穿的防线）与当前价的相对位置：
      正值表示防线仍在上方（当前是 BOS_Bullish 刚突破 / CHoCH_Bullish 刚反转后回踩中）。
    - bars_since 保守下限 0（极端时 ev.ts > anchor_ts 可能出现 clock skew）。
    """
    t = ev.type
    is_bullish = t.endswith("Bullish")
    kind: Literal["CHoCH", "BOS"] = "CHoCH" if t.startswith("CHoCH") else "BOS"
    dist = (ev.level_price - last_price) / last_price if last_price > 0 else 0.0
    bars = (anchor_ts - ev.ts) // tf_ms if tf_ms > 0 else 0
    if bars < 0:
        bars = 0
    return ChochLatestView(
        ts=ev.ts,
        price=ev.price,
        level_price=ev.level_price,
        origin_ts=ev.origin_ts,
        type=t,
        kind=kind,
        direction="bullish" if is_bullish else "bearish",
        is_choch=t.startswith("CHoCH"),
        distance_pct=dist,
        bars_since=int(bars),
    )


def _band_to_view(
    band: CascadeBand | RetailStopBand,
    *,
    last_price: float,
    volume: float,
    signal_count: int | None,
) -> BandView:
    """把 Cascade / RetailStop 原子投影成统一数字化视图。

    side 映射口径（白话化）：
      - ``type == Accumulation`` → ``long_fuel``（下方红带：多头燃料 / 多头被爆仓）
      - ``type == Distribution`` → ``short_fuel``（上方绿带：空头燃料 / 空头被爆仓）
    ``above_price`` 独立记录价位实际位置（应对价格已穿越带的异常情况）。
    """
    side: Literal["long_fuel", "short_fuel"] = (
        "long_fuel" if band.type == "Accumulation" else "short_fuel"
    )
    above = band.avg_price > last_price
    dist = (band.avg_price - last_price) / last_price if last_price > 0 else 0.0
    return BandView(
        start_time=band.start_time,
        avg_price=band.avg_price,
        top_price=band.top_price,
        bottom_price=band.bottom_price,
        volume=volume,
        type=band.type,
        side=side,
        above_price=above,
        distance_pct=dist,
        signal_count=signal_count,
    )


def _pierce_recovered(
    *,
    klines: list[Kline],
    sweep_last: LiquiditySweepEvent | None,
    liq_recover_bars: int,
) -> bool:
    """sweep 的针尖价位是否在 liq_recover_bars 根内被价格回收。

    - bullish_sweep（下刺）：随后 N 根内收盘价 ≥ sweep.price 即算回收。
    - bearish_sweep（上刺）：随后 N 根内收盘价 ≤ sweep.price 即算回收。
    """
    if sweep_last is None or liq_recover_bars <= 0 or not klines:
        return False
    # 找到 sweep 对应的 K 线（ts 最接近且 ≤ sweep.ts）
    anchor_idx: int | None = None
    for i in range(len(klines) - 1, -1, -1):
        if klines[i].ts <= sweep_last.ts:
            anchor_idx = i
            break
    if anchor_idx is None:
        return False
    end_idx = min(len(klines) - 1, anchor_idx + liq_recover_bars)
    if sweep_last.type == "bullish_sweep":
        return any(k.close >= sweep_last.price for k in klines[anchor_idx + 1 : end_idx + 1])
    if sweep_last.type == "bearish_sweep":
        return any(k.close <= sweep_last.price for k in klines[anchor_idx + 1 : end_idx + 1])
    return False


# ════════════════════════════════════════════════════════════════════
# V1.1 · Step 7：MomentumPulse / TargetProjection 派生
# ════════════════════════════════════════════════════════════════════


def _momentum_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    """从 cfg 取 momentum_pulse 节，全字段带兜底默认。

    与 ``rules.default.yaml::momentum_pulse`` 一一对应；任何字段缺失/类型异常
    都退回到内建默认（写死兜底，避免 yaml 缺一行就崩）。
    """
    section = (cfg or {}).get("momentum_pulse", {}) if isinstance(cfg, dict) else {}
    if not isinstance(section, dict):
        section = {}
    th = section.get("thresholds", {}) or {}
    w = section.get("weights", {}) or {}
    fd = section.get("fatigue_decay", {}) or {}
    return {
        "pi_min_ratio": float(th.get("power_imbalance_min_ratio", 1.5)),
        "pi_streak_full": float(th.get("power_imbalance_streak_full", 3)),
        "resonance_min_count": float(th.get("resonance_min_count", 2)),
        "atr_break_min": float(th.get("atr_break_min", 0.3)),
        "saturation_mid": float(th.get("saturation_mid", 50)),
        "override_max_bars": int(th.get("override_max_bars", 3)),
        "min_dominant_gap": int(th.get("min_dominant_gap", 10)),
        "exhaustion_alert": float(
            (cfg or {}).get("capabilities", {})
                       .get("reversal", {})
                       .get("thresholds", {})
                       .get("exhaustion_alert", 5)
            if isinstance(cfg, dict) else 5
        ),
        "exhaustion_consecutive_min": int(
            (cfg or {}).get("capabilities", {})
                       .get("reversal", {})
                       .get("thresholds", {})
                       .get("exhaustion_consecutive_min", 3)
            if isinstance(cfg, dict) else 3
        ),
        "w": {
            "power_imbalance": float(w.get("power_imbalance", 25)),
            "pi_streak": float(w.get("pi_streak", 20)),
            "cvd_slope": float(w.get("cvd_slope", 20)),
            "resonance": float(w.get("resonance", 15)),
            "imbalance_ratio": float(w.get("imbalance_ratio", 10)),
            "pierce": float(w.get("pierce", 10)),
        },
        "fd": {
            "fresh": float(fd.get("fresh", 0.0)),
            "mid": float(fd.get("mid", 0.2)),
            "exhausted": float(fd.get("exhausted", 0.5)),
        },
    }


def _target_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    section = (cfg or {}).get("target_projection", {}) if isinstance(cfg, dict) else {}
    if not isinstance(section, dict):
        section = {}
    sw_raw = section.get("source_weights", {}) or {}
    sw = {
        "roi": float(sw_raw.get("roi", 0.90)),
        "pain": float(sw_raw.get("pain", 0.85)),
        "cascade_band": float(sw_raw.get("cascade_band", 0.65)),
        "heatmap": float(sw_raw.get("heatmap", 0.70)),
        "vacuum": float(sw_raw.get("vacuum", 0.50)),
        "nearest_level": float(sw_raw.get("nearest_level", 0.60)),
    }
    return {
        "max_distance_pct": float(section.get("max_distance_pct", 0.08)),
        "max_bars_clip": int(section.get("max_bars_clip", 50)),
        "per_side_topn": int(section.get("per_side_topn", 5)),
        "source_weights": sw,
    }


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _override_detail(kind: str, direction: str, level_price: float, bars: int) -> str:
    arrow = "↑" if direction == "bullish" else "↓"
    when = "刚刚" if bars <= 0 else f"{bars} 根前"
    if abs(level_price) < 1:
        price_str = f"{level_price:,.4f}"
    else:
        price_str = f"{level_price:,.2f}"
    return f"⚡ {kind}{arrow} 破 {price_str} · {when}"


def _derive_momentum_pulse(
    *,
    cfg: dict[str, Any],
    anchor_ts: int,
    tf_ms: int,
    stale_tables: list[str],
    power_imbalance_last,
    power_imbalance_streak: int,
    power_imbalance_streak_side: Literal["buy", "sell", "none"],
    cvd_slope: float | None,
    cvd_slope_sign: Literal["up", "down", "flat"],
    imbalance_green_ratio: float,
    imbalance_red_ratio: float,
    resonance_buy_count: int,
    resonance_sell_count: int,
    trend_exhaustion_last,
    exhaustion_streak: int,
    exhaustion_streak_type: Literal["Accumulation", "Distribution", "none"],
    trend_saturation,
    choch_latest: ChochLatestView | None,
    sweep_last,
    just_broke_resistance: bool,
    just_broke_support: bool,
    pierce_atr_ratio: float | None,
) -> MomentumPulseView:
    """派生 MomentumPulseView。

    设计要点：
      1. ``score_long`` / ``score_short`` 各自独立 0~100，**不互减**；
         双侧同时强表示"激烈拉锯"，UI 双柱平行展示而非"净向"。
      2. ``power_imbalance`` 数据 stale（atoms_power_imbalance 在 stale_tables 里）
         时不计 PI/streak 分；其他字段照常。
      3. ``override`` 优先级：CHoCH > Sweep > Pierce；同时存在时取最近一条。
      4. ``fatigue_state`` 必须按"主导侧"匹配 exhaustion type，错配不算疲劳。
    """
    mc = _momentum_cfg(cfg)
    w = mc["w"]
    contributions: list[ContribItem] = []
    long_score = 0.0
    short_score = 0.0

    pi_stale = "atoms_power_imbalance" in stale_tables
    pi_ratio = abs(power_imbalance_last.ratio) if power_imbalance_last is not None else 0.0
    pi_side = power_imbalance_streak_side  # buy / sell / none

    # 1) power_imbalance 单根
    if not pi_stale and power_imbalance_last is not None and pi_ratio >= mc["pi_min_ratio"]:
        delta = w["power_imbalance"]
        if pi_side == "buy":
            long_score += delta
            contributions.append(ContribItem(
                label="power_imbalance",
                value=f"ratio={pi_ratio:.2f} side=buy",
                delta=int(round(delta)), side="long",
            ))
        elif pi_side == "sell":
            short_score += delta
            contributions.append(ContribItem(
                label="power_imbalance",
                value=f"ratio={pi_ratio:.2f} side=sell",
                delta=int(round(delta)), side="short",
            ))

    # 2) power_imbalance streak（连续 N 根）
    if not pi_stale and power_imbalance_streak > 0 and pi_side != "none":
        ratio = _clamp(power_imbalance_streak / max(1.0, mc["pi_streak_full"]), 0.0, 1.0)
        delta = w["pi_streak"] * ratio
        if pi_side == "buy":
            long_score += delta
            contributions.append(ContribItem(
                label="pi_streak", value=f"{power_imbalance_streak}/{int(mc['pi_streak_full'])} root buy",
                delta=int(round(delta)), side="long",
            ))
        else:
            short_score += delta
            contributions.append(ContribItem(
                label="pi_streak", value=f"{power_imbalance_streak}/{int(mc['pi_streak_full'])} root sell",
                delta=int(round(delta)), side="short",
            ))

    # 3) cvd 斜率
    if cvd_slope_sign == "up" and cvd_slope is not None:
        delta = w["cvd_slope"]
        long_score += delta
        contributions.append(ContribItem(
            label="cvd_slope", value=f"slope={cvd_slope:.2f}",
            delta=int(round(delta)), side="long",
        ))
    elif cvd_slope_sign == "down" and cvd_slope is not None:
        delta = w["cvd_slope"]
        short_score += delta
        contributions.append(ContribItem(
            label="cvd_slope", value=f"slope={cvd_slope:.2f}",
            delta=int(round(delta)), side="short",
        ))

    # 4) resonance
    if resonance_buy_count > 0:
        ratio = _clamp(resonance_buy_count / max(1.0, mc["resonance_min_count"]), 0.0, 1.0)
        delta = w["resonance"] * ratio
        long_score += delta
        contributions.append(ContribItem(
            label="resonance_buy", value=f"count={resonance_buy_count}",
            delta=int(round(delta)), side="long",
        ))
    if resonance_sell_count > 0:
        ratio = _clamp(resonance_sell_count / max(1.0, mc["resonance_min_count"]), 0.0, 1.0)
        delta = w["resonance"] * ratio
        short_score += delta
        contributions.append(ContribItem(
            label="resonance_sell", value=f"count={resonance_sell_count}",
            delta=int(round(delta)), side="short",
        ))

    # 5) imbalance 绿/红占比
    # 占比差 ≥ 0 才有意义；最大权重在差值 0.5 时给满
    diff = imbalance_green_ratio - imbalance_red_ratio
    if diff > 0:
        ratio = _clamp(diff / 0.5, 0.0, 1.0)
        delta = w["imbalance_ratio"] * ratio
        long_score += delta
        contributions.append(ContribItem(
            label="imbalance_ratio",
            value=f"green={imbalance_green_ratio:.2f} red={imbalance_red_ratio:.2f}",
            delta=int(round(delta)), side="long",
        ))
    elif diff < 0:
        ratio = _clamp(-diff / 0.5, 0.0, 1.0)
        delta = w["imbalance_ratio"] * ratio
        short_score += delta
        contributions.append(ContribItem(
            label="imbalance_ratio",
            value=f"green={imbalance_green_ratio:.2f} red={imbalance_red_ratio:.2f}",
            delta=int(round(delta)), side="short",
        ))

    # 6) pierce（真穿越）
    if pierce_atr_ratio is not None and pierce_atr_ratio >= mc["atr_break_min"]:
        delta = w["pierce"]
        if just_broke_resistance:
            long_score += delta
            contributions.append(ContribItem(
                label="pierce", value=f"atr_ratio={pierce_atr_ratio:.2f} 上破",
                delta=int(round(delta)), side="long",
            ))
        if just_broke_support:
            short_score += delta
            contributions.append(ContribItem(
                label="pierce", value=f"atr_ratio={pierce_atr_ratio:.2f} 下破",
                delta=int(round(delta)), side="short",
            ))

    # 7) override（事件抢跑，优先级 CHoCH > Sweep > Pierce）
    override: OverrideEvent | None = None
    max_bars = mc["override_max_bars"]
    if choch_latest is not None and choch_latest.bars_since <= max_bars:
        override = OverrideEvent(
            kind=choch_latest.kind,
            direction=choch_latest.direction,
            bars_since=choch_latest.bars_since,
            detail=_override_detail(
                choch_latest.kind, choch_latest.direction,
                choch_latest.level_price, choch_latest.bars_since,
            ),
        )
    elif sweep_last is not None and tf_ms > 0:
        bars = max(0, (anchor_ts - sweep_last.ts) // tf_ms)
        if bars <= max_bars:
            sw_dir: Literal["bullish", "bearish"] = (
                "bullish" if sweep_last.type == "bullish_sweep" else "bearish"
            )
            override = OverrideEvent(
                kind="Sweep",
                direction=sw_dir,
                bars_since=int(bars),
                detail=_override_detail(
                    "Sweep", sw_dir, sweep_last.price, int(bars),
                ),
            )
    elif (
        pierce_atr_ratio is not None
        and pierce_atr_ratio >= mc["atr_break_min"]
        and (just_broke_resistance or just_broke_support)
    ):
        p_dir: Literal["bullish", "bearish"] = (
            "bullish" if just_broke_resistance else "bearish"
        )
        override = OverrideEvent(
            kind="Pierce",
            direction=p_dir,
            bars_since=0,
            detail=f"⚡ Pierce{'↑' if p_dir == 'bullish' else '↓'} ATR×{pierce_atr_ratio:.2f} · 刚刚",
        )

    # 8) clip & dominant
    score_long = int(round(_clamp(long_score, 0, 100)))
    score_short = int(round(_clamp(short_score, 0, 100)))
    if score_long - score_short >= mc["min_dominant_gap"]:
        dominant: Literal["long", "short", "neutral"] = "long"
    elif score_short - score_long >= mc["min_dominant_gap"]:
        dominant = "short"
    else:
        dominant = "neutral"

    # 9) streak（仅在主导侧匹配 streak_side 时输出）
    if dominant == "long" and pi_side == "buy":
        streak_bars = power_imbalance_streak
    elif dominant == "short" and pi_side == "sell":
        streak_bars = power_imbalance_streak
    else:
        streak_bars = 0

    # 10) fatigue_state（必须按 dominant 侧 + exhaustion type 匹配）
    fatigue_state: Literal["fresh", "mid", "exhausted"] = "fresh"
    if (
        trend_exhaustion_last is not None
        and trend_exhaustion_last.exhaustion >= mc["exhaustion_alert"]
        and exhaustion_streak >= mc["exhaustion_consecutive_min"]
    ):
        # Accumulation 类 exhaustion 警告"上涨疲劳"，只在 dominant=long 时算 exhausted；
        # Distribution 类同理；type=none 不视作疲劳。
        match = (
            (dominant == "long" and exhaustion_streak_type == "Accumulation")
            or (dominant == "short" and exhaustion_streak_type == "Distribution")
        )
        if match:
            fatigue_state = "exhausted"
    if fatigue_state == "fresh" and trend_saturation is not None:
        if trend_saturation.progress >= mc["saturation_mid"]:
            fatigue_state = "mid"

    fatigue_decay = mc["fd"][fatigue_state]

    # 11) note（白话一句话）
    side_label = {"long": "多头", "short": "空头", "neutral": "中性"}[dominant]
    note = (
        f"{side_label} · 多 {score_long} / 空 {score_short} · "
        f"streak {streak_bars} · {fatigue_state}"
    )
    if pi_stale:
        note += " · ⚠ PI 数据陈旧"
    if override is not None:
        note += f" · {override.detail}"

    return MomentumPulseView(
        score_long=score_long,
        score_short=score_short,
        dominant_side=dominant,
        streak_bars=int(streak_bars),
        streak_side=pi_side,
        fatigue_state=fatigue_state,
        fatigue_decay=round(fatigue_decay, 3),
        override=override,
        contributions=contributions,
        note=note,
    )


def _bars_to_arrive(price: float, last_price: float, atr: float | None, clip: int) -> int | None:
    if atr is None or atr <= 0:
        return None
    bars = int(round(abs(price - last_price) / atr))
    return min(max(bars, 0), clip)


def _push_target(
    items: list[TargetItem],
    *,
    kind: str,
    price: float,
    last_price: float,
    atr: float | None,
    cfg: dict[str, Any],
    momentum_pulse: MomentumPulseView | None,
    tier: Literal["T1", "T2"],
    evidence: str,
) -> None:
    """构造一个 TargetItem 并 push 进 items（distance_pct 超阈值则跳过）。

    confidence 公式（详见 MOMENTUM-PULSE.md §3.3）：
      0.45 * source_weight
      + 0.25 * (1 - dist/max)
      + 0.20 * align_with_momentum
      + 0.10 * (1 - fatigue_decay)
    """
    if last_price <= 0:
        return
    distance_pct = (price - last_price) / last_price
    abs_dist = abs(distance_pct)
    max_d = cfg["max_distance_pct"]
    if abs_dist > max_d:
        return
    side: Literal["above", "below"] = "above" if distance_pct >= 0 else "below"
    sw = cfg["source_weights"].get(kind, 0.5)

    align = 0.0
    if momentum_pulse is not None:
        if side == "above" and momentum_pulse.dominant_side == "long":
            align = 1.0
        elif side == "below" and momentum_pulse.dominant_side == "short":
            align = 1.0

    fd = momentum_pulse.fatigue_decay if momentum_pulse is not None else 0.0
    near_score = 1.0 - (abs_dist / max_d) if max_d > 0 else 0.0

    confidence = _clamp(
        0.45 * sw + 0.25 * near_score + 0.20 * align + 0.10 * (1 - fd),
        0.0, 1.0,
    )

    items.append(TargetItem(
        kind=kind,  # type: ignore[arg-type]
        side=side,
        tier=tier,
        price=round(price, 6),
        distance_pct=round(distance_pct, 4),
        confidence=round(confidence, 3),
        bars_to_arrive=_bars_to_arrive(price, last_price, atr, cfg["max_bars_clip"]),
        evidence=evidence,
    ))


def _derive_target_projection(
    *,
    cfg: dict[str, Any],
    last_price: float,
    atr: float | None,
    segment_portrait: SegmentPortrait | None,
    cascade_views: list[BandView],
    heatmap: list,
    vacuums: list,
    nearest_support_price: float | None,
    nearest_resistance_price: float | None,
    momentum_pulse: MomentumPulseView | None,
) -> TargetProjectionView:
    """派生 TargetProjectionView。

    所有目标项的 side 由 ``distance_pct`` 直接决定（current price 是中点），
    不按 ROI/Pain 的"语义方向"硬定（避免 type=Distribution 的 ROI 在上方却被错放下方）。
    """
    tc = _target_cfg(cfg)
    items: list[TargetItem] = []

    # 1) ROI 目标（T1=avg / T2=max）
    if segment_portrait is not None:
        if segment_portrait.roi_limit_avg_price is not None:
            _push_target(
                items, kind="roi", price=segment_portrait.roi_limit_avg_price,
                last_price=last_price, atr=atr, cfg=tc,
                momentum_pulse=momentum_pulse, tier="T1",
                evidence="🎯 ROI T1 平均目标",
            )
        if segment_portrait.roi_limit_max_price is not None:
            _push_target(
                items, kind="roi", price=segment_portrait.roi_limit_max_price,
                last_price=last_price, atr=atr, cfg=tc,
                momentum_pulse=momentum_pulse, tier="T2",
                evidence="🎯 ROI T2 极限目标",
            )
        # 2) Pain 防线（T1=avg / T2=max）
        if segment_portrait.pain_avg_price is not None:
            _push_target(
                items, kind="pain", price=segment_portrait.pain_avg_price,
                last_price=last_price, atr=atr, cfg=tc,
                momentum_pulse=momentum_pulse, tier="T1",
                evidence="🛡 Pain T1 容忍带",
            )
        if segment_portrait.pain_max_price is not None:
            _push_target(
                items, kind="pain", price=segment_portrait.pain_max_price,
                last_price=last_price, atr=atr, cfg=tc,
                momentum_pulse=momentum_pulse, tier="T2",
                evidence="🛡 Pain T2 极限防线",
            )

    # 3) cascade 爆仓带（按 signal_count desc 取 TopN，T1=最强 / T2=次强）
    if cascade_views:
        # 按强度降序：signal_count 优先，volume 次之
        sorted_bands = sorted(
            cascade_views,
            key=lambda b: (b.signal_count or 0, abs(b.volume)),
            reverse=True,
        )
        for idx, b in enumerate(sorted_bands[: tc["per_side_topn"]]):
            tier: Literal["T1", "T2"] = "T1" if idx == 0 else "T2"
            sc = b.signal_count or 0
            ev = f"💣 Cascade {b.side} count={sc}"
            _push_target(
                items, kind="cascade_band", price=b.avg_price,
                last_price=last_price, atr=atr, cfg=tc,
                momentum_pulse=momentum_pulse, tier=tier, evidence=ev,
            )

    # 4) heatmap（按 intensity desc 取 TopN）
    if heatmap:
        sorted_h = sorted(heatmap, key=lambda h: getattr(h, "intensity", 0.0), reverse=True)
        for idx, h in enumerate(sorted_h[: tc["per_side_topn"]]):
            tier = "T1" if idx == 0 else "T2"
            _push_target(
                items, kind="heatmap", price=h.price,
                last_price=last_price, atr=atr, cfg=tc,
                momentum_pulse=momentum_pulse, tier=tier,
                evidence=f"🌡 Heatmap intensity={getattr(h, 'intensity', 0.0):.2f}",
            )

    # 5) vacuums（按到现价的距离取上下最近各一条）
    if vacuums:
        # 对每个 vacuum 取中价
        v_above = [v for v in vacuums if (v.low + v.high) / 2 > last_price]
        v_below = [v for v in vacuums if (v.low + v.high) / 2 <= last_price]
        if v_above:
            v = min(v_above, key=lambda x: (x.low + x.high) / 2 - last_price)
            mid = (v.low + v.high) / 2
            _push_target(
                items, kind="vacuum", price=mid,
                last_price=last_price, atr=atr, cfg=tc,
                momentum_pulse=momentum_pulse, tier="T1",
                evidence=f"💨 真空 [{v.low:.2f}, {v.high:.2f}]",
            )
        if v_below:
            v = max(v_below, key=lambda x: (x.low + x.high) / 2 - last_price)
            mid = (v.low + v.high) / 2
            _push_target(
                items, kind="vacuum", price=mid,
                last_price=last_price, atr=atr, cfg=tc,
                momentum_pulse=momentum_pulse, tier="T1",
                evidence=f"💨 真空 [{v.low:.2f}, {v.high:.2f}]",
            )

    # 6) nearest_level（最近 R/S 兜底，永远显示）
    if nearest_resistance_price is not None:
        _push_target(
            items, kind="nearest_level", price=nearest_resistance_price,
            last_price=last_price, atr=atr, cfg=tc,
            momentum_pulse=momentum_pulse, tier="T1",
            evidence="◯ 最近阻力",
        )
    if nearest_support_price is not None:
        _push_target(
            items, kind="nearest_level", price=nearest_support_price,
            last_price=last_price, atr=atr, cfg=tc,
            momentum_pulse=momentum_pulse, tier="T1",
            evidence="◯ 最近支撑",
        )

    # 拆 above/below + 按 |distance| 升序 + 限制每侧 TopN
    above = sorted(
        [it for it in items if it.side == "above"],
        key=lambda x: abs(x.distance_pct),
    )[: tc["per_side_topn"]]
    below = sorted(
        [it for it in items if it.side == "below"],
        key=lambda x: abs(x.distance_pct),
    )[: tc["per_side_topn"]]

    return TargetProjectionView(
        above=above,
        below=below,
        max_distance_pct=tc["max_distance_pct"],
    )


__all__ = [
    "BandView",
    "ChochLatestView",
    "ContribItem",
    "FeatureExtractor",
    "FeatureSnapshot",
    "MomentumPulseView",
    "OverrideEvent",
    "SegmentPortrait",
    "TargetItem",
    "TargetProjectionView",
]
