"""V1.1 · Phase 9 · AI 观察层数据契约。

严格分三层（对应 V1.1 统一模型架构），每层都是纯 Pydantic model，
禁止扩展字段（``extra="forbid"``），保证 LLM 输出格式可控：

1. TrendLayerOut       —— Layer 1 · 趋势分类
2. MoneyFlowLayerOut   —— Layer 2 · 主力动向
3. TradePlanLayerOut   —— Layer 3 · 交易计划（仅 Pro）

组合输出：AIObserverFeedItem / AIObserverFeed（面向前端 & REST）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Strict(BaseModel):
    # ``protected_namespaces=()`` 关闭 ``model_*`` 命名保护：我们在 AnalysisReport
    # 等模型里用了 ``model_tier`` 这类业务字段，与 Pydantic 的 ``model_*`` 内置约定无冲突。
    model_config = ConfigDict(extra="forbid", protected_namespaces=())


# ════════════════════════════════════════════════════════════════════
# 输入（FeatureSnapshot 的扁平投影，只取 LLM 真正需要的字段）
# ════════════════════════════════════════════════════════════════════


class AIObserverInput(_Strict):
    """给 LLM 的精简输入快照。由 observer 从 FeatureSnapshot 抽取构造。

    原始 FeatureSnapshot 体积大（含全量 recent 序列），直接喂成本高、
    信噪比差。这里做 2 件事：
      1. **投影**：只保留 29+ 指标里 "当前状态 + 关键派生" 的字段；
      2. **白话化**：枚举和标注 label 都替换成 LLM 看得懂的自然语言。

    非持久化模型，只在 observer 内部使用。
    """

    # 基础锚点
    symbol: str
    tf: str
    anchor_ts: int
    last_price: float
    atr: float | None = None

    # 趋势 / 价值
    vwap_last: float | None = None
    vwap_slope_pct: float | None = None          # 百分比，正 = 向上
    fair_value_delta_pct: float | None = None     # (price - vwap) / vwap
    trend_purity: str | None = None               # "Bullish" / "Bearish" / "Mixed"

    # 动能 / 方向
    cvd_slope: float | None = None
    cvd_sign: Literal["up", "down", "flat"] = "flat"
    cvd_converge_ratio: float | None = None       # 0-1，越小越收敛
    imbalance_green_ratio: float = 0.0
    imbalance_red_ratio: float = 0.0
    poc_shift_trend: Literal["up", "down", "flat"] = "flat"
    power_imbalance_streak: int = 0
    power_imbalance_streak_side: Literal["buy", "sell", "none"] = "none"
    trend_exhaustion_streak: int = 0
    trend_exhaustion_streak_type: Literal["Accumulation", "Distribution", "none"] = "none"

    # 主力事件
    resonance_buy_count: int = 0
    resonance_sell_count: int = 0
    sweep_count_recent: int = 0
    whale_net_direction: Literal["buy", "sell", "neutral"] = "neutral"

    # 关键位（距离 + 刚穿越）
    nearest_resistance_price: float | None = None
    nearest_resistance_distance_pct: float | None = None
    nearest_support_price: float | None = None
    nearest_support_distance_pct: float | None = None
    just_broke_resistance: bool = False
    just_broke_support: bool = False
    pierce_atr_ratio: float | None = None
    pierce_recovered: bool = False

    # V1.1 指标视图
    choch_latest_kind: Literal["CHoCH", "BOS", "none"] = "none"
    choch_latest_direction: Literal["bullish", "bearish", "none"] = "none"
    choch_latest_distance_pct: float | None = None
    choch_latest_bars_since: int | None = None
    cascade_bands_top: list[dict] = Field(default_factory=list)   # 简版 [{side, avg_price, strength}]
    retail_stop_bands_top: list[dict] = Field(default_factory=list)
    segment_portrait: dict | None = None                          # 波段四维扁平 dict

    # 沉睡资产（Stage 0 激活）
    volume_profile: dict | None = None                            # {poc,va_low,va_high,position,top_n}
    time_heatmap: dict | None = None                              # {current_hour,peak_hours,dead_hours,rank,active}

    # 饱和 / 时间
    trend_saturation_progress: float | None = None
    trend_saturation_type: Literal["Accumulation", "Distribution", "none"] = "none"

    # 数据新鲜度
    stale_tables: list[str] = Field(default_factory=list)


# ════════════════════════════════════════════════════════════════════
# Layer 1 · TrendClassifier
# ════════════════════════════════════════════════════════════════════


class TrendLayerOut(_Strict):
    """Layer 1 · 趋势分类输出。

    这层定性：方向、阶段、强度、置信度 + 2 条简短 evidence。
    不给任何交易动作，只给"现在市场处于什么状态"。
    """

    direction: Literal["bullish", "bearish", "neutral"]
    stage: Literal[
        "accumulation",    # 吸筹 / 区间震荡偏多
        "breakout",        # 突破 / 趋势启动
        "distribution",    # 派发 / 区间震荡偏空
        "trend_up",        # 趋势运行（多）
        "trend_down",      # 趋势运行（空）
        "reversal",        # 反转进行中
        "chop",            # 震荡 / 无趋势
    ]
    strength: Literal["strong", "moderate", "weak"]
    confidence: float = Field(ge=0.0, le=1.0)
    narrative: str = Field(max_length=160, description="一句话白话结论")
    evidences: list[str] = Field(min_length=2, max_length=4)


# ════════════════════════════════════════════════════════════════════
# Layer 2 · MoneyFlowReader
# ════════════════════════════════════════════════════════════════════


class MoneyFlowBandEcho(_Strict):
    """LLM 可引用的价位带（含白话说明）。"""

    kind: Literal["cascade_long_fuel", "cascade_short_fuel", "retail_long_fuel", "retail_short_fuel"]
    avg_price: float
    distance_pct: float
    note: str = Field(max_length=80)


class MoneyFlowLayerOut(_Strict):
    """Layer 2 · 主力动向输出。

    聚焦"谁在动、动到哪、在哪加/减仓"。
    Layer 1 给定性，本层给定量和定位。
    """

    dominant_side: Literal["smart_buy", "smart_sell", "retail_chase", "retail_flush", "neutral"]
    pressure_above: str = Field(max_length=120, description="上方关键压力白话（价位 + 成因）")
    support_below: str = Field(max_length=120, description="下方关键支撑白话")
    key_bands: list[MoneyFlowBandEcho] = Field(default_factory=list, max_length=6)
    narrative: str = Field(max_length=180)
    confidence: float = Field(ge=0.0, le=1.0)
    evidences: list[str] = Field(min_length=2, max_length=5)


# ════════════════════════════════════════════════════════════════════
# Layer 3 · TradePlanner（Pro）
# ════════════════════════════════════════════════════════════════════


class TradePlanLeg(_Strict):
    """单条交易计划。

    故意允许 ``entry / stop / tp`` 这类交易动词 —— 这一层就是给"可操作建议"。
    前端会明确标注 "AI 建议 · 非财务建议" 免责声明。
    """

    direction: Literal["long", "short"]
    entry_zone: tuple[float, float] = Field(description="(low, high) 入场区间")
    stop_loss: float
    take_profits: list[float] = Field(min_length=1, max_length=3)
    risk_reward: float = Field(ge=0.0, description="T1 的 R:R，供前端直接展示")
    size_hint: Literal["light", "half", "full"] = "half"
    rationale: str = Field(max_length=200)
    invalidation: str = Field(max_length=160, description="什么条件下本计划作废")

    @field_validator("entry_zone")
    @classmethod
    def _entry_order(cls, v: tuple[float, float]) -> tuple[float, float]:
        lo, hi = v
        if lo > hi:
            return (hi, lo)
        return v


class TradePlanLayerOut(_Strict):
    """Layer 3 · 交易计划输出（可有 0-2 条 legs）。"""

    legs: list[TradePlanLeg] = Field(default_factory=list, max_length=2)
    conditions: list[str] = Field(
        default_factory=list,
        max_length=5,
        description="当前市场需满足的先决条件（若未满足则 legs 为空）",
    )
    risk_flags: list[str] = Field(default_factory=list, max_length=5)
    confidence: float = Field(ge=0.0, le=1.0)
    narrative: str = Field(max_length=200)


# ════════════════════════════════════════════════════════════════════
# 组合输出
# ════════════════════════════════════════════════════════════════════


class AIObserverFeedItem(_Strict):
    """一次观察的完整产物。三层都可选，某层失败 / 未触发则留 None。"""

    ts: int
    symbol: str
    tf: str
    anchor_ts: int
    last_price: float

    # 本次实际调用的层 + 模型 + 成本
    layers_used: list[Literal["trend", "money_flow", "trade_plan"]] = Field(default_factory=list)
    models_used: dict[str, str] = Field(default_factory=dict)  # {"trend": "deepseek-v4-flash", ...}
    provider: str = "deepseek"
    latency_ms: int = 0
    cost_tokens: dict[str, int] = Field(default_factory=dict)   # {"prompt": 1200, "completion": 380}

    # 三层输出
    trend: TrendLayerOut | None = None
    money_flow: MoneyFlowLayerOut | None = None
    trade_plan: TradePlanLayerOut | None = None

    # 触发信息
    trigger: Literal["scheduled", "manual", "phase_switch", "urgent_signal"] = "scheduled"
    note: str | None = None

    # 错误信息（任何一层失败保留原因，但其它层的结果仍然保留）
    errors: dict[str, str] = Field(default_factory=dict)


class AIObserverFeed(_Strict):
    """AI 观察流水（近 N 条）。"""

    items: list[AIObserverFeedItem] = Field(default_factory=list)
    latest: AIObserverFeedItem | None = None


class SummaryBandPreview(_Strict):
    """summary 层磁吸带预览（Top N 最强），让主卡直接看到关键价位。"""

    kind: Literal[
        "cascade_long_fuel",
        "cascade_short_fuel",
        "retail_long_fuel",
        "retail_short_fuel",
    ]
    avg_price: float
    distance_pct: float
    note: str = Field(max_length=80)


# ════════════════════════════════════════════════════════════════════
# OnePass · 单次综合分析（V1.2 · 替代旧的 4 层 DeepAnalyzer）
# ════════════════════════════════════════════════════════════════════


class OnePassReport(_Strict):
    """OnePass · 单次综合分析输出。

    设计取舍：
    - **schema 极简**：只保留 hero/索引必需的结构化字段，其它全交给 ``report_md``，
      让模型尽量"按它的语言/逻辑"组织内容，而不是被 schema 强行肢解；
    - **markdown 优先**：``report_md`` 是主体，章节和结构由 prompt **建议**而非
      schema 强制 —— 避免老 DeepAnalyzer "7 章 + 4 ScenarioCase + JSON 闭合"
      的复杂稳态在 finish_reason="stop" 处早停；
    - **长度上限放到 60k**：远超 DeepSeek V4 单次输出硬上限（约 8k tokens），
      不会成为截断瓶颈；模型按需展开。
    """

    one_line: str = Field(max_length=240, description="一句话冷静结论（hero / 列表展示）")
    overall_bias: Literal["bullish", "bearish", "neutral"] = Field(
        description="综合方向判断"
    )
    confidence: float = Field(ge=0.0, le=1.0)

    key_takeaways: list[str] = Field(
        default_factory=list,
        max_length=12,
        description="3-12 条要点，每条独立可读，必带数值",
    )
    key_risks: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="风险点，每条带触发条件",
    )
    next_focus: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="未来 6h / 24h 应该重点观察的指标 / 价位",
    )

    report_md: str = Field(
        min_length=100,
        max_length=60000,
        description="综合 markdown 研报；章节由 prompt 建议但不强制",
    )


# ════════════════════════════════════════════════════════════════════
# AnalysisReport（落盘 + REST）
# ════════════════════════════════════════════════════════════════════


class AIRawPayloadDump(_Strict):
    """单层 LLM 调用的 system / user / raw_response 三段原文。"""

    layer: str
    model: str
    tokens_total: int = 0
    latency_ms: int = 0
    system_prompt: str = ""
    user_prompt: str = ""
    raw_response: str = ""


class AnalysisReport(_Strict):
    """一次深度分析产出（持久化 + REST 返回）。

    设计：
    - 与 ``AIObserverFeedItem`` 解耦：分析报告体积大、频次低、保留期长（ring 20）；
    - ``raw_payloads`` 是图 5 的 "AI 交互过程原文" 数据源：每层一段；
    - ``data_slice`` 是"纯指标数据"（剥掉规则/指令的 input JSON）—— 用户复制贴给其他 AI 做跨模型对照。
    """

    id: str                          # "20260425T024058-BTC-1h"
    ts: int                          # ms
    symbol: str
    tf: str
    model_tier: Literal["flash", "pro"] = "flash"
    thinking_enabled: bool = False
    status: Literal["ok", "error"] = "ok"
    error_reason: str | None = None
    total_tokens: int = 0
    total_latency_ms: int = 0
    unknown_price_count: int = 0
    unknown_price_samples: list[float] = Field(default_factory=list, max_length=8)

    one_line: str = ""
    report_md: str = ""
    raw_payloads: list[AIRawPayloadDump] = Field(default_factory=list)
    data_slice: str = ""             # 纯 JSON 字符串（input.model_dump_json）


class AnalysisReportSummary(_Strict):
    """报告列表项：和 AnalysisReport 同形（去掉重型字段）。"""

    id: str
    ts: int
    symbol: str
    tf: str
    model_tier: Literal["flash", "pro"] = "flash"
    thinking_enabled: bool = False
    status: Literal["ok", "error"] = "ok"
    total_tokens: int = 0
    total_latency_ms: int = 0
    unknown_price_count: int = 0
    one_line: str = ""


class AIObserverSummary(_Strict):
    """AIObservationCard 前端展示用的扁平摘要（从最新 feed item 派生）。

    设计口径：
    - 所有新字段均 Optional，缺失时前端优雅降级；
    - summary 只做"最薄投影"，不 copy 完整 schema 字段（详见 feed item）；
    - 目的：让主卡一眼看清"置信 / 强度 / 磁吸带 / 计划亮度 / 成本"。
    """

    ts: int
    age_seconds: int
    trigger: str
    provider: str

    # 趋势投影
    trend_direction: str | None = None
    trend_stage: str | None = None
    trend_strength: str | None = None
    trend_confidence: float | None = None
    trend_narrative: str | None = None

    # 资金面投影
    money_flow_dominant: str | None = None
    money_flow_confidence: float | None = None
    money_flow_narrative: str | None = None
    key_bands_preview: list[SummaryBandPreview] = Field(
        default_factory=list, max_length=3
    )

    # 交易计划投影
    has_trade_plan: bool = False
    trade_plan_narrative: str | None = None
    trade_plan_confidence: float | None = None
    trade_plan_legs_count: int = 0
    trade_plan_top_rr: float | None = None
    risk_flags: list[str] = Field(default_factory=list, max_length=5)

    # 成本 / 来源
    layers_used: list[str] = Field(default_factory=list)
    latency_ms: int = 0
    tokens_total: int = 0

    errors: dict[str, str] = Field(default_factory=dict)
