# 指标组合手册（V1 准确度的命门）

> 22 个指标如何**组合**使用，比用哪些指标更重要。
>
> 本文为每个"能力"定义严格的 3 层组合（主 / 确认 / 否决）+ 评分公式 + 已知陷阱。
> 对 GPT 建议的组合做了诊断和补强。

---

## 一、设计原则

### 原则 1：每个能力 3 层指标

```
┌─ 主指标（1~2 个）    决定标签"是什么"
├─ 确认指标（3~5 个）  给主指标加分（可信度）
└─ 否决指标（1~3 个）  即使主亮，否决亮 → 信号作废
```

**否决指标是最容易被忽视的关键**。例子：
- 主指标 smart_money_cost 说"吸筹段 Ongoing"
- 但否决指标 trend_purity 显示 purity=35（意志极弱）
- → 这是假吸筹，信号作废

### 原则 2：同一指标在不同能力中角色不同

```
trend_purity：
  ・能力 1 主力行为 → 否决指标（低纯度 = 假信号）
  ・能力 2 成本区   → 权重调节器（高纯度 = 成本线加粗）
  ・能力 4 撑压      → 主指标之一（给防线打可信度）
```

实现上必须分上下文管理，不能共用。

### 原则 3：组合评分必须给出公式

不接受"综合判断"这种模糊说法。每个组合的最终分数必须有明确的数学公式，能直接翻译成代码。

### 原则 4：必须标注已知陷阱

每个组合都列出"什么情况下会失效"。这是避免 V1 翻车的护栏。

---

## 二、指标角色矩阵（每个指标在 5 大能力中的角色）

| 指标 | 能力 1 主力行为 | 能力 2 成本/攻防线 | 能力 3 清算目标 | 能力 4 撑压可信 | 能力 5 真假突破 |
|---|---|---|---|---|---|
| smart_money_cost | 🔴 主 | 🔴 主 | — | 🟡 确 | — |
| trend_price (OB) | 🟡 确 | 🔴 主 | — | 🔴 主 | 🟡 确 |
| absolute_zones | 🟡 确 | 🔴 主 | — | 🔴 主 | 🟡 确 |
| micro_poc | 🟡 确 | 🔴 主 | — | 🟡 确 | — |
| trailing_vwap | — | 🔴 主 | — | 🟡 确 | — |
| volume_profile | — | 🟡 确 | — | 🟡 确 | — |
| hvn_nodes | — | 🔴 主 | — | 🔴 主 | 🟡 确 |
| trend_purity | ⚫ 否 | 🟡 确 | — | 🔴 主 | 🟡 确 |
| ob_decay | — | 🟡 确 | — | 🔴 主 | 🔴 主 |
| fair_value (div) | 🔴 主 (诱多诱空) | — | — | — | ⚫ 否 |
| imbalance_series | 🟡 确 | — | — | — | 🟡 确 |
| cvd_series | 🟡 确 | — | — | — | 🔴 主 |
| inst_vol_series | 🟡 确 | — | — | — | 🟡 确 |
| poc_shift | 🟡 确 (暗吸/暗派) | 🟡 确 | — | — | — |
| cross_exchange_resonance | 🔴 主 | — | — | — | 🔴 主 |
| power_imbalance | 🔴 主 | — | — | — | 🔴 主 |
| trend_exhaustion | 🔴 主 (衰竭) | — | — | — | ⚫ 否 |
| trend_saturation | 🔴 主 (变盘) | — | — | — | — |
| liq_heatmap | — | — | 🔴 主 | — | 🟡 确 |
| liquidation_fuel | — | — | 🔴 主 | — | 🟡 确 |
| liquidity_sweep | 🔴 主 (猎杀) | — | 🟡 确 | 🟡 确 | 🔴 主 |
| liq_vacuum | — | — | 🔴 主 | ⚫ 否 | 🟡 确 |
| fvg | — | — | 🟡 确 | — | — |
| time_heatmap | 全局门 | 全局门 | 全局门 | 全局门 | 🟡 确 |

> 🔴 主指标  🟡 确认指标  ⚫ 否决指标  — 不参与

---

## 三、能力 1：识别主力行为（在干什么）

> **回答的问题**：主力现在是在吸 / 派 / 护 / 压 / 诱 / 衰竭 / 变盘？

### 3.1 主行为识别（4 选 1）

#### 🔴 主指标
- `smart_money_cost.Ongoing` — 最后一段的 type + status

