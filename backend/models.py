"""跨模块数据契约（约束 §3）。

本文件是所有模块之间通信的唯一数据规格定义，分四层：

1. **基础类型** —— 枚举、常用别名
2. **23 个原子（Atom）** —— 与 docs/upstream-api/ATOMS.md 一一对应，存储层和指标视图层的边界
3. **能力 / 模块输出** —— 规则引擎产出的中间结构
4. **DashboardSnapshot** —— 推给前端的最终聚合结构

设计原则：
- 字段名保留 HFD 原始命名，避免上游改字段时多处同步
- 时间戳一律毫秒 epoch（int），ISO 字符串只在 API 边界出现
- 全部用 Pydantic v2 的 ``BaseModel``，运行时强校验
- AI 输出有专门的禁止词校验器（详见 docs/dashboard-v1/AI-OBSERVER.md）
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ════════════════════════════════════════════════════════
# 一、基础类型
# ════════════════════════════════════════════════════════

# 主力行为方向
SegmentType = Literal["Accumulation", "Distribution"]

# 段式状态
SegmentStatus = Literal["Ongoing", "Completed"]

# K 线数据来源
KlineSource = Literal["binance", "okx", "hfd"]

# 大屏阶段（8 阶段状态机，详见 PLAN.md）
PhaseLabel = Literal[
    "底部吸筹震荡",
    "高位派发震荡",
    "真突破启动",
    "趋势延续",
    "假突破猎杀",
    "趋势耗竭",
    "黑洞加速",
    "无序震荡",
]

# 主力行为标签（详见 PLAN.md 模块 ③）
BehaviorMain = Literal[
    "强吸筹",
    "弱吸筹",
    "强派发",
    "弱派发",
    "横盘震荡",
    "趋势反转",
    "无主导",
]

# 行为警报
BehaviorAlertType = Literal[
    "共振爆发",
    "诱多",
    "诱空",
    "衰竭",
    "变盘临近",
    "护盘中",
    "压盘中",
    "猎杀进行中",
]

# 主力参与度
ParticipationLevel = Literal[
    "主力真参与",
    "局部参与",
    "疑似散户",
    "垃圾时间",
]

# 关键位强度
LevelStrength = Literal["strong", "medium", "weak"]
LevelFit = Literal["first_test_good", "worn_out", "can_break", "observe"]

# 交易动作
TradeAction = Literal[
    "追多",
    "追空",
    "回踩做多",
    "反弹做空",
    "反手",
    "观望",
]

# 仓位档位
PositionSize = Literal["轻仓", "标仓", "重仓"]

# 多空方向
Direction = Literal["buy", "sell"]

# 流动性磁吸方向
MagnetSide = Literal["above", "below"]

# 突破判定
BreakoutKind = Literal[
    "强真突破",
    "弱真突破",
    "假突破",
    "反向猎杀",
    "未突破",
]

# 数据源连接状态
DataSourceStatus = Literal["connected", "disconnected", "standby", "available"]


class _StrictBase(BaseModel):
    """所有契约模型默认 forbid 多余字段。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ════════════════════════════════════════════════════════
# 二、23 个原子（Atom）
# 与 docs/upstream-api/ATOMS.md 一一对应
# ════════════════════════════════════════════════════════

# ── 时序点类（9 个）──

class Kline(_StrictBase):
    """1.1 K 线（来源优先 Binance）。"""

    symbol: str
    tf: str
    ts: int  # ms epoch, K 线开盘时间
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: KlineSource = "binance"


class CvdPoint(_StrictBase):
    """1.2 累计主动净成交量。"""

    symbol: str
    tf: str
    ts: int
    value: float


class ImbalancePoint(_StrictBase):
    """1.3 单 K 线净差。"""

    symbol: str
    tf: str
    ts: int
    value: float


class InstVolPoint(_StrictBase):
    """1.4 机构成交量。"""

    symbol: str
    tf: str
    ts: int
    value: float


class VwapPoint(_StrictBase):
    """1.5 VWAP 基准。"""

    symbol: str
    tf: str
    ts: int
    vwap: float


class PocShiftPoint(_StrictBase):
    """1.6 POC 重心轨迹。"""

    symbol: str
    tf: str
    ts: int
    poc_price: float
    volume: float


class TrailingVwapPoint(_StrictBase):
    """1.7 动态防线（绿/红梯）。"""

    symbol: str
    tf: str
    ts: int
    resistance: float | None = None
    support: float | None = None


