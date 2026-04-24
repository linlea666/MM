# 原子数据模型（Atoms）

> 把 22 个指标接口的返回数据，归一化成 **10 类"原子"**。这是存储层和指标视图层之间的统一契约。
> 
> 原则：**原子 = 不再分解的最小数据单元**。下游所有消费者只认原子，不认 HFD 原始响应。

---

## 设计原则

1. **一份 klines 全局共用**：22 个接口都返回 klines，我们只入库一份（来自 Binance，不用 HFD 的）
2. **时间戳统一用毫秒 epoch**（`number`，不是 ISO 字符串）
3. **上游字段名一律保留在原子层**，改名在"视图层"做（方便上游改字段时只改一处）
4. **所有原子强制带 `symbol / tf / source` 索引维度**，方便多币种/多周期/多源切换
5. **事件型原子按时间戳去重**，状态型原子按 (symbol, tf, ts) upsert

---

## 原子清单

| # | 原子名 | 类型 | 来源字段 | 供给的指标 |
|---|---|---|---|---|
| 1 | `Kline` | 时序 | `klines[]`（实际来自 Binance） | 全部 22 个 |
| 2 | `CvdPoint` | 时序 | `cvd_series[]` | fair_value / fvg / imbalance / liquidity_sweep / micro_poc / poc_shift |
| 3 | `ImbalancePoint` | 时序 | `imbalance_series[]` | 同上 |
| 4 | `InstVolPoint` | 时序 | `inst_vol_series[]` | 同上 |
| 5 | `VwapPoint` | 时序 | `vwap_series[]` | 同上 |
| 6 | `SmartMoneySegment` | 段式 | `smart_money_cost[]` | smart_money_cost |
| 7 | `OrderBlock` | 段式 | `order_blocks[]`（avg_price 版本） | trend_price / ob_decay |
| 8 | `AbsoluteZone` | 段式 | `order_blocks[]`（bottom/top 版本） | absolute_zones |
| 9 | `MicroPocSegment` | 段式 | `micro_poc[]` | micro_poc |
| 10 | `PocShiftPoint` | 时序 | `poc_shift[]` | poc_shift |
| 11 | `TrendPuritySegment` | 段式 | `trend_purity[]` | trend_purity |
| 12 | `TrailingVwapPoint` | 时序 | `trailing_vwap[]` | trailing_vwap |
| 13 | `PowerImbalancePoint` | 时序 | `power_imbalance[]` | power_imbalance |
| 14 | `TrendExhaustionPoint` | 时序 | `trend_exhaustion[]` | trend_exhaustion |
| 15 | `ResonanceEvent` | 事件 | `cross_exchange_resonance[]` | cross_exchange_resonance |
| 16 | `LiquiditySweepEvent` | 事件 | `liquidity_sweep[]` | liquidity_sweep |
| 17 | `HeatmapBand` | 价位 | `heatmap_data[]` | liq_heatmap |
| 18 | `VacuumBand` | 价位 | `liq_vacuum[]` | liq_vacuum |
| 19 | `LiquidationFuelBand` | 价位 | `liquidation_fuel[]` | liquidation_fuel |
| 20 | `HvnNode` | 价位 | `hvn_nodes[]` | hvn_nodes |
| 21 | `VolumeProfileBucket` | 价位 | `volume_profile[]` | inst_volume_profile |
| 22 | `TimeHeatmapHour` | 聚合 | `time_heatmap[]` | time_heatmap |
| 23 | `TrendSaturationStat` | 聚合 | `trend_saturation{}` | trend_saturation |

> 虽然列了 23 个原子，但语义上只有 **5 大类**：时序点 / 段式区间 / 事件 / 价位 / 聚合统计。下文按类组织。

---

## 一、时序点类（Time-series Point）

每根 K 线一条记录。存储：`(symbol, tf, ts)` 做主键。

### 1.1 `Kline` — K 线