#### 🟡 确认指标（每个 +分）
- `cross_exchange_resonance.count_1h` — 同向共振次数
- `imbalance_series` 近 10 根合计方向
- `inst_vol_series` 近 10 根机构净量
- `poc_shift` 斜率（近 10 点）

#### ⚫ 否决指标（亮了直接降级）
- **`trend_purity < 50`** — 意志薄弱，吸/派只是噪音
- **`time_heatmap` 活跃度 < 0.5** — 垃圾时间，全部降级

#### 评分公式
```ts
type BehaviorScore = {
  accumulation: number;  // 0-100
  distribution: number;  // 0-100
  sideways: number;      // 0-100
  reversal: number;      // 0-100
};

function scoreBehavior(): BehaviorScore {
  // 主指标基础分
  const smcOngoing = smart_money_cost.findLast(s => s.status === 'Ongoing');
  let accumBase = smcOngoing?.type === 'Accumulation' ? 60 : 0;
  let distBase  = smcOngoing?.type === 'Distribution' ? 60 : 0;

  // 确认指标叠加（每个 +10）
  const resonanceBuy  = count1hWhere(r => r.direction === 'buy'  && r.count >= 3);
  const resonanceSell = count1hWhere(r => r.direction === 'sell' && r.count >= 3);
  accumBase += Math.min(resonanceBuy  * 3, 15);  // 最多 +15
  distBase  += Math.min(resonanceSell * 3, 15);

  const imbSum   = sumLast(imbalance_series, 10);
  if (imbSum > 0) accumBase += 8;
  if (imbSum < 0) distBase  += 8;

  const instVolSum = sumLast(inst_vol_series, 10);
  if (instVolSum > 0) accumBase += 7;
  if (instVolSum < 0) distBase  += 7;

  const pocSlope = slope(poc_shift, 10);
  if (pocSlope > 0) accumBase += 10;
  if (pocSlope < 0) distBase  += 10;

  // 否决降级
  const latestPurity = trend_purity.findLast(p => !p.end_time)?.purity ?? 0;
  if (latestPurity < 50) {
    accumBase *= 0.5;
    distBase  *= 0.5;
  }

  const activity = timeHeatmapActivity();
  if (activity < 0.5) {
    accumBase *= 0.4;
    distBase  *= 0.4;
  }

  // 反转专用（扫损 + 背离）
  const recentSweep = liquidity_sweep.findLast(s => (now - s.timestamp) < 30 * 60 * 1000);
  const fairValueDiv = calcFairValueDivergence();
  let reversal = 0;
  if (recentSweep && Math.abs(fairValueDiv) > 0.005) reversal = 70;

  // 横盘 = 其它都不强
  const sideways = Math.max(0, 60 - Math.max(accumBase, distBase, reversal));

  return {
    accumulation: Math.min(100, accumBase),
    distribution: Math.min(100, distBase),
    sideways,
    reversal,
  };
}

function pickMainBehavior(s: BehaviorScore): string {
  const max = Math.max(s.accumulation, s.distribution, s.sideways, s.reversal);
  if (max < 50) return '无主导';  // 数据不充分
  if (max === s.accumulation) return s.accumulation >= 75 ? '强吸筹' : '弱吸筹';
  if (max === s.distribution) return s.distribution >= 75 ? '强派发' : '弱派发';
  if (max === s.reversal) return '趋势反转';
  return '横盘震荡';
}
```

#### ⚠️ 已知陷阱
1. **段切换瞬间的短暂错位**：新段刚开始时 smart_money_cost 会与其它指标暂时不同步（1~3 根 K 线）。对策：要求"连续 3 根都是同一倾向"才切换标签。
2. **大波段内的局部反弹/回调**：大吸筹段里出现局部下跌，poc_shift 和 imbalance 可能短暂转空，但主标签不应翻转。对策：smart_money_cost 保持吸筹时，确认指标只加分不减分。
3. **低流动性时段的极值噪音**：活跃度 < 0.5 时 imbalance 和 power_imbalance 容易造假。对策：否决指标 time_heatmap 必须硬降级。

---

### 3.2 叠加警报（0~N 个，多选）

每个警报独立计算，可同时存在。