class PowerImbalancePoint(_StrictBase):
    """1.8 多空力量悬殊。大部分 K 线为 0，表示无碾压。"""

    symbol: str
    tf: str
    ts: int
    buy_vol: float
    sell_vol: float
    ratio: float


class TrendExhaustionPoint(_StrictBase):
    """1.9 能量耗竭。0 = 无耗竭。"""

    symbol: str
    tf: str
    ts: int
    exhaustion: int
    type: SegmentType


# ── 段式区间类（5 个）──

class SmartMoneySegment(_StrictBase):
    """2.1 主力成本段。"""

    symbol: str
    tf: str
    start_time: int
    end_time: int  # Ongoing 时跟随最新 K 线
    avg_price: float
    type: SegmentType
    status: SegmentStatus


class OrderBlock(_StrictBase):
    """2.2 订单块（trend_price / ob_decay）。"""

    symbol: str
    tf: str
    start_time: int
    avg_price: float
    volume: float
    type: SegmentType


class AbsoluteZone(_StrictBase):
    """2.3 密集博弈带（absolute_zones）。字段与 OrderBlock 不同。"""

    symbol: str
    tf: str
    start_time: int
    bottom_price: float
    top_price: float
    type: SegmentType


class MicroPocSegment(_StrictBase):
    """2.4 微观成本段。最新一段 end_time 可为 None。"""

    symbol: str
    tf: str
    start_time: int
    end_time: int | None = None
    poc_price: float
    volume: float
    type: SegmentType


class TrendPuritySegment(_StrictBase):
    """2.5 筹码纯度段。purity ∈ [0, 100]。"""

    symbol: str
    tf: str
    start_time: int
    end_time: int | None = None
    avg_price: float
    buy_vol: float
    sell_vol: float
    total_vol: float
    purity: float
    type: SegmentType


# ── 事件类（2 个）──

class ResonanceEvent(_StrictBase):
    """3.1 跨所共振大单。"""

    symbol: str
    tf: str
    ts: int
    price: float
    direction: Direction
    count: int
    exchanges: list[str]


class LiquiditySweepEvent(_StrictBase):
    """3.2 流动性猎杀。"""

    symbol: str
    tf: str
    ts: int
    price: float
    type: Literal["bullish_sweep", "bearish_sweep"]
    volume: float


# ── 价位类（5 个）──

class HeatmapBand(_StrictBase):
    """4.1 清算痛点带。intensity ∈ [0, 1]。"""

    symbol: str
    tf: str
    start_time: int
    price: float
    intensity: float
    type: SegmentType


class VacuumBand(_StrictBase):
    """4.2 流动性真空带。"""

    symbol: str
    tf: str
    low: float
    high: float


class LiquidationFuelBand(_StrictBase):
    """4.3 燃料库清算带。"""

    symbol: str
    tf: str
    bottom: float
    top: float
    fuel: float


class HvnNode(_StrictBase):
    """4.4 真实换手率节点（Top 10）。"""

    symbol: str
    tf: str
    rank: int
    price: float
    volume: float


class VolumeProfileBucket(_StrictBase):
    """4.5 筹码分布桶。"""

    symbol: str
    tf: str
    price: float
    accum: float
    dist: float
    total: float


# ── 聚合统计类（2 个）──

class TimeHeatmapHour(_StrictBase):
    """5.1 24 小时活跃度（hour ∈ 0..23 UTC）。"""

    symbol: str
    tf: str
    hour: int
    accum: float
    dist: float
    total: float

    @field_validator("hour")
    @classmethod
    def _hour_range(cls, v: int) -> int:
        if not 0 <= v <= 23:
            raise ValueError("hour must be in 0..23")
        return v


class TrendSaturationStat(_StrictBase):
    """5.2 趋势进度（每 (symbol, tf) 一行）。

    上游 ``start_time`` 是字符串，入库前必须转成 ms。
    """

    symbol: str
    tf: str
    type: SegmentType
    start_time: int  # ms（已转换）
    avg_vol: float
    current_vol: float
    progress: float


# ════════════════════════════════════════════════════════
# 三、能力 / 模块输出（规则引擎中间结构）
# 详见 docs/dashboard-v1/INDICATOR-COMBINATIONS.md
# ════════════════════════════════════════════════════════