```ts
type Kline = {
  symbol: string;   // "BTC"
  tf: string;       // "30m"
  ts: number;       // 毫秒时间戳，K 线开盘时间
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  source: "binance" | "okx" | "hfd";  // 数据源
};
```

**来源**：优先 Binance REST/WS，HFD 响应里的 klines 丢弃。

### 1.2 `CvdPoint` — 累计主动净成交量

```ts
type CvdPoint = {
  symbol: string;
  tf: string;
  ts: number;
  value: number;    // 累计净 delta
};
```

**来源**：HFD 响应的 `cvd_series: [[ts, value], ...]`。

### 1.3 `ImbalancePoint` — 单 K 线净差

```ts
type ImbalancePoint = {
  symbol: string;
  tf: string;
  ts: number;
  value: number;    // 本 K 线 buy_vol - sell_vol
};
```

**来源**：HFD `imbalance_series: [[ts, value], ...]`。

### 1.4 `InstVolPoint` — 机构成交量

```ts
type InstVolPoint = {
  symbol: string;
  tf: string;
  ts: number;
  value: number;    // 被识别为机构的净量
};
```

**来源**：HFD `inst_vol_series: [[ts, value], ...]`。

### 1.5 `VwapPoint` — VWAP 基准

```ts
type VwapPoint = {
  symbol: string;
  tf: string;
  ts: number;
  vwap: number;
};
```

**来源**：HFD `vwap_series: [[ts, value], ...]`。

### 1.6 `PocShiftPoint` — POC 重心轨迹

```ts
type PocShiftPoint = {
  symbol: string;
  tf: string;
  ts: number;
  poc_price: number;
  volume: number;
};
```

**来源**：HFD `poc_shift: [[ts, poc_price, volume], ...]`（注意是元组，不是对象）。

### 1.7 `TrailingVwapPoint` — 动态防线（绿/红梯）

```ts
type TrailingVwapPoint = {
  symbol: string;
  tf: string;
  ts: number;
  resistance: number | null;   // 红梯（上方阻力）
  support: number | null;      // 绿梯（下方支撑）
};
```

**来源**：HFD `trailing_vwap: [{resistance, support, timestamp}, ...]`。

### 1.8 `PowerImbalancePoint` — 多空力量悬殊

```ts
type PowerImbalancePoint = {
  symbol: string;
  tf: string;
  ts: number;
  buy_vol: number;
  sell_vol: number;
  ratio: number;    // buy_vol / sell_vol，碾压时可能 > 3
};
```

**来源**：HFD `power_imbalance: [{buy_vol, sell_vol, ratio, timestamp}, ...]`。

⚠️ 大部分 K 线此值为 0，表示"不在碾压状态"。

### 1.9 `TrendExhaustionPoint` — 能量耗竭

```ts
type TrendExhaustionPoint = {
  symbol: string;
  tf: string;
  ts: number;
  exhaustion: number;   // 0 = 无耗竭
  type: "Accumulation" | "Distribution";
};
```

**来源**：HFD `trend_exhaustion: [{exhaustion, type, timestamp}, ...]`。

---

## 二、段式区间类（Segment）

每段覆盖一个时间区间（start_time ~ end_time），记录该段的聚合指标。存储：`(symbol, tf, start_time, type)` upsert。

### 2.1 `SmartMoneySegment` — 主力成本段

```ts
type SmartMoneySegment = {
  symbol: string;
  tf: string;
  start_time: number;
  end_time: number;            // Ongoing 时跟随最新 K 线
  avg_price: number;           // 该段主力平均成本
  type: "Accumulation" | "Distribution";
  status: "Ongoing" | "Completed";
};
```

**来源**：HFD `smart_money_cost: [...]`。

### 2.2 `OrderBlock` — 订单块（avg_price 形态）

```ts
type OrderBlock = {
  symbol: string;
  tf: string;
  start_time: number;
  avg_price: number;
  volume: number;
  type: "Accumulation" | "Distribution";
};
```