#### 警报 ①：诱多（⚠️ 价格涨但主力悄悄撤）
```ts
// 主指标：price 创新高 + fair_value 下行
triggered =
  price.isNewHigh(20)                           // 近 20 根新高
  && fairValueSlope(10) < 0                     // Fair Value 下行
  && cvdSlope(10) <= 0;                         // CVD 未同步创新

// 否决：如果 cross_exchange_resonance 近期有 buy 共振 >= 3 次 → 否决
if (resonanceBuyCount(30min) >= 3) triggered = false;

strength = triggered ? Math.min(100, Math.abs(fairValueDivergencePct) * 10000) : 0;
```

#### 警报 ②：诱空（镜像）
```ts
triggered =
  price.isNewLow(20)
  && fairValueSlope(10) > 0
  && cvdSlope(10) >= 0;
if (resonanceSellCount(30min) >= 3) triggered = false;
```

#### 警报 ③：共振爆发
```ts
const count1h = resonance.filter(r =>
  r.count >= 3 && (now - r.timestamp) < 60 * 60 * 1000
).length;
strength = Math.min(100, count1h * 15);  // 7 次 ≈ 100 分
```

#### 警报 ④：衰竭
```ts
// 主指标：trend_exhaustion 近 5 根最大值
const maxExh = Math.max(...trend_exhaustion.slice(-5).map(e => e.exhaustion));
strength = Math.min(100, maxExh * 10);

// 置信度加成：trend_saturation.progress > 90
if (trend_saturation.progress > 90) strength = Math.min(100, strength * 1.3);
```

#### 警报 ⑤：变盘临近
```ts
const progress = trend_saturation.progress;
if (progress >= 80) strength = Math.min(100, (progress - 80) * 5);
```

#### 警报 ⑥：护盘中
```ts
const accumSeg = smart_money_cost.findLast(
  s => s.status === 'Ongoing' && s.type === 'Accumulation'
);
if (!accumSeg) return 0;
const testCount = countTestsNear(accumSeg.avg_price, 0.003);  // ±0.3%
strength = Math.min(100, testCount * 25);
```

#### 警报 ⑦：压盘中（镜像）

#### 警报 ⑧：猎杀进行中
```ts
const recentSweeps = liquidity_sweep.filter(
  s => (now - s.timestamp) < 30 * 60 * 1000
);
strength = Math.min(100, recentSweeps.length * 30);
```

---

### 3.3 与 GPT 方案的差异

| 指标 | GPT | 我 | 原因 |
|---|---|---|---|
| smart_money_cost | 主 | 主 | 一致 |
| fair_value | 主 | 主（诱多诱空） | 一致 |
| whale_action (resonance) | 主 | 主 | 一致 |
| poc_shift | 主 | 确 | **降级**：单独看 POC 重心容易误判（横盘时 POC 也会漂），必须配合价格 MA 一起看 |
| imbalance | 主 | 确 | 单根 K 线不足以作主指标 |
| trend_exhaustion | 主 | 主（警报） | 改为独立警报 |
| trend_saturation | 主 | 主（警报） | 改为独立警报 |
| **trend_purity** | ❌ 缺 | **⚫ 否决** | **关键遗漏**：没有纯度就无法过滤假吸筹 |
| **power_imbalance** | ❌ 缺 | 主（警报） | **关键遗漏**：碾压比是主力"动手"的最强实时信号 |
| **liquidity_sweep** | ❌ 缺 | 主（反转/猎杀警报） | **关键遗漏**：没有扫损信号就无法识别"猎杀 / 反转" |

---

## 四、能力 2：找主力成本区和真实攻防线

> **回答的问题**：下方最关键护盘带在哪？上方最关键压制带在哪？哪条还厚哪条已薄？

### 4.1 候选位收集（5 个来源）

#### 🔴 主指标（每个都贡献候选位）

| 来源 | 字段 | 说明 | 基础权重 |
|---|---|---|---|
| `smart_money_cost` | avg_price + status + type | 主力成本带，Ongoing 权重 × 1.5 | 1.0 |
| `trend_price` | order_blocks.avg_price | 右侧投影撑压 | 0.9 |
| `absolute_zones` | bottom_price / top_price | 密集博弈带（矩形） | 0.9 |
| `micro_poc` | poc_price | 微观局部成本 | 0.6 |
| `hvn_nodes` | price (rank 1~10) | 历史 Top 10 换手节点 | 1.0 × (11-rank)/10 |
| `trailing_vwap` | resistance / support | 动态防线 | 0.7 |

### 4.2 权重调节（🟡 确认指标）