class CapabilityScore(_StrictBase):
    """单个能力的得分（5 大能力共用）。"""

    name: str  # behavior / cost_wall / liquidity_magnet / support_resistance / breakout
    score: int  # 0~100
    confidence: float  # 0~1
    evidences: list[str] = Field(default_factory=list)
    notes: str | None = None


class BehaviorAlert(_StrictBase):
    type: BehaviorAlertType
    strength: int  # 0~100


class BehaviorScore(_StrictBase):
    """模块 ③ 主力行为雷达。"""

    main: BehaviorMain
    main_score: int  # 0~100
    sub_scores: dict[str, int] = Field(default_factory=dict)  # 吸筹/派发/护盘/...
    alerts: list[BehaviorAlert] = Field(default_factory=list)


class PhaseState(_StrictBase):
    """模块 ② 趋势阶段状态机。"""

    current: PhaseLabel
    current_score: int
    prev_phase: PhaseLabel | None = None
    next_likely: PhaseLabel | None = None
    unstable: bool = False
    bars_in_phase: int = 0


class ParticipationGate(_StrictBase):
    """模块 ④ 主力参与确认。"""

    level: ParticipationLevel
    confidence: float  # 0~1
    evidence: list[str] = Field(default_factory=list)


class Level(_StrictBase):
    """单一关键位。"""

    price: float
    sources: list[str] = Field(default_factory=list)
    strength: LevelStrength
    test_count: int = 0
    decay_pct: float = 0.0  # 0~1
    fit: LevelFit = "observe"
    score: int = 0


class LevelLadder(_StrictBase):
    """模块 ⑤ 关键位阶梯（上 3 + 当前价 + 下 3）。"""

    r3: Level | None = None
    r2: Level | None = None
    r1: Level | None = None
    current_price: float
    s1: Level | None = None
    s2: Level | None = None
    s3: Level | None = None


class LiquidityTarget(_StrictBase):
    side: MagnetSide
    price: float
    distance_pct: float
    intensity: float  # 0~1
    source: str  # heatmap / fuel / vacuum / sweep_targets / ...


class LiquidityCompass(_StrictBase):
    """模块 ⑥ 流动性磁吸罗盘。"""

    above_targets: list[LiquidityTarget] = Field(default_factory=list)
    below_targets: list[LiquidityTarget] = Field(default_factory=list)
    nearest_side: MagnetSide | None = None
    nearest_distance_pct: float | None = None


class TradingPlan(_StrictBase):
    """A/B/C 三情景之一（规则产出，AI 不能生成）。"""

    label: Literal["A", "B", "C"]
    action: TradeAction
    stars: int  # 0~5
    entry: tuple[float, float] | None = None  # (low, high)
    stop: float | None = None
    take_profit: list[float] = Field(default_factory=list)  # [T1, T2]
    position_size: PositionSize | None = None
    premise: str
    invalidation: str

    @field_validator("stars")
    @classmethod
    def _star_range(cls, v: int) -> int:
        if not 0 <= v <= 5:
            raise ValueError("stars must be 0..5")
        return v


# ── AI 观察模式（V1.1）──

# 禁止 AI 输出的词，详见 AI-OBSERVER.md §5
_AI_FORBIDDEN_WORDS: tuple[str, ...] = (
    "做多", "做空", "入场", "止损", "止盈", "开仓", "平仓",
    "追多", "追空", "抄底", "逃顶", "重仓", "梭哈",
    "entry", "stop", "tp", "long ", " short ", "buy at", "sell at",
)


class AIEvidence(_StrictBase):
    indicator: str
    field: str
    value: float | str
    note: str = ""


class AIObservation(_StrictBase):
    """AI 输出的单条观察。"""

    type: Literal["opportunity_candidate", "conflict_warning"]
    attention_level: Literal["low", "medium", "high"]
    headline: str = Field(max_length=40)
    description: str = Field(max_length=120)
    evidences: list[AIEvidence] = Field(min_length=2)

    @field_validator("headline", "description")
    @classmethod
    def _no_trading_verbs(cls, v: str) -> str:
        lower = v.lower()
        for word in _AI_FORBIDDEN_WORDS:
            if word in v or word in lower:
                raise ValueError(f"AI 输出包含禁止词: {word}")
        return v


class AIObserverOutput(_StrictBase):
    observations: list[AIObservation] = Field(max_length=5, default_factory=list)
    narrative: str | None = Field(default=None, max_length=200)
    conflict_with_rules: bool = False


# ── Hero Strip（顶部 4 维度结论）──

