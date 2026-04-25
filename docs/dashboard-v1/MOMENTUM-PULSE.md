# 动能能量柱 + 目标投影（Momentum Pulse + Target Projection）· 设计规划 v0.1

> 「先说后做」的落档版。本文是 Step 7（V1.1 增量）的单一真源；
> 任何前后端字段、阈值、配置出现歧义时，以此处为准。
>
> 父文档：[`MASTER-PLAN.md`](../MASTER-PLAN.md) · 关联文档：
> [`INDICATOR-COMBINATIONS.md`](INDICATOR-COMBINATIONS.md) ·
> [`ARCHITECTURE.md`](ARCHITECTURE.md)

---

## 0. 一句话定位

不预测价格，而是回答两个问题：

1. **动能能量柱**：现在多空哪边在烧油？还能烧多久？（一眼看强度 + 持续力）
2. **目标投影**：油烧完之前，价格的"磁吸目的地"分布在哪？（一眼看上下方向 + 距离 + 置信度）

**不是预测器**，是「能量预算 + 磁吸价位」的可视化。任何文案、提示、代码注释都
必须强化这一点，避免被解读成「下一根 K 线一定到 X 价」。

---

## 1. 总览（两张卡 / 一条灯带 / 三只时钟）

```
┌─ Card A · MomentumPulse（动能能量柱） ────────────────┐
│ ▲ 多头侧（绿）         倒计时 / streak              │
│ ░░░░░▓▓▓▓▓ ────────────                            │
│   中线（current price）                             │
│ ────────── ▓▓▓▓▓░░░░░                              │
│ ▼ 空头侧（红）         疲劳标签 / override 闪电      │
└─────────────────────────────────────────────────────┘

┌─ Card B · TargetProjection（目标投影） ──────────────┐
│ ────────────● 现价 ────────────                     │
│   T1 -1.2% 🛡 92,400 (📊 0.7)                      │
│   T2 -2.4% 💣 91,300 (📊 0.5)                      │
│   T1 +0.9% 🎯 96,500 (📊 0.6)                      │
│   T2 +2.6% 🎯 99,800 (📊 0.4)                      │
└─────────────────────────────────────────────────────┘

┌─ Multi-TF 三色灯带（卡 A 顶部 / 卡 B 顶部共享） ─────┐
│ 30m ●  1h ●  4h ◐    （绿=偏多 / 红=偏空 / 灰=中性） │
└─────────────────────────────────────────────────────┘

三只时钟（freshness chip，hover 可见）：
  🟢 实时（Binance WS · ms 级）
  🟡 半实时（K 线收盘 +5s）
  ⚪ 慢更新（5min / 30min / 1h / 4h）
```

---

## 2. Card A · MomentumPulse（动能能量柱）

### 2.1 视觉结构

垂直双向柱图。中线 = 当前价；柱长 = 动能强度（0~100）；柱色 = 方向。

| 区域 | 含义 | 数据源 |
|------|------|--------|
| 上半绿柱 | 多头动能强度（0~100） | `momentum_score_long` |
| 下半红柱 | 空头动能强度（0~100） | `momentum_score_short` |
| 中线发光 | `direction_override` 触发（CHoCH / sweep / pierce） | `override.kind` + `override.bars_since` |
| 顶部数字 | `streak`（连续 N 根同侧） | `streak_bars` + `streak_side` |
| 角标 | 疲劳标签 | `fatigue_state ∈ {fresh, mid, exhausted}` |

### 2.2 信息密度（三层）

1. **L1 主视觉**：能量柱长度 + 颜色 + 中线发光（一眼看出"烧多大、谁烧、刚不刚发生大事件"）。
2. **L2 数字层**：`score_long` / `score_short` 数值、`streak_bars` 连续根数、`fatigue_state` 疲劳标签。
3. **L3 Tooltip**：完整证据链（power_imbalance.ratio、cvd_slope_sign、resonance 计数、exhaustion）。

### 2.3 交互