**来源**：HFD `order_blocks: [...]`（trend_price / ob_decay 返回这种形态）。

### 2.3 `AbsoluteZone` — 密集博弈带（矩形）

```ts
type AbsoluteZone = {
  symbol: string;
  tf: string;
  start_time: number;
  bottom_price: number;
  top_price: number;
  type: "Accumulation" | "Distribution";
};
```

**来源**：HFD `order_blocks: [...]`（absolute_zones 返回这种形态，**字段与 OrderBlock 不同！**）。

### 2.4 `MicroPocSegment` — 微观成本段

```ts
type MicroPocSegment = {
  symbol: string;
  tf: string;
  start_time: number;
  end_time: number | null;     // 最新一段为 null
  poc_price: number;
  volume: number;
  type: "Accumulation" | "Distribution";
};
```

**来源**：HFD `micro_poc: [...]`。

### 2.5 `TrendPuritySegment` — 筹码纯度段

```ts
type TrendPuritySegment = {
  symbol: string;
  tf: string;
  start_time: number;
  end_time: number | null;
  avg_price: number;
  buy_vol: number;
  sell_vol: number;
  total_vol: number;
  purity: number;              // 百分比 0~100
  type: "Accumulation" | "Distribution";
};
```

**来源**：HFD `trend_purity: [...]`。

---

## 三、事件类（Event）

一次性事件，按时间戳天然去重。

### 3.1 `ResonanceEvent` — 跨所共振大单

```ts
type ResonanceEvent = {
  symbol: string;
  tf: string;
  ts: number;
  price: number;
  direction: "buy" | "sell";
  count: number;               // 参与共振的交易所数量
  exchanges: string[];         // 如 ["binance", "okx"]
};
```

**来源**：HFD `cross_exchange_resonance: [...]`。

### 3.2 `LiquiditySweepEvent` — 流动性猎杀

```ts
type LiquiditySweepEvent = {
  symbol: string;
  tf: string;
  ts: number;
  price: number;
  type: "bullish_sweep" | "bearish_sweep";
  volume: number;
};
```

**来源**：HFD `liquidity_sweep: [...]`。

---

## 四、价位类（Price Band / Node）

不是时间序列，是"横跨价格轴"的带或点。

### 4.1 `HeatmapBand` — 清算痛点带

```ts
type HeatmapBand = {
  symbol: string;
  tf: string;
  start_time: number;
  price: number;
  intensity: number;           // 0~1
  type: "Accumulation" | "Distribution";
};
```

**来源**：HFD `heatmap_data: [...]`。

### 4.2 `VacuumBand` — 流动性真空带

```ts
type VacuumBand = {
  symbol: string;
  tf: string;
  low: number;                 // 带底
  high: number;                // 带顶
};
```

**来源**：HFD `liq_vacuum: [[low, high], ...]`（元组格式）。

### 4.3 `LiquidationFuelBand` — 燃料库清算带

```ts
type LiquidationFuelBand = {
  symbol: string;
  tf: string;
  bottom: number;
  top: number;
  fuel: number;                // 燃料浓度（越高越容易被磁吸）
};
```

**来源**：HFD `liquidation_fuel: [...]`。

### 4.4 `HvnNode` — 真实换手率节点

```ts
type HvnNode = {
  symbol: string;
  tf: string;
  rank: number;                // 1~10，按 volume 降序
  price: number;
  volume: number;
};
```

**来源**：HFD `hvn_nodes: [...]`（正好 Top 10）。

### 4.5 `VolumeProfileBucket` — 筹码分布桶

```ts
type VolumeProfileBucket = {
  symbol: string;
  tf: string;
  price: number;               // 价位
  accum: number;               // 主动买入量
  dist: number;                // 主动卖出量
  total: number;               // 总量
};
```

**来源**：HFD `volume_profile: [...]`。

---