class HeroStrip(_StrictBase):
    main_behavior: str
    market_structure: str
    risk_status: str
    action_conclusion: str
    stars: int
    invalidation: str


# ── 时间线异动 ──

class TimelineEvent(_StrictBase):
    ts: int
    kind: str  # phase_switch / urgent_signal / sweep / breakout / ...
    headline: str
    detail: str | None = None
    severity: Literal["info", "warning", "alert"] = "info"


# ── 系统健康 ──

class DataSourceHealth(_StrictBase):
    status: DataSourceStatus
    last_success_ts: int | None = None
    avg_latency_ms: float | None = None
    recent_failures_1h: int = 0


class DashboardHealth(_StrictBase):
    """快照内嵌的简化健康指标（完整健康看 /api/system/health）。"""

    fresh: bool
    last_collector_ts: int | None = None
    stale_seconds: int | None = None
    warnings: list[str] = Field(default_factory=list)


# ── 最终聚合 ──

class DashboardSnapshot(_StrictBase):
    """推给前端的一次完整决策快照。"""

    timestamp: int
    symbol: str
    tf: str
    current_price: float

    hero: HeroStrip

    behavior: BehaviorScore
    phase: PhaseState
    participation: ParticipationGate
    levels: LevelLadder
    liquidity: LiquidityCompass

    plans: list[TradingPlan] = Field(default_factory=list)  # A/B/C

    ai_observations: list[AIObservation] = Field(default_factory=list)  # D（V1.1）

    capability_scores: list[CapabilityScore] = Field(default_factory=list)
    recent_events: list[TimelineEvent] = Field(default_factory=list)
    health: DashboardHealth


# ════════════════════════════════════════════════════════
# 四、订阅 / 系统
# ════════════════════════════════════════════════════════

SubscriptionStatus = Literal["active", "inactive"]


class Subscription(_StrictBase):
    symbol: str
    display_order: int = 0
    active: bool = True
    added_at: int   # ms
    last_viewed_at: int | None = None


class SystemHealth(_StrictBase):
    ts: int
    engine_running: bool
    uptime_seconds: int
    last_snapshot_ts: int | None = None
    data_sources: dict[str, DataSourceHealth] = Field(default_factory=dict)
    storage_ok: bool = True
    disk_free_mb: float | None = None
    db_size_mb: float | None = None
    active_symbols: list[str] = Field(default_factory=list)
    timeframes: list[str] = Field(default_factory=list)


# ════════════════════════════════════════════════════════
# 五、日志（API 边界）
# ════════════════════════════════════════════════════════

class LogEntry(_StrictBase):
    """SQLite 中保存 / API 返回的日志条目。"""

    id: int | None = None
    ts: str  # ISO 8601
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"]
    logger: str
    message: str
    tags: list[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    traceback: str | None = None


__all__ = [
    "AIEvidence",
    "AIObservation",
    "AIObserverOutput",
    "AbsoluteZone",
    "BehaviorAlert",
    "BehaviorAlertType",
    "BehaviorMain",
    "BehaviorScore",
    "BreakoutKind",
    "CapabilityScore",
    "CvdPoint",
    "DashboardHealth",
    "DashboardSnapshot",
    "DataSourceHealth",
    "DataSourceStatus",
    "Direction",
    "HeatmapBand",
    "HeroStrip",
    "HvnNode",
    "ImbalancePoint",
    "InstVolPoint",
    "Kline",
    "KlineSource",
    "Level",
    "LevelFit",
    "LevelLadder",
    "LevelStrength",
    "LiquidationFuelBand",
    "LiquidityCompass",
    "LiquiditySweepEvent",
    "LiquidityTarget",
    "LogEntry",
    "MagnetSide",
    "MicroPocSegment",
    "OrderBlock",
    "ParticipationGate",
    "ParticipationLevel",
    "PhaseLabel",
    "PhaseState",
    "PocShiftPoint",
    "PositionSize",
    "PowerImbalancePoint",
    "ResonanceEvent",
    "SegmentStatus",
    "SegmentType",
    "SmartMoneySegment",
    "Subscription",
    "SubscriptionStatus",
    "SystemHealth",
    "TimeHeatmapHour",
    "TimelineEvent",
    "TradeAction",
    "TradingPlan",
    "TrailingVwapPoint",
    "TrendExhaustionPoint",
    "TrendPuritySegment",
    "TrendSaturationStat",
    "VacuumBand",
    "VolumeProfileBucket",
    "VwapPoint",
]