- **hover**：弹证据 tooltip，列每个分量得分与原始值（"power_imbalance ratio=2.4 → +25"）。
- **direction_override 命中**：中线 1.5s 闪电高光（不蹦不抖），同时角标显示 `⚡ CHoCH↑ 3 根前`。
- **数据 stale**：柱体半透明 + 灰色斜纹叠加；hover 显示 `atoms_xxx 陈旧 N 秒`。
- **TF 切换**：柱长平滑过渡 300ms，避免数字闪跳引发误读。

### 2.4 计算公式（伪代码）

```python
# === 多头动能 ===
score_long = clamp(0, 100,
      25 * 1[power_imbalance.ratio ≥ pi_threshold and side == 'buy']
    + 20 * min(1, power_imbalance.streak / pi_streak_full)
    + 20 * 1[cvd_slope_sign == 'up']
    + 15 * (resonance_buy_count / max(1, resonance_min_count))   # 上限 1
    + 10 * (imbalance_green_ratio - imbalance_red_ratio + 0.5)   # 折算 0~1
    + 10 * 1[just_broke_resistance and pierce_atr_ratio ≥ atr_break_min]
)

# === 空头动能 ===  对称
score_short = ... (镜像 imbalance_red / cvd_down / resonance_sell / just_broke_support)

# === streak ===
if score_long > score_short:
    side = 'long'; streak_bars = power_imbalance_streak if streak_side == 'buy' else 0
elif score_short > score_long:
    side = 'short'; streak_bars = power_imbalance_streak if streak_side == 'sell' else 0
else:
    side = 'neutral'; streak_bars = 0

# === 疲劳 ===
fatigue_state = (
    'exhausted' if (trend_exhaustion_last.exhaustion ≥ exhaustion_alert
                    and exhaustion_streak ≥ exhaustion_consecutive_min
                    and exhaustion_type matches side)
    else 'mid'  if trend_saturation.progress ≥ saturation_mid
    else 'fresh'
)

# === direction_override ===  优先级最高的"事件性"反向警告/确认
override = None
if choch_latest and choch_latest.bars_since ≤ override_max_bars:
    override = { kind: 'CHoCH', dir: choch_latest.direction, bars: bars_since }
elif sweep_last and (anchor_ts - sweep_last.ts) / tf_ms ≤ override_max_bars:
    override = { kind: 'Sweep', dir: 'bullish' if 'bullish_sweep' else 'bearish', bars: ... }
elif (just_broke_resistance or just_broke_support) and pierce_atr_ratio ≥ atr_break_min:
    override = { kind: 'Pierce', dir: 'bullish' if just_broke_resistance else 'bearish', bars: 0 }
```

> **铁律**：当 `override.dir` 与 `score` 主方向冲突时，**不强行翻转 score**（保留原始动能），
> 仅在 UI 上以中线闪电 + 文案提示「⚡ 反向事件，警惕翻车」。把判断权交给用户/AI。

### 2.5 数据来源

| 字段 | 来自 `FeatureSnapshot` | 频率（30m 周期） |
|------|----------------------|----------------|
| `power_imbalance_last/recent/streak` | `atoms_power_imbalance` | K 线收盘 +5s |
| `cvd_slope/cvd_slope_sign` | `atoms_cvd` | K 线收盘 +5s |
| `imbalance_green/red_ratio` | `atoms_imbalance` | K 线收盘 +5s |
| `resonance_buy/sell_count` | `atoms_resonance_events` | 事件触发即落库 |
| `trend_exhaustion_last/streak` | `atoms_trend_exhaustion` | K 线收盘 +5s |
| `trend_saturation` | `atoms_trend_saturation` | 每 5 min |
| `choch_latest` | `atoms_choch_events` | 事件即落库 |
| `sweep_last` | `atoms_sweep_events` | 事件即落库 |
| `just_broke_*` / `pierce_atr_ratio` | `_nearest_levels_and_pierce` | K 线收盘派生 |

---

## 3. Card B · TargetProjection（目标投影）

### 3.1 视觉结构

水平 Gantt 条。**中点固定 = 现价**，左侧（远）→ 右侧（近）按 `distance_pct` 排列；
上下两半分别对应「上方目标」和「下方目标」。

