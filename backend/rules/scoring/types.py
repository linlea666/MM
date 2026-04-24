"""评分层公共类型。

3 类分数：
1. ``CapabilityScore``   snapshot 级（accumulation/distribution/breakout/reversal）
2. ``LevelScore``        关键位级（key_level_strength，单个 level 打分）
3. ``MagnetScore``       磁吸目标级（liquidity_magnet，单个 target 打分）

所有 scorer 都是纯函数，输入不可变，输出带完整证据链（Evidence），
好让前端调试面板 / AI 观察模式直接展示"为什么给 X 分"。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Direction = Literal["bullish", "bearish", "neutral"]


class Evidence(BaseModel):
    """一条证据：规则命中 / 未命中 / 部分命中。"""

    model_config = ConfigDict(extra="forbid")

    rule_id: str
    label: str                          # 中文可读标签
    weight: float                       # 该条在能力里占的权重 0-1
    hit: bool                           # 是否达标（部分达标仍为 True，用 ratio 表达强弱）
    ratio: float = 0.0                  # 达标程度 0-1，× weight × 100 = 贡献分
    value: Any = None                   # 观测值
    threshold: Any = None               # 阈值（若有）
    note: str = ""                      # 可读说明

    @property
    def contribution(self) -> float:
        """该条最终贡献到 capability 总分的值（0 - weight*100）。"""
        return self.ratio * self.weight * 100.0


class CapabilityScore(BaseModel):
    """snapshot 级能力分（吸筹/派发/突破/反转）。"""

    model_config = ConfigDict(extra="forbid")

    name: str                           # accumulation / distribution / ...
    score: float                        # 0-100
    band: str                           # very_strong / strong / neutral_low / ...
    direction: Direction = "neutral"
    evidence: list[Evidence] = Field(default_factory=list)
    note: str = ""


# ─── 关键位评分相关 ───────────────────────────────────────


LevelSourceKind = Literal[
    "hvn",
    "absolute_zone",
    "fvg",                 # V1 用 vacuum 代理
    "micro_poc",
    "smart_money",
    "trend_price",
    "trailing_vwap",
    "heatmap",
    "cascade_band",        # V1.1 · 💣 机构连环爆仓带（雷区插针反向接针）
    "retail_band",         # V1.1 · 散户止损带（磁吸方向/破位追单）
]


class LevelSource(BaseModel):
    """一个关键位来源（一个 level 可能由多个来源共同支持）。"""

    model_config = ConfigDict(extra="forbid")

    kind: LevelSourceKind
    weight: float                       # 来源权重（来自 capabilities.key_level_strength.source_weights）
    value: Any = None                   # 源数据（调试用）


class LevelCandidate(BaseModel):
    """规则层用的候选关键位（未打分、未聚合）。"""

    model_config = ConfigDict(extra="forbid")

    price: float
    side: Literal["support", "resistance"]
    sources: list[LevelSource] = Field(default_factory=list)
    top: float | None = None            # zone / vacuum 的上沿
    bottom: float | None = None         # zone / vacuum 的下沿
    note: str = ""


class LevelScore(BaseModel):
    """单个 level 的强度评分。"""

    model_config = ConfigDict(extra="forbid")

    price: float
    side: Literal["support", "resistance"]
    score: float                        # 0-100
    band: str                           # strong / medium / weak
    sources: list[LevelSource]          # 回传让前端展示证据
    evidence: list[Evidence] = Field(default_factory=list)


# ─── 流动性磁吸目标 ───────────────────────────────────────


class MagnetCandidate(BaseModel):
    """磁吸候选目标（heatmap / fuel / vacuum 都可能成为目标）。"""

    model_config = ConfigDict(extra="forbid")

    price: float                        # 目标中心价
    side: Literal["upside", "downside"]
    heatmap_intensity: float = 0.0      # 0-1
    fuel_strength: float = 0.0          # 0-1
    vacuum_pull: float = 0.0            # 0-1
    distance_pct: float = 0.0           # 距当前价百分比
    source_ids: list[str] = Field(default_factory=list)  # 参与合成的原子来源


class MagnetScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    price: float
    side: Literal["upside", "downside"]
    score: float                        # 0-100
    distance_pct: float
    evidence: list[Evidence] = Field(default_factory=list)


__all__ = [
    "CapabilityScore",
    "Direction",
    "Evidence",
    "LevelCandidate",
    "LevelScore",
    "LevelSource",
    "LevelSourceKind",
    "MagnetCandidate",
    "MagnetScore",
]
