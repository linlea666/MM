# AI 观察模式（副驾驶，不是兜底）

> 定位：AI 是副驾驶观察员，不是兜底决策者。
> 本文档是 V1.1 AI 增强的**核心补充**。

---

## 一、为什么不能"喂原始数据兜底"

用户原话：*"能不能把所有原始数据喂 AI 分析做兜底？"*

思路对（规则硬，易漏机会），但直接那样做会掉 3 个陷阱：

### 陷阱 1：AI 幻觉造假机会 > 规则漏机会
- 规则漏掉 → 少赚一笔（机会成本）
- AI 幻觉多出 → 亏损真金白银（实际损失）
- **风险不对称**：宁漏 100 次，不错 1 次

### 陷阱 2：原始数据喂全量代币爆炸
- 22 个 endpoint × 多周期 = 单次 prompt 50~100 KB
- DeepSeek 响应慢（5~10 秒），长上下文反而抓不住重点
- 月成本上百元

### 陷阱 3：AI 和规则冲突时听谁的？
- 总听 AI → 规则形同虚设 = 黑盒
- 从不听 AI → AI 毫无意义
- 没有"部分听"的清晰规则 → 纠结

---

## 二、正确定位：AI 观察模式

把 AI 做成**副驾驶观察员**，与规则层**物理隔离**。

```
规则闭环（主路，V1）              AI 观察模式（副路，V1.1）
──────────────────────           ──────────────────────
A 追多 ★★★★☆ 入场/止损/止盈      D 观察：罕见组合候选
B 观望 ★★                        ⚠️ 纯度 75 + 衰竭 3 + Fair Value 上拐
C 反弹空 ★★★☆                    "规则未触发但值得关注"
                                  🤖 无价格，无仓位，仅文字提示

规则结论（主）       ←─不交叉─→     AI 观察（副）
```

---

## 三、3 条红线

| # | 红线 | 违反后果 |
|---|------|---------|
| 1 | AI **不能生成 A/B/C 主情景** | 主情景只来自规则层 |
| 2 | AI **不能生成价格/止损/止盈/仓位** | 只能文字描述"注意某组合" |
| 3 | AI 每个观察 **必须引用具体指标数值**（evidence-citing） | 无证据的句子后端强制删除 |

---

## 四、输入设计（不喂原始数据）

AI 看到的不是原始 HFD 响应，而是**规则层已计算好的加工数据**：

```python
class AIObserverInput(BaseModel):
    symbol: str
    tf: str
    current_price: float
    timestamp: int

    # 规则层产出（已加工）
    behavior: BehaviorScore          # 行为分数
    phase: PhaseState                # 阶段状态
    participation: ParticipationGate # 参与度
    levels: LevelLadder              # 关键位
    liquidity: LiquidityCompass      # 流动性
    plans_abc: list[TradingPlan]     # A/B/C 主方案

    # 原子摘要（不是完整 series）
    atom_summary: AtomSummary        # 每个原子取最新 1~5 个点
```

单次输入 **~2K tokens**，DeepSeek 成本 < 0.001 元/次。

---

## 五、输出设计（严格结构化）

AI 只能输出两类内容，Pydantic 强制校验：

```python
class AIObservation(BaseModel):
    type: Literal["opportunity_candidate", "conflict_warning"]
    attention_level: Literal["low", "medium", "high"]
    headline: str                    # 1 句话总结，≤ 30 字
    description: str                 # 详细说明，≤ 100 字
    evidences: list[AIEvidence]      # 至少 2 条证据

    # 严格禁止的字段（Pydantic 校验器会拒绝包含这些词的输出）
    # ❌ entry / stop / take_profit / price / position / 做多 / 做空 / 入场

class AIEvidence(BaseModel):
    indicator: str                   # 必须是 22 个 HFD 指标之一
    field: str                       # 指标里的具体字段
    value: float | str               # 具体数值
    note: str                        # 说明

class AIObserverOutput(BaseModel):
    observations: list[AIObservation]   # 最多 3 个
    narrative: str | None               # 可选的整体氛围描述
    conflict_with_rules: bool           # 是否与规则结论冲突
```

### Pydantic 校验器（后端强制）

```python
FORBIDDEN_WORDS = [
    "做多", "做空", "入场", "止损", "止盈", "开仓", "平仓", "追", "抄底", "逃顶",
    "entry", "stop", "tp", "long", "short"
]

@validator("description", "headline")
def no_trading_verbs(cls, v):
    for word in FORBIDDEN_WORDS:
        if word in v:
            raise ValueError(f"AI 输出包含禁止词: {word}")
    return v

@validator("evidences", each_item=True)
def indicator_must_exist(cls, ev):
    if ev.indicator not in KNOWN_22_INDICATORS:
        raise ValueError(f"AI 引用了不存在的指标: {ev.indicator}")
    return ev
```