```
                  现价 ●
─────────🛡──💣──◯───●───◯──🎯───
        T2  T1      T1  T2     ← 距离越远越淡
                        confidence = 透明度
```

每个目标项（`TargetItem`）包含：

| 字段 | 含义 |
|------|------|
| `kind` | `roi` / `pain` / `liq_heatmap` / `cascade_band` / `vacuum` / `nearest_level` |
| `side` | `above` / `below` |
| `tier` | `T1`（首要磁吸）/ `T2`（次级磁吸） |
| `price` | 目标价 |
| `distance_pct` | 带正负 |
| `confidence` | 0~1（颜色透明度） |
| `bars_to_arrive` | 估算到达需要的 K 线数（仅参考，附 ⏳ 角标） |
| `evidence` | 文案说明（"ROI T1 平均目标 / Pain max / Heatmap 0.78"） |

### 3.2 编码规则

| 类型 | 颜色 | 形状 | 优先级 |
|------|------|------|------|
| ROI（赚多远） | 金 🎯 | 圆点 | T1 ≥ T2 |
| Pain（洗多深） | 蓝 🛡️ | 圆点 | T1 ≥ T2 |
| Cascade Band（💣） | 橙 💣 | 方块 | 按 `intensity` |
| Heatmap（清算线） | 紫 🌡 | 三角 | 按 `intensity` |
| Vacuum（真空） | 浅蓝渐变 | 长条 | 单独标记 |
| Nearest Level（最近 R/S） | 灰 ◯ | 圆环 | 永远显示 |

### 3.3 confidence 计算

```python
confidence = clamp(0, 1,
      0.45 * source_weight                         # 不同来源固有权重（roi=0.9, heatmap=0.7, cascade=0.6, vacuum=0.5）
    + 0.25 * (1 - distance_pct / max_distance_pct) # 越近越可信
    + 0.20 * align_with_momentum                   # 0/1：方向是否与当前主动能一致
    + 0.10 * (1 - fatigue_decay)                   # 动能未疲劳时加分
)
```

### 3.4 `bars_to_arrive`（参考值，附 ⏳ 角标）

```python
# 用 ATR 做"K 线行进速度"的代理
bars_to_arrive = ceil(abs(price - last_price) / max(atr, 1e-9))
# 上限 max_bars_clip（默认 50），超过显示 "50+"
```

> 该值**仅作参考**，UI 必须挂 ⏳ 提示「估算值，不构成预测」。

### 3.5 兜底与降级

- 任一类型缺数据 → 该类型的 item 直接跳过（不补占位）。
- 总 item 数为 0 → 显示「目标数据不足，等下一根 K 线」+ 灰底空状态。
- `distance_pct > max_distance_pct`（默认 8%）→ 直接过滤（避免远端噪声盖过近端）。

---

## 4. Multi-TF 三色灯带

### 4.1 行为

- 默认显示 `30m / 1h / 4h` 三档（与后端 `SUPPORTED_TFS` 单一真源对齐）。
- 每档颜色 = 该 tf 的 `MomentumPulseView.dominant_side`：
  - 绿 = `long`，红 = `short`，灰 = `neutral`。
- 每档亮度 = `max(score_long, score_short) / 100`（弱信号偏暗）。
- 用户点击灯带某档 → 切换到该 tf 的卡片视图（不影响 dashboard 主 tf）。

### 4.2 后端契约

新增 `GET /api/momentum_pulse?symbol=BTC&tfs=30m,1h,4h`：

```jsonc
{
  "symbol": "BTC",
  "items": [
    {
      "tf": "30m",
      "view": MomentumPulseView,           // 完整对象
      "target": TargetProjectionView,      // 完整对象（用于切换 TF 时秒切）
      "anchor_ts": 1714000000000,
      "stale_tables": []
    },
    { "tf": "1h", ... },
    { "tf": "4h", ... }
  ]
}
```

实现走 `FeatureExtractor.extract` + `_derive_momentum_pulse` + `_derive_target_projection`，
不跑完整 `RuleRunner._assemble`，把延迟控制在 < 80ms。

