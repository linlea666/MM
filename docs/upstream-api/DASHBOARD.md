# 22 个指标 × 三大作战台 映射表

> 产品定位：**自用交易决策辅助工具**，不用于商业化。
> 
> 大屏有三大核心台：
> 1. **主力行为监控台** — 看主力在干什么
> 2. **市场结构地图** — 看关键位和流动性分布
> 3. **交易决策辅助台** — 看当前最优交易动作

---

## 一、三大台的职责

### 台 1：主力行为监控台

**核心问题**：主力在吸筹、派发、护盘、压盘、猎杀，还是已经衰竭？

**核心输出**：一句白话结论（吸筹 / 派发 / 护盘 / 压盘 / 猎杀 / 衰竭 / 共振启动 / 无明显主力）

### 台 2：市场结构地图

**核心问题**：撑压位在哪？流动性磁吸点在哪？前方有没有加速空间？

**核心输出**：
- 下方支撑价位 + 强度
- 上方阻力价位 + 强度
- 最近的磁吸目标位（上下各 Top 3）
- 真空带 / 筹码峰 / 猎杀血滴位置

### 台 3：交易决策辅助台

**核心问题**：现在该做多 / 做空 / 观望？入场点在哪？止损止盈在哪？

**核心输出**：
- 方向（做多 / 做空 / 观望）
- 入场区间
- 止损位
- 止盈 T1 / T2
- 失效条件
- 信号星级（★★★★★）

---

## 二、22 个指标 × 三大台 映射矩阵

✅ = 主要贡献    ◯ = 辅助贡献    — = 不参与

| # | 中文名 | indicator | 台 1 主力行为 | 台 2 结构地图 | 台 3 决策辅助 | 备注 |
|---|---|---|:---:|:---:|:---:|---|
| 1 | 趋势成本带 | `smart_money_cost` | ✅ | ✅ | ✅ | 三台核心 |
| 2 | 清算痛点地图 | `liq_heatmap` | — | ✅ | ✅ | 磁吸目标 |
| 3 | 密集博弈 | `absolute_zones` | ◯ | ✅ | ✅ | 撑压区 |
| 4 | 筹码真空区 | `fvg` | — | ✅ | ✅ | 缺口回补 |
| 5 | 主力大单行动 | `cross_exchange_resonance` | ✅ | — | ✅ | 真假突破核心 |
| 6 | 真实价值走势 | `fair_value` | ✅ | — | ✅ | 背离信号 |
| 7 | 筹码分布 | `inst_volume_profile` | — | ✅ | ◯ | 价格轴筹码 |
| 8 | 趋势撑压 | `trend_price` | ◯ | ✅ | ✅ | 右侧撑压 |
| 9 | 订单墙衰减 | `ob_decay` | — | ✅ | ✅ | 防线血量 |
| 10 | 微观成本线 | `micro_poc` | ✅ | ✅ | ✅ | 局部成本 |
| 11 | 趋势筹码纯度 | `trend_purity` | ✅ | ✅ | ◯ | 防线质量 |
| 12 | 均价重心偏移 | `poc_shift` | ✅ | — | ◯ | 暗吸筹/派发 |
| 13 | 趋势动态防线 | `trailing_vwap` | ◯ | ✅ | ✅ | 移动止损 |
| 14 | 趋势进度条 | `trend_saturation` | ✅ | — | ✅ | 变盘预警 |
| 15 | 流动性黑洞预警 | `liq_vacuum` | — | ✅ | ✅ | 单边加速带 |
| 16 | 多空失衡能量条 | `imbalance` | ✅ | — | ◯ | 单 K 净差 |
| 17 | 多空力量悬殊比 | `power_imbalance` | ✅ | — | ✅ | 逼空/逼多 |
| 18 | 能量耗竭 | `trend_exhaustion` | ✅ | — | ✅ | 反转信号 |
| 19 | 燃料库清算地图 | `liquidation_fuel` | — | ✅ | ✅ | 止盈目标 |
| 20 | 真实换手率节点 | `hvn_nodes` | — | ✅ | ✅ | 历史铁底/铁顶 |
| 21 | 流动性猎杀 | `liquidity_sweep` | ✅ | — | ✅ | 扫损反转 |
| 22 | 资金时间热力图 | `time_heatmap` | ◯ | — | ✅ | 信号时段过滤 |

---

## 三、按台整理｜每台需要消费哪些原子

### 🎯 台 1：主力行为监控台