校验失败 → 整个 AI 输出丢弃 → 大屏无 D 情景 → 不影响主路。

---

## 六、UI 呈现（物理隔离）

### A/B/C 主情景卡（规则产出）
- 白底 / 清爽
- 星级（0~5）
- 入场区间 / 止损 / 止盈
- 无 🤖 图标

### D 观察卡（AI 产出）
- **灰底 / 虚线边框**
- 🤖 图标 + 标签 "AI 观察（非规则触发）"
- 只有文字描述 + 注意力等级
- **无任何价格数字**
- 可折叠，默认展开
- 点击"查看证据"展开完整指标数值引用

```
┌────────────────────────────────────────────┐
│ 🤖 AI 观察（非规则触发）       注意力: 中  │
├────────────────────────────────────────────┤
│ 罕见组合：高纯度 + 衰竭 + 估值回拐          │
│                                             │
│ 当前 trend_purity = 75 / 100（上 4h 中枢）  │
│ trend_exhaustion = 3（连续衰竭 3 根）       │
│ fair_value 过去 2 根由降转升                │
│ 规则未触发因 power_imbalance 弱，但此组合   │
│ 历史上偏利多，建议留意。                    │
│                                             │
│ [查看 3 条证据] [忽略]                       │
└────────────────────────────────────────────┘
```

---

## 七、失败降级

```python
async def run_ai_observer(input_data: AIObserverInput) -> list[AIObservation]:
    try:
        output = await deepseek_client.call(prompt, input_data, timeout=15)
        validated = AIObserverOutput.parse_raw(output)
        return validated.observations
    except (TimeoutError, ValidationError, APIError) as e:
        logger.warning(f"AI 观察失败，本轮跳过: {type(e).__name__}", exc_info=True)
        return []  # 返回空 → 前端无 D 情景，不影响 A/B/C
```

**失败不影响主路**，这是和"兜底"的根本区别。

---

## 八、调用频率与成本

| 项 | 值 |
|---|---|
| 调用间隔 | 5 分钟（与 30m 级别主路节拍错开）|
| 单次输入 | ~2K tokens |
| 单次输出 | ~500 tokens |
| 单次成本 | < 0.001 元 |
| 日调用 | 288 次 |
| **日成本** | **< 0.3 元** |
| 月成本 | < 10 元 |

---

## 九、V1.1 完整 AI 用法（补充 4 → 5）

| # | 用途 | 触发 | 输入 | 输出 |
|---|------|-----|-----|------|
| 1 | 自然语言解释 | 用户点"为什么" | 规则快照 | 1 段话 |
| 2 | A/B/C 情景润色 | 规则生成后 | 方案 + 证据 | 润色后 premise + invalidation |
| 3 | 冲突二级裁决 | 规则内部冲突 | 两个冲突结论 | 仲裁理由 |
| 4 | 日终复盘 | 每日 00:00 | 当日信号日志 | 胜率分析 + 调参建议 |
| **5** | **观察模式（本文档）** | **每 5 分钟** | **规则快照 + 原子摘要** | **D 情景候选** |

---

## 十、为什么这比"AI 兜底"更好

| 用户担心 | "AI 兜底"方案 | "AI 观察"方案 |
|---------|--------------|---------------|
| 规则漏机会 | ✅ AI 全权判决 | ✅ D 情景承接 |
| AI 幻觉 | ❌ 可能输出假价格假止损 | ✅ 物理禁止输出交易参数 |
| 代币成本 | ❌ 50K/次，月百元 | ✅ 2K/次，月 10 元 |
| 可解释性 | ❌ 黑盒 | ✅ 必须引用具体指标数值 |
| 冲突处理 | ❌ 和规则纠缠 | ✅ 物理隔离，A/B/C ≠ D |
| 失败容忍 | ❌ AI 挂 = 大屏空 | ✅ AI 挂 = D 消失，A/B/C 照常 |

---

## 十一、实施节拍（V1.1）

**V1 先完成规则闭环，AI 观察在 V1.1 引入**，不提前。

依赖：
- V1 的 `DashboardSnapshot` 稳定（作为 AI 输入）
- V1 的日志系统完整（便于调试 AI 幻觉）
- V1 在真实数据跑过 1 周，积累调参经验