### 4.3 切 TF 防抖

- 前端切 TF 时不卸载组件，**只 patch 数据**，保留柱体高度并 300ms 平滑过渡。
- 后端响应携带 `anchor_ts`，前端按 `anchor_ts` 去重，避免 WS 与 REST 并发覆盖。

---

## 5. 实时 vs 自动刷新（三只时钟）

### 5.1 数据频率分层

| 层级 | 数据 | 刷新源 | 时钟图标 |
|------|------|--------|----------|
| 实时 | `current_price` | Binance WS（`useLivePrice`） | 🟢 |
| 半实时 | 动能/目标主体 | K 线收盘 +5s 后端推 WS | 🟡 |
| 慢更新 | `trend_saturation` / heatmap / cascade | APScheduler 5/30/60/240 min | ⚪ |

每张卡顶部右侧显示一个时钟 chip，hover 看完整 freshness 信息：

```
🟢 价格 400ms 前
🟡 动能 23s 前 · 下次 4m37s
⚪ 饱和度 3m12s 前 · 下次 1m48s
```

### 5.2 K 线半成品提示

K 线尚未收盘时，动能数据来自上一根已收盘 K 线。卡 A 顶部显示倒计时：

```
⏱ 当前 30m K 线 12:43 收盘（还剩 14m22s）
```

让用户知道「我看到的动能是上一根的，下一刷新在 14 分钟后」。

---

## 6. 指标滞后性 & 缓解（3 条铁律）

| 指标 | 滞后量级 | 缓解 |
|------|----------|------|
| `power_imbalance` / `imbalance` / `cvd` | 收盘 +5s | 配 `direction_override` 抢跑事件 |
| `trend_exhaustion` / `trend_purity` | 收盘 +5s（30m K 线天然滞后 30 min） | 用 `fatigue_decay` 在 confidence 中折扣 |
| `trend_saturation` | 5 min | 仅参与 `fatigue_state`，不参与主动能 |
| `cascade_band` / `heatmap` | 30 min~4h | 仅参与 TargetProjection 的"地图"层，不参与方向 |
| `choch` / `sweep` / `resonance` | 事件即时 | 参与 `direction_override` 与 `score` 双通道 |

**铁律**：

1. **事件优先级 > 静态指标**：`direction_override` 命中时 UI 必须以闪电高亮，但**不翻转**主 score。
2. **多 TF 灯带预警**：单 tf 偏多但其他 tf 偏空时灯带变灰，提示用户「不同 tf 在打架」。
3. **fatigue_decay**：`fatigue_state` 直接乘入 confidence，让"看着强但其实快烧完"的信号不会被误读为强信号。

---

## 7. 数据契约（Pydantic / TS）

### 7.1 后端（`backend/rules/features.py`）

```python
class MomentumPulseView(BaseModel):
    score_long: int                     # 0~100
    score_short: int                    # 0~100
    dominant_side: Literal["long", "short", "neutral"]
    streak_bars: int                    # 同向连续根数
    streak_side: Literal["buy", "sell", "none"]
    fatigue_state: Literal["fresh", "mid", "exhausted"]
    fatigue_decay: float                # 0~1，confidence 折扣因子
    override: Optional[OverrideEvent]   # 抢跑事件
    contributions: list[ContribItem]    # 证据链（前端 tooltip）

class OverrideEvent(BaseModel):
    kind: Literal["CHoCH", "BOS", "Sweep", "Pierce"]
    direction: Literal["bullish", "bearish"]
    bars_since: int
    detail: str                         # "⚡ CHoCH↑ 破 93,800 · 3 根前"

class ContribItem(BaseModel):
    label: str                          # "power_imbalance"
    value: str                          # "ratio=2.4 streak=3"
    delta: int                          # 该分量贡献分（带正负）
    side: Literal["long", "short", "both", "none"]

class TargetItem(BaseModel):
    kind: Literal["roi", "pain", "cascade_band", "heatmap", "vacuum", "nearest_level"]
    side: Literal["above", "below"]
    tier: Literal["T1", "T2"]
    price: float
    distance_pct: float
    confidence: float                   # 0~1
    bars_to_arrive: int | None
    evidence: str                       # "ROI T1 平均目标 / Pain max / Heatmap 0.78"

class TargetProjectionView(BaseModel):
    above: list[TargetItem]             # 已按 distance asc 排序
    below: list[TargetItem]
    max_distance_pct: float             # 截断阈值（来自配置）
    note: str                           # "📍 目标 = 磁吸价位地图，不构成预测"
```