**订阅原子**：
- `SmartMoneySegment`（最近 Ongoing 段 → 吸筹 or 派发）
- `ResonanceEvent`（近 30 分钟共振数量与方向 → 共振启动）
- `ImbalancePoint`（最近 10 根 → 持续净买卖）
- `PowerImbalancePoint`（近 5 根 → 逼空逼多）
- `TrendExhaustionPoint`（近 3 根 > 阈值 → 衰竭）
- `CvdPoint` + `Kline`（价格 vs CVD 背离 → 诱多诱空）
- `PocShiftPoint`（与 MA 对比 → 暗吸筹 / 暗派发）
- `TrendSaturationStat`（progress > 80% → 变盘在即）
- `TrendPuritySegment`（最近一段 purity → 防线可信度）

**决策输出**（受限选词）：
```
吸筹 | 派发 | 护盘明显 | 压盘明显 | 全球联合进场 | 猎杀中 | 趋势衰竭 | 无明显共振
```

### 🗺 台 2：市场结构地图

**订阅原子**：
- `Kline`（现价基准）
- `OrderBlock[]`（撑压投影到右侧）
- `AbsoluteZone[]`（密集博弈带）
- `MicroPocSegment[]`（局部成本射线）
- `HvnNode[]`（历史 Top 10 防线）
- `TrailingVwapPoint`（动态梯）
- `HeatmapBand[]`（上下方磁吸带）
- `LiquidationFuelBand[]`（燃料库）
- `VacuumBand[]`（真空加速区）
- `VolumeProfileBucket[]`（右侧筹码柱）
- `LiquiditySweepEvent[]`（血滴位置）
- `TrendPuritySegment[]`（为每条防线上色：纯度越高越红/绿）

**决策输出**：
```
上下方目标榜（Top 3 × 2）
每条防线的血量（OB Decay）
当前运行区域类型（成本上方 / 测试防守区 / 逼近高纯度阻力 / 进入真空区）
```

### ⚔️ 台 3：交易决策辅助台

**订阅原子**：
- 台 1 + 台 2 的全部输出
- `TimeHeatmapHour`（当前是否主力活跃时段）
- `SmartMoneySegment.status`（Ongoing 的段方向）

**决策输出**：
```json
{
  "direction": "long" | "short" | "wait",
  "confidence": 0.0 ~ 1.0,
  "entry_zone": [number, number],
  "stop_loss": number,
  "take_profit": [number, number],
  "valid_until": number,
  "invalidation": "string",
  "reasoning": ["string"],
  "stars": 1 ~ 5
}
```

---

## 四、5 类标准化结论语言（受限选词）

大屏所有台都只输出这 5 行结论，UI 永不重构。

### ① 主力结论（6 选 1）
> 吸筹 / 派发 / 护盘明显 / 压盘明显 / 全球联合进场 / 无明显共振

**触发映射**：

| 结论 | 触发条件（伪代码） |
|---|---|
| 吸筹 | `SmartMoneySegment.status = Ongoing && type = Accumulation` |
| 派发 | `SmartMoneySegment.status = Ongoing && type = Distribution` |
| 护盘明显 | `price` 回踩 Accumulation 段的 `avg_price` 后反弹 |
| 压盘明显 | `price` 反弹 Distribution 段的 `avg_price` 后回落 |
| 全球联合进场 | 近 30min 内 `ResonanceEvent.count >= 3` |
| 无明显共振 | 以上都不触发 |

### ② 结构结论（5 选 1）
> 成本上方运行 / 测试核心防守区 / 逼近高纯度阻力 / 进入低阻力真空区 / 前方黑洞加速空间

**触发映射**：

| 结论 | 触发条件 |
|---|---|
| 成本上方运行 | `price > SmartMoneySegment(Ongoing, Accum).avg_price + 0.5%` |
| 测试核心防守区 | `price` 进入 `abs(price - avg_price) < 0.3%` 的 OrderBlock |
| 逼近高纯度阻力 | 上方 1% 内有 `TrendPurity.purity > 80% && type = Distribution` 段 |
| 进入低阻力真空区 | `price` 在任何 `VacuumBand` 内 |
| 前方黑洞加速空间 | 上/下方最近 3% 内无 OrderBlock 且有 VacuumBand |

### ③ 流动性结论（4 选 1）
> 上方空头清算区更吸引 / 下方多头清算区更近 / 已完成一轮扫损 / 更像扫流动性而非真突破

**触发映射**：

| 结论 | 触发条件 |
|---|---|
| 上方空头清算区更吸引 | `上方最近 HeatmapBand.intensity > 下方最近 × 1.5` |
| 下方多头清算区更近 | 反之 |
| 已完成一轮扫损 | 近 10 根 K 线内有 `LiquiditySweepEvent` |
| 更像扫流动性而非真突破 | 突破后 3 根 K 线内价格回到突破位 |

### ④ 突破结论（5 选 1）
> 真突破概率高 / 假突破概率高 / 突破未获资金确认 / 已完成猎杀回收 / 墙体衰减击穿概率升高