每条候选位用以下规则打分：

```ts
function scoreLevel(candidate: LevelCandidate): number {
  let score = candidate.baseWeight * 50;  // 基础 50

  // trend_purity 加权：段纯度越高，线越值钱
  const segment = findPuritySegmentContaining(candidate.startTime);
  if (segment) {
    score *= (segment.purity / 100 + 0.5);  // purity 50 → ×1.0, 100 → ×1.5
  }

  // ob_decay 衰减：OB 被测试过多少次
  if (candidate.type === 'OrderBlock') {
    const decayPct = calcObDecay(candidate);
    score *= (1 - decayPct);  // 衰减 70% → ×0.3
  }

  // volume_profile 加成：该价位本身成交量大
  const vpWeight = getVolumeProfileWeight(candidate.price);
  score *= (1 + vpWeight * 0.3);

  // 新鲜度：近期形成的权重更高
  const ageDays = (now - candidate.startTime) / (86400 * 1000);
  score *= Math.max(0.5, 1 - ageDays * 0.05);  // 每天衰减 5%，下限 0.5

  return score;
}
```

### 4.3 候选位合并

```ts
// 合并相距 < 0.3% 的同类型候选位
function mergeCandidates(candidates: LevelCandidate[]): LevelCandidate[] {
  const sorted = candidates.sort((a, b) => a.price - b.price);
  const merged: LevelCandidate[] = [];
  for (const c of sorted) {
    const last = merged[merged.length - 1];
    if (last && last.type === c.type &&
        Math.abs(c.price - last.price) / last.price < 0.003) {
      last.price = (last.price + c.price) / 2;
      last.score += c.score;
      last.sources.push(...c.sources);
    } else {
      merged.push({ ...c, sources: [c.source] });
    }
  }
  return merged;
}
```

### 4.4 每档位的标签生成

```ts
function labelLevel(level: LevelCandidate): string {
  const sources = level.sources.map(s => SOURCE_LABEL[s]).join(' + ');

  // 类型判定
  let type = '';
  if (level.sources.includes('smart_money_cost')) type += '成本区';
  if (level.sources.includes('absolute_zones')) type += (type ? ' + ' : '') + '博弈区';
  if (level.sources.includes('hvn_nodes')) type += (type ? ' + ' : '') + '筹码峰';

  // 测试状态
  const testCount = countTestsNear(level.price, 0.003);
  const status =
    testCount === 0 ? '未测试' :
    testCount === 1 ? '首次测试' :
    testCount <= 3 ? `已测试 ${testCount} 次` :
    '已测试多次(警惕)';

  // 血量
  const decayPct = level.sources.includes('OrderBlock') ? calcObDecay(level) : 0;
  const strength = decayPct > 0.7 ? '濒危' : decayPct > 0.3 ? '中等' : '完整';

  // 适合场景
  let fit = '';
  if (decayPct > 0.7) fit = '墙已薄，等突破';
  else if (testCount === 0) fit = '首测最值得做';
  else if (testCount >= 3) fit = '警惕假破';
  else fit = '可做反弹';

  return `${sources} | ${type} | ${status} | 强度${strength} | ${fit}`;
}
```

### 4.5 ⚠️ 已知陷阱
1. **smart_money_cost Completed 段的 avg_price 长期无意义**：只有 Ongoing 段的成本带最值钱。对策：Completed 段权重衰减快（4.2 中的 ageDays 衰减）。
2. **absolute_zones 411 个太多会糊屏**：对策：只保留距离现价 ±5% 且 score > 30 的。
3. **HVN Top 1 可能远离现价**：不该用它作为"当前撑压"，只作为"历史铁底/铁顶"参考。
4. **ob_decay 的衰减算法 HFD 不给**：只能自己根据"被测试次数"推断，可能和真实主力意图有偏差。

### 4.6 与 GPT 方案的差异

| 指标 | GPT | 我 | 原因 |
|---|---|---|---|
| smart_money_cost | 主 | 主 | 一致 |
| trend_price | 主 | 主 | 一致 |
| micro_poc | 主 | 主 | 一致 |
| trailing_vwap | 主 | 主 | 一致 |
| volume_profile | 主 | 确 | 降级：连续分布不如 HVN 尖锐 |
| hvn_nodes | 主 | 主 | 一致 |
| **absolute_zones** | ❌ 缺 | **主** | **关键遗漏**：密集博弈带是最直接的"攻防线"可视化 |
| **ob_decay** | ❌ 缺 | 确 | **关键遗漏**：没有 decay 就无法回答"这条线还厚不厚" |
| **trend_purity** | ❌ 缺 | 确 | **关键遗漏**：没有 purity 就无法回答"这条线可信度多高" |