`FeatureSnapshot` 增加：

```python
momentum_pulse: MomentumPulseView | None = None
target_projection: TargetProjectionView | None = None
```

### 7.2 后端 DTO（`backend/models.py`）

新增 `MomentumPulseCard` / `TargetItemCard` / `TargetProjectionCard`，
字段与 view 一致；`DashboardCards` 增加：

```python
momentum_pulse: MomentumPulseCard | None = None
target_projection: TargetProjectionCard | None = None
```

### 7.3 前端（`frontend/src/lib/types.ts`）

镜像后端字段。同时把 `DashboardCards` 扩成包含 `momentum_pulse` / `target_projection`。
此外新增多 TF 接口的响应类型 `MomentumPulseMultiResp`。

---

## 8. 配置（`backend/config/rules.default.yaml`）

新增节点：

```yaml
# ════════════════════════════════════════════════════════════════════
# V1.1 · Step 7 · 动能能量柱 + 目标投影
# ════════════════════════════════════════════════════════════════════
momentum_pulse:
  thresholds:
    power_imbalance_min_ratio: 1.5      # 单根 power_imbalance |ratio| ≥ 此值算"放大"
    power_imbalance_streak_full: 3      # streak 达到此值即满分
    resonance_min_count: 2              # 共振计数到此值即满分
    atr_break_min: 0.3                  # pierce_atr_ratio ≥ 此值算"真穿越"
    saturation_mid: 50                  # progress ≥ 此值算"半满"，触发 fatigue=mid
    override_max_bars: 3                # 事件抢跑窗口（≤ N 根算"刚刚"）
  weights:                              # 总和需要 = 100
    power_imbalance: 25
    pi_streak: 20
    cvd_slope: 20
    resonance: 15
    imbalance_ratio: 10
    pierce: 10
  fatigue_decay:
    fresh: 0.0
    mid: 0.2
    exhausted: 0.5

target_projection:
  max_distance_pct: 0.08                # 8% 之外的目标过滤
  max_bars_clip: 50                     # bars_to_arrive 上限
  source_weights:
    roi: 0.90
    pain: 0.85
    cascade_band: 0.65
    heatmap: 0.70
    vacuum: 0.50
    nearest_level: 0.60
  per_side_topn: 5                      # 每侧最多保留 N 个 item
```

---

## 9. 边界 / 降级

| 场景 | 行为 |
|------|------|
| `atoms_power_imbalance` 全 0 → 已挂 `stale_tables` | `score_long/short = 0`，UI 灰柱 + 警告条 |
| `atr` 缺失 | `bars_to_arrive` 全 None；柱体 strength 仅减 `pierce` 分 |
| `cascade_bands` 为空 | TargetProjection 仅展示 ROI/Pain/Nearest（不报错） |
| `choch_latest` 缺失 | `override = None`；不影响主流程 |
| 跨币种小币种 | `_fmt_price` 自动切 4 位小数；strength_label 复用 `cards.py` 现有口径 |
| 单 TF 数据缺失 | 多 TF 灯带该档显示 ◇（"无数据"） |

---

## 10. 风险与陷阱（写在代码注释里）

1. **`trend_exhaustion.type` 与方向的对齐**：`type=Accumulation` 的 exhaustion 警告"上涨疲劳"，
   `type=Distribution` 的 exhaustion 警告"下跌疲劳"。`fatigue_state` 必须按当前 `dominant_side` 检查
   匹配类型，错配的 exhaustion 不应触发 fatigue。