**触发映射**：

| 结论 | 触发条件 |
|---|---|
| 真突破概率高 | 突破 + 同时段 `ResonanceEvent.count >= 3` + `PowerImbalance.ratio > 3` + 前方 `VacuumBand` |
| 假突破概率高 | 突破 + `ResonanceEvent` 缺失 + 与 `FairValue` 背离 |
| 突破未获资金确认 | 突破 + `CvdPoint` 未同步创新 |
| 已完成猎杀回收 | 突破后出现 `LiquiditySweepEvent` 反向 |
| 墙体衰减击穿 | 目标防线 `OBDecay 透明度 < 30%` + 趋势方向向该防线 |

### ⑤ 交易结论（5 选 1）
> 回踩做多优先 / 反弹做空优先 / 追突破可行 / 等待扫损后反手 / 当前不值得交易

**触发映射**：

| 结论 | 触发条件 |
|---|---|
| 回踩做多优先 | 台 1 = 吸筹 / 护盘 && 台 2 = 测试核心防守区 |
| 反弹做空优先 | 台 1 = 派发 / 压盘 && 台 2 = 逼近高纯度阻力 |
| 追突破可行 | 台 2 = 进入真空区 && 台 4 = 真突破概率高 |
| 等待扫损后反手 | 台 1 = 猎杀中 && 近 3 根未出现 `LiquiditySweepEvent` |
| 当前不值得交易 | 信号冲突（多头与空头条件同时触发） OR 非 `TimeHeatmap` 活跃时段 |

---

## 五、六维评分引擎｜把原子压缩成 6 个 0~100 分数

每个分数都明确引用原子，方便后续回测和调优。

### 维度 1：主力参与度
```
f(ResonanceEvent.count_recent, PowerImbalance.ratio, TrendPurity.purity, CvdPoint.slope)
```

### 维度 2：多头优势分
```
f(SmartMoneySegment[Accum].exists, price > avg_price, 
  下方 OrderBlock 质量, 下方 HvnNode 密度, FairValue 抬升)
```

### 维度 3：空头优势分
```
f(SmartMoneySegment[Dist].exists, price < avg_price, 
  上方 OrderBlock 质量, 上方 HvnNode 密度, FairValue 走弱)
```

### 维度 4：突破确认分
```
f(破关键 OrderBlock, ResonanceEvent.count, PowerImbalance.ratio, 
  前方 VacuumBand, TimeHeatmap 活跃度)
```

### 维度 5：反转概率分
```
f(LiquiditySweepEvent 近期, FairValue 背离, 
  TrendExhaustion 飙升, HeatmapBand 刺穿回收)
```

### 维度 6：交易价值分（最终决定）
```
交易价值 = (max(多头, 空头) × 突破确认 / 100 + 反转概率 × 0.3) × TimeHeatmap 系数
```

其中 `TimeHeatmap 系数 = 当前小时活跃度 / 24h 平均活跃度`，不在活跃时段直接 × 0.5。

---

## 六、MVP 优先级（P0 先做哪几个）

不是 22 个都要一起上。P0 先跑通：

### P0 Week 1（最小闭环）
**采集 + 存储**：
- ✅ `smart_money_cost`（台 1 + 台 2 + 台 3 的核心）
- ✅ `trend_price`（台 2 撑压，顺带 `ob_decay`）
- ✅ `cross_exchange_resonance`（台 1 + 台 3 的真假突破判别）
- ✅ `liq_heatmap`（台 2 + 台 3 的目标位）

**输出**：一张图能同时画出：
- K 线 + 现价
- 上下绿红带（smart_money_cost）
- 右侧撑压（trend_price）
- 磁吸热区（liq_heatmap）
- 跨所共振圆点（resonance）

### P0 Week 2（结论引擎）
**补指标**：
- ✅ `trend_purity`（给防线上色）
- ✅ `liquidity_sweep`（血滴标记）
- ✅ `trend_saturation`（台 1 变盘预警）
- ✅ `time_heatmap`（台 3 活跃度过滤）

**输出**：5 类结论 + 六维评分 + 作战建议卡片。

### P1（深化）
- 剩余 14 个指标全部接入
- 多周期共振矩阵
- 多币种机会扫描榜

---

## 七、文档引用关系

```
README.md
   ↓ 列出 22 个 endpoint
endpoints/*.md
   ↓ 每个 endpoint 的字段对应
ATOMS.md
   ↓ 23 个原子定义
DASHBOARD.md (本文档)
   ↓ 原子如何拼装成三大台
[大屏前端代码]
```

**数据流向**：HFD 接口 → `endpoints/` 字段解析 → `ATOMS.md` 原子入库 → `DASHBOARD.md` 组装结论 → 大屏渲染。