---

## 五、能力 3：找上下方的清算/磁吸目标

> **回答的问题**：下一步主力更可能把价格推向哪边拿单？止盈 T1/T2 在哪？

### 5.1 拆成 3 个子能力，不能混为一谈

GPT 把 5 个指标混一起，但这是错的 —— 它们分别回答不同问题：

| 子能力 | 问题 | 指标 |
|---|---|---|
| 3A | 上下方真正的清算磁吸带 | `liq_heatmap` + `liquidation_fuel` |
| 3B | 单边加速候选区（一旦进入就滑滑梯） | `liq_vacuum` + `fvg` |
| 3C | 刚发生的猎杀事件（用于反转判断） | `liquidity_sweep` |

把 3 个混在一起会造成"FVG 被当成清算目标"等错误。

### 5.2 3A：清算磁吸目标（最核心）

#### 🔴 主指标
- `liq_heatmap.heatmap_data[]` — 全价格轴清算单分布
- `liquidation_fuel[]` — 精细带 + 燃料浓度

#### 评分公式
```ts
function attractionScore(level): number {
  // liq_heatmap 层
  const heatmap = liq_heatmap.find(h => Math.abs(h.price - level) < 100);
  const heatIntensity = heatmap?.intensity ?? 0;

  // liquidation_fuel 层（可能在带内）
  const fuel = liquidation_fuel.find(f => level >= f.bottom && level <= f.top);
  const fuelBonus = fuel?.fuel ?? 0;

  // 组合
  return heatIntensity * 100 + fuelBonus * 20;
}
```

#### 输出：上下各 Top 3 磁吸点
```ts
const upMagnets = collectPricesAbove(current_price, 0.05)  // 现价上方 5% 内
  .map(p => ({ price: p, score: attractionScore(p) / (1 + (p - current_price) / current_price * 5) }))
  .sort((a, b) => b.score - a.score)
  .slice(0, 3);

const downMagnets = /* mirror */;
```

### 5.3 3B：单边加速候选区

#### 🔴 主指标
- `liq_vacuum[]` — HFD 识别的真空带
- `fvg`（自己基于 klines 识别）—— 未回补缺口

#### 组合使用
```ts
// 现价前方（顺趋势方向）是否有 vacuum 或 fvg
function hasVacuumAhead(direction: 'up' | 'down'): boolean {
  const range = direction === 'up'
    ? [current_price, current_price * 1.03]
    : [current_price * 0.97, current_price];

  const inVacuum = liq_vacuum.some(v => rangesOverlap([v.low, v.high], range));
  const inFVG = identifyFVGs().some(g => rangesOverlap([g.low, g.high], range));

  return inVacuum || inFVG;
}
```

**用途**：
- 作为 `真突破启动` 阶段触发的必要条件之一
- 作为 `黑洞加速` 阶段触发的核心条件

### 5.4 3C：已发生的猎杀事件

#### 🔴 主指标
- `liquidity_sweep[]`

这个不是"目标"，是"已发生"。用途：
- 判断之前的清算带是否已被扫过（扫过的不再是目标）
- 识别"扫损反转"机会（见能力 5）

```ts
// 判断某个清算带是否"已被消化"
function isMagnetConsumed(level: number): boolean {
  return liquidity_sweep.some(s => {
    const priceMatch = Math.abs(s.price - level) / level < 0.002;
    const recent = (now - s.timestamp) < 6 * 60 * 60 * 1000;  // 6 小时内
    return priceMatch && recent;
  });
}

// 从磁吸目标中剔除已消化的
const validUpMagnets = upMagnets.filter(m => !isMagnetConsumed(m.price));
```

### 5.5 ⚠️ 已知陷阱
1. **FVG 不是清算目标，是缺口目标**：磁吸机制类似但性质不同。UI 上要用不同颜色区分。
2. **已被扫过的清算带很可能不再磁吸**：必须用 liquidity_sweep 做"消化检查"。
3. **liquidation_fuel 的 fuel 值分布未知**：先按 `fuel > 3` 当强信号，运行后再调阈值。

### 5.6 与 GPT 方案的差异