## 五、聚合统计类（Aggregate）

### 5.1 `TimeHeatmapHour` — 24 小时活跃度

```ts
type TimeHeatmapHour = {
  symbol: string;
  tf: string;
  hour: number;                // 0~23（UTC）
  accum: number;
  dist: number;
  total: number;
};
```

**来源**：HFD `time_heatmap: [...]`（固定 24 行）。

### 5.2 `TrendSaturationStat` — 趋势进度（单对象）

```ts
type TrendSaturationStat = {
  symbol: string;
  tf: string;
  type: "Accumulation" | "Distribution";
  start_time: string;          // "2026-04-20 21:00:00"（注意是字符串，不是 ms）
  avg_vol: number;
  current_vol: number;
  progress: number;            // 百分比，可能 > 100
};
```

**来源**：HFD `trend_saturation: {...}`。

⚠️ `start_time` 是 UTC 字符串格式，**入库时务必转成毫秒时间戳**。

---

## 存储建议（SQLite / PostgreSQL）

```
atoms_klines(symbol, tf, ts, open, high, low, close, volume, source)
atoms_cvd(symbol, tf, ts, value)
atoms_imbalance(symbol, tf, ts, value)
atoms_inst_vol(symbol, tf, ts, value)
atoms_vwap(symbol, tf, ts, vwap)
atoms_poc_shift(symbol, tf, ts, poc_price, volume)
atoms_trailing_vwap(symbol, tf, ts, resistance, support)
atoms_power_imbalance(symbol, tf, ts, buy_vol, sell_vol, ratio)
atoms_trend_exhaustion(symbol, tf, ts, exhaustion, type)

atoms_smart_money(symbol, tf, start_time, avg_price, type, status, end_time)
atoms_order_blocks(symbol, tf, start_time, avg_price, volume, type)
atoms_absolute_zones(symbol, tf, start_time, bottom_price, top_price, type)
atoms_micro_poc(symbol, tf, start_time, end_time, poc_price, volume, type)
atoms_trend_purity(symbol, tf, start_time, end_time, avg_price, buy_vol, sell_vol, total_vol, purity, type)

atoms_resonance_events(symbol, tf, ts, price, direction, count, exchanges)
atoms_sweep_events(symbol, tf, ts, price, type, volume)

atoms_heatmap(symbol, tf, start_time, price, intensity, type)
atoms_vacuum(symbol, tf, low, high)
atoms_liquidation_fuel(symbol, tf, bottom, top, fuel)
atoms_hvn_nodes(symbol, tf, rank, price, volume)
atoms_volume_profile(symbol, tf, price, accum, dist, total)

atoms_time_heatmap(symbol, tf, hour, accum, dist, total)
atoms_trend_saturation(symbol, tf, type, start_ts, avg_vol, current_vol, progress)
```

---

## 去重与 Upsert 规则

| 表 | 主键 | 冲突策略 |
|---|---|---|
| 时序类 (`*_ts`) | `(symbol, tf, ts)` | 最后写入覆盖 |
| 段式类 (`*_start_time`) | `(symbol, tf, start_time, type)` | 覆盖所有字段（Ongoing → Completed 时特别需要） |
| 事件类 | `(symbol, tf, ts, price, type)` | 忽略重复 |
| 价位类 (heatmap/fuel/vacuum) | 非稳定主键，**全量覆盖** | 删旧插新 |
| 聚合类 (saturation/time_heatmap) | `(symbol, tf)` | upsert |

---

## 与指标视图层的关系

```
                      HFD 响应
                          ↓
                   Parser（拆原子）
                          ↓
            [ 23 个原子表，1 份 Kline 权威 ]
                          ↓
                   Indicator Views
             （组装成 22 个标准化指标）
                          ↓
                      对外 API
```

**关键原则**：视图层可以组合多个原子，但原子层永远不知道视图的存在。这保证了"数据层改算法不破坏展示层"。