2. **`power_imbalance` 全 0 ≠ 无失衡**：上游静默期会全 0，必须靠 `stale_tables` 区分，否则
   被当成"动能枯竭"会误导反向。
3. **`roi_limit_*` / `pain_*` 必须按 `type` 配 side**：`type=Accumulation` 的 ROI 在上方（多头目标），
   `type=Distribution` 的 ROI 在下方（空头目标）。绝对不能直接按"avg < last"判 side。
4. **`pierce_atr_ratio` 阈值不能过低**：< 0.3 容易把"擦线"算成"突破"，触发 override 误抢跑。
5. **多 TF 灯带不能跨 tf 复用 anchor**：每个 tf 独立 extract，独立 anchor_ts，独立 stale。

---

## 11. 实施步骤（Step 7.x）

### Step 7.1：S1 后端派生
1. `backend/rules/features.py`：新增 `MomentumPulseView` / `TargetProjectionView` / `TargetItem` / `OverrideEvent` / `ContribItem`。
2. `FeatureSnapshot` 增加两个可选字段。
3. `FeatureExtractor.extract` 末尾派生（私有函数 `_derive_momentum_pulse` / `_derive_target_projection`，从 cfg 读阈值）。
4. 单测：`backend/tests/test_momentum_pulse.py`，覆盖 5 个典型 case + 3 个降级 case。

### Step 7.2：S2 后端 DTO + cards + 多 TF API
1. `backend/models.py`：新增 3 个 Card DTO + `DashboardCards.momentum_pulse/target_projection`。
2. `backend/rules/modules/cards.py`：`build_dashboard_cards` 装入两张卡（view → card 直映）。
3. `backend/config/rules.default.yaml`：新增 `momentum_pulse` / `target_projection` 节。
4. `backend/api/momentum_pulse.py`：新接口 `/api/momentum_pulse`，并发跑多 tf。
5. WS 自动随 dashboard snapshot 推（DashboardCards 已包含）。

### Step 7.3：S3 前端
1. `frontend/src/lib/types.ts`：同步 `MomentumPulseCard` / `TargetItemCard` / `TargetProjectionCard` / `MomentumPulseMultiResp`。
2. `frontend/src/lib/api.ts`：新增 `fetchMomentumPulseMulti`。
3. `frontend/src/components/dashboard/momentum-pulse.tsx`：双向柱 + 多 TF 灯带 + 三只时钟。
4. `frontend/src/components/dashboard/target-projection.tsx`：水平甘特投影。
5. `frontend/src/pages/dashboard-page.tsx`：在「波段四维画像」之上新增两张卡。

### Step 7.4：S4 验证
1. `pytest backend/tests/test_momentum_pulse.py` 全绿。
2. `pnpm --dir frontend tsc --noEmit && pnpm --dir frontend build` 通过。
3. 真实数据 24h 跑测，记录误判 → `docs/dashboard-v1/MOMENTUM-TUNING-LOG.md`。

---

## 12. 不在本期做（明确剔除）

- ❌ 不做 K 线粒度的目标价回归（避免被理解为预测）。
- ❌ 不接 AI 重写卡片文案（文案完全规则化，便于排查）。
- ❌ 不引入新原子表（全部基于 `FeatureSnapshot` 已有字段派生）。
- ❌ 不做用户级阈值微调界面（先靠 `rules.default.yaml`，后续接 /settings）。

---

## 13. 与现有体系的关系

- **不影响**：`HeroStrip` / `BehaviorRadar` / `PhaseStateMachine` / 现有 capability scores。
- **复用**：`FeatureSnapshot` 全部已有字段；`build_dashboard_cards` 同款"view → card"模式；
  `cards.py` 的 `_fmt_price` / `_fmt_strength` 工具复用。
- **扩展**：`DashboardCards` 多两个可选字段；前端大屏增加两张卡（不动既有卡顺序）。

---

> 本文档版本：v0.1 · 写于 Step 7 启动前。任何字段/阈值变更必须同步更新此处与
> `rules.default.yaml`，并在 `MOMENTUM-TUNING-LOG.md` 记录调参动机。