| 指标 | GPT | 我 | 原因 |
|---|---|---|---|
| liq_heatmap | 主 | 主(3A) | 一致 |
| liquidation_fuel | 主 | 主(3A) | 一致 |
| liquidity_sweep | 主 | 主(3C) | **分离**：sweep 不是目标，是事件 |
| fvg | 主 | 主(3B) | **分离**：fvg 不是清算目标，是缺口 |
| liq_vacuum | 主 | 主(3B) | **分离**：vacuum 是加速区不是目标 |

---

## 六、能力 4：识别真正有效的支撑阻力

> **回答的问题**：R3~S3 各档位的可信度多高？是首测还是末期？适合反弹还是突破？

### 6.1 主指标（决定候选位）

同 4.1 的 5 个来源（smart_money_cost / trend_price / absolute_zones / hvn_nodes / micro_poc）。

### 6.2 🟡 确认指标（给可信度打分）

| 指标 | 贡献 | 说明 |
|---|---|---|
| `trend_purity` | +10~30 | purity ≥ 80 → +30；60~80 → +15；<60 → 0 |
| `ob_decay` | -40~0 | decay ≥ 70% → -40；30~70% → -20；<30% → 0 |
| `volume_profile` | +5~15 | 该价位 VP.total 在历史 Top 20% → +15 |
| `liquidity_sweep` | -30 | 该价位近期被扫 → -30（已失效的阵地） |
| `trailing_vwap` | +10 | 当前 resistance/support 贴近该位 → +10 |

### 6.3 ⚫ 否决指标

```ts
// liq_vacuum 否决：位于真空带内的撑压不可信
if (isInsideVacuum(level)) score *= 0.3;

// 多次测试失败
const failedTestCount = countFailedTests(level);  // 测试后反向突破的次数
if (failedTestCount >= 2) score *= 0.5;
```

### 6.4 状态判定

每个位自动输出 5 个属性（你最早的需求）：

```ts
type LevelStatus = {
  source: string[];        // ['smart_money_cost', 'hvn_#3']
  strength: 'strong' | 'medium' | 'weak';
  test_count: number;
  decay_pct: number;       // 0 = 完整, 1 = 已耗尽
  fit: 'first_test_good' | 'worn_out' | 'can_break' | 'observe';
  signal_type: 'support' | 'resistance' | 'pivot';
};

function labelLevel(level): LevelStatus {
  const score = scoreLevel(level);

  const strength =
    score >= 70 ? 'strong' :
    score >= 40 ? 'medium' : 'weak';

  const test_count = countTestsNear(level.price, 0.003);
  const decay_pct = level.isOB ? calcObDecay(level) : 0;

  let fit: string;
  if (decay_pct > 0.7) fit = 'worn_out';           // 墙已薄，等突破
  else if (test_count === 0) fit = 'first_test_good';  // 首测最强
  else if (test_count >= 4) fit = 'can_break';     // 多次测试，准备击穿
  else fit = 'observe';

  return { source: level.sources, strength, test_count, decay_pct, fit, ... };
}
```

### 6.5 ⚠️ 已知陷阱
1. **HVN 历史位可能已失效**：几个月前的 HVN 对当前行情影响微弱。对策：只采用距离现价 ±8% 内的 HVN。
2. **OB 衰减算法有主观性**：HFD 不提供，我们的估算不完美。对策：UI 上标注"衰减估算值"而非"精确值"。
3. **smart_money_cost 段 avg_price 在段结束后短时间内仍有效**：不要立刻把 Completed 段归零，给 3~10 根 K 线的衰减期。

### 6.6 与 GPT 方案的差异

| 指标 | GPT | 我 | 原因 |
|---|---|---|---|
| trend_cost / trend_price / vp / hvn / abs_zones / micro_poc / trend_purity | 主 | 主/确 | 基本一致 |
| ob_decay | 主 | 主 | 一致 |
| **fvg** | 主（错误分类）| **不参与能力 4** | FVG 是缺口/目标，不是撑压 |

---

## 七、能力 5：判断真假突破（V1 最具实战价值）

> **回答的问题**：这次突破可追吗？是真突破、假突破、扫损反转还是垃圾时间？

### 7.1 5 选 1 结论

```
真突破启动 / 真突破未获确认 / 假突破猎杀 / 扫损反转 / 垃圾时间异动
```

### 7.2 🔴 主指标（必查）

| 指标 | 角色 | 真突破要求 |
|---|---|---|
| `cross_exchange_resonance` | 主 | 近 3 根 K 线内 count ≥ 3 的同向共振 ≥ 2 次 |
| `power_imbalance` | 主 | 突破当根或前后 K 线 ratio > 3（同向） |
| `cvd_series` | 主 | CVD 与价格同步创新（不能背离） |
| `liquidity_sweep` | 主 | 突破后 3 根内出现反向 sweep → 假突破 |

### 7.3 🟡 确认指标

| 指标 | 加分情况 |
|---|---|
| `ob_decay` | 被突破的 OB decay > 0.5（已衰减的墙更容易真破） |
| `liq_vacuum` | 前方 5% 内有 vacuum 带（有加速空间） |
| `time_heatmap` | 当前活跃度 > 1.0（主力活跃时段） |
| `imbalance_series` | 突破根 imbalance > 阈值 |
| `hvn_nodes` | 破的是 HVN rank 1~5（含金量高） |
| `absolute_zones` | 破的是 absolute_zones 矩形顶/底 |

### 7.4 ⚫ 否决指标

| 指标 | 否决条件 |
|---|---|
| `fair_value` divergence | 突破时 Fair Value 与价格**反向** → 降级为"未获确认" |
| `trend_exhaustion` | 突破当根 exhaustion > 7 → 降级为"衰竭反转候选" |
| `time_heatmap` | 活跃度 < 0.5 → 强制"垃圾时间异动"，不论其它如何 |

### 7.5 评分公式
```ts
function judgeBreakout(breakoutLevel: Level): BreakoutJudgment {
  // Hard gate: 垃圾时间
  if (timeHeatmapActivity() < 0.5) {
    return { type: '垃圾时间异动', confidence: 0 };
  }

  let realScore = 0;   // 真突破分
  let fakeScore = 0;   // 假突破分

  // 主指标
  const resonanceRecent = resonance.filter(r =>
    r.count >= 3 &&
    r.direction === breakoutDirection(breakoutLevel) &&
    (now - r.timestamp) < 3 * tfMillis()
  ).length;
  realScore += Math.min(40, resonanceRecent * 15);

  const latestPI = power_imbalance.findLast(p => p.timestamp >= breakoutLevel.ts);
  if (latestPI && latestPI.ratio > 3) realScore += 20;

  const cvdCorr = cvdVsPriceCorrelation(10);
  if (cvdCorr > 0.7) realScore += 15;

  const reverseSweep = liquidity_sweep.find(s =>
    s.timestamp >= breakoutLevel.ts &&
    s.type !== breakoutDirection(breakoutLevel)
  );
  if (reverseSweep) fakeScore += 40;

  // 确认指标
  if (breakoutLevel.ob_decay > 0.5) realScore += 10;
  if (hasVacuumAhead(breakoutDirection(breakoutLevel))) realScore += 10;
  if (timeHeatmapActivity() > 1.0) realScore += 5;

  // 否决
  const fvDiv = calcFairValueDivergence();
  if (Math.abs(fvDiv) > 0.01 && sign(fvDiv) !== sign(breakoutDirection)) {
    realScore *= 0.6;
  }

  const exhaustion = trend_exhaustion.findLast(e => e.timestamp >= breakoutLevel.ts);
  if (exhaustion && exhaustion.exhaustion > 7) {
    return { type: '衰竭反转候选', confidence: 0.6 };
  }

  // 结论
  if (fakeScore > 30 && fakeScore > realScore) {
    return { type: '假突破猎杀', confidence: fakeScore / 100 };
  }
  if (realScore >= 70) {
    return { type: '真突破启动', confidence: realScore / 100 };
  }
  if (realScore >= 40) {
    return { type: '真突破未获确认', confidence: realScore / 100 };
  }
  return { type: '方向不明', confidence: 0.3 };
}
```

### 7.6 ⚠️ 已知陷阱
1. **"突破后 3 根内反向 sweep"**：tf 不同时，3 根的时长差很大（30m = 90min，4h = 12h）。sweep 滞后出现时依然是假突破的证据。对策：每个 tf 单独配阈值。
2. **共振延迟到达**：K 线刚收盘时 resonance 可能还没推送，应等 +3s 再判断，或等第二根 K 线确认。
3. **power_imbalance 的 ratio=0 大量存在**：要过滤 ratio=0 的条目后再判断。
4. **ob_decay 我们自己算**：阈值 0.5 是经验值，V1 先跑，后续调参。

### 7.7 与 GPT 方案的差异

| 指标 | GPT | 我 | 原因 |
|---|---|---|---|
| whale_action (resonance) | 主 | 主 | 一致 |
| fair_value | 主 | ⚫ 否决 | **重分类**：FV 背离不是"加分项"而是"否决项" |
| imbalance | 主 | 确 | 单 K 不足以主导 |
| power_imbalance | 主 | 主 | 一致 |
| liquidity_sweep | 主 | 主 | 一致 |
| ob_decay | 主 | 确 | 降级：只影响"该墙是否真的容易破" |
| liq_vacuum | 主 | 确 | 降级：是"加速空间"而非"真假判定" |
| time_heatmap | 主 | ⚫ 否决 / 🟡 确 | 双重身份：活跃度 < 0.5 硬否决，其它时候加分 |
| **cvd_series** | ❌ 缺 | 主 | **关键遗漏**：CVD 同步 = 真突破最核心证据 |
| **trend_exhaustion** | ❌ 缺 | ⚫ 否决 | **关键遗漏**：突破根出现衰竭 = 假突破高概率 |

---

## 八、指标冲突处理总表

### 8.1 同一指标在不同能力中的角色不冲突

每个能力的计算上下文是独立的，同一个指标读取同一份数据但用不同的权重函数。代码上：

```ts
// 每个能力一个独立的 scorer 函数
const behaviorScore = scoreBehavior(atoms);
const levelScore = scoreLevels(atoms);
const magnetScore = scoreMagnets(atoms);
const supportResistScore = scoreSR(atoms);
const breakoutScore = scoreBreakout(atoms);

// 共享原子数据，独立评分上下文
```

### 8.2 能力之间的冲突裁决

当 5 个能力输出不一致时（例如：能力 1 说吸筹 80，能力 5 说假突破 75），用以下优先级：

```
实时硬事件 > 短期结构 > 长期倾向

硬事件（最高优先级）：
  liquidity_sweep 发生 / power_imbalance > 3 出现 / 重大共振爆发
短期结构（中优先级）：
  突破/跌破关键位 / 段切换 / 警报触发
长期倾向（低优先级）：
  smart_money_cost.Ongoing 段方向 / HVN 趋势
```

**实现**：高优先级信号可以压过低优先级的"结论"。

```ts
function finalDecision(allScores): Decision {
  // 1. 硬事件压过一切
  if (hasRecentSweep(30min) && breakoutScore.type === '假突破猎杀') {
    return { action: '反手' };
  }

  // 2. 垃圾时间否决
  if (timeHeatmapActivity() < 0.5) {
    return { action: '观望', reason: '垃圾时间' };
  }

  // 3. 冲突：A/B 分数接近
  const top2 = sortedScores.slice(0, 2);
  if (top2[0] - top2[1] < 15) {
    return { action: '观望', reason: '信号分化' };
  }

  // 4. 正常决策
  return ...;
}
```

---

## 九、V1 实施路径

### 阶段 1 最小闭环（Week 1~2）
仅跑通 **能力 1 + 能力 4 + 能力 5 的简化版**（不做叠加警报、不做反转判定）：

- 能力 1 简化：只输出 吸筹 / 派发 / 横盘 3 选 1，无警报
- 能力 4 简化：只用 smart_money_cost + trend_price + hvn_nodes 3 个主指标
- 能力 5 简化：只输出 真突破 / 假突破 / 不明

### 阶段 2 补齐结构（Week 3~4）
- 补能力 2 全套（含 trend_purity / ob_decay）
- 补能力 3 全部 3 个子能力
- 补能力 1 的 8 个叠加警报
- 补能力 5 的完整否决逻辑

### 阶段 3 参数调优（Week 5+）
- 跑一周真实数据，对每个能力的阈值做记录
- 把所有 "15" "70" 等魔数改为可配置参数
- 基于 AI 日终复盘的建议做定向调整（V1.1）

---

## 十、相关文档

- [PLAN.md](./PLAN.md) — V1 总体方案
- [PLAN-v1.1-ai-augmented.md](./PLAN-v1.1-ai-augmented.md) — V1.1 AI 增强
- [../upstream-api/ATOMS.md](../upstream-api/ATOMS.md) — 原子数据模型
- [../upstream-api/endpoints/](../upstream-api/endpoints/) — 每个指标的字段文档
