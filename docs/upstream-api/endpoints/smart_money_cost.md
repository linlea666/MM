# smart_money_cost — 趋势成本带

> **业务定位**：主力当前波段的平均持仓成本价（绿带/红带的核心）。大屏台 1/2/3 的核心输入。

---

## 请求

```
GET https://dash.hfd.fund/api/pro/pro_data?coin=BTC&indicator=smart_money_cost&tf=30m
```

| 参数 | 示例 | 说明 |
|---|---|---|
| `coin` | `BTC` | 币种 |
| `indicator` | `smart_money_cost` | 固定值 |
| `tf` | `30m` / `1h` / `4h` / `1d` | 周期 |

---

## 响应结构

```json
{
  "klines": [[ts, o, c, l, h, vol], ...],
  "smart_money_cost": [
    {
      "avg_price": 79911.67,
      "start_time": 1760425200000,
      "end_time": 1760709600000,
      "status": "Completed",
      "type": "Accumulation"
    },
    ...
  ]
}
```

### 字段详解

| 字段 | 类型 | 示例 | 说明 |
|---|---|---|---|
| `klines` | `Array<[ts, o, c, l, h, vol]>` | 4923 条 | **丢弃**（用 Binance 的） |
| `smart_money_cost[].avg_price` | `number` | `79911.67` | 该段主力平均成本价（绘制成本带的中心线） |
| `smart_money_cost[].start_time` | `number` (ms) | `1760425200000` | 该段起始 K 线时间 |
| `smart_money_cost[].end_time` | `number` (ms) | `1760709600000` | 该段结束时间；`Ongoing` 时跟随最新 K 线漂移 |
| `smart_money_cost[].status` | `string` | `Completed` / `Ongoing` | ⭐ Ongoing = 正在发生，最值钱的信号 |
| `smart_money_cost[].type` | `string` | `Accumulation` / `Distribution` | 吸筹（绿带）/ 派发（红带） |

### 典型数据量

- 30m 周期：约 **76 段** / 4923 根 K 线（≈ 每 65 根 K 线产生 1 段）
- 最后一段通常是 `status=Ongoing`，作为当前市场状态判断

---

## 更新节拍

- **建议拉取间隔**：30 min（K 线收盘 +10s）
- 原因：段结构变化较慢，过于频繁的请求无意义
- `Ongoing` 段的 `avg_price` 会随 K 线收盘而小幅更新，这是重点追踪对象

---

## 已知异常

| 现象 | 处理建议 |
|---|---|
| 最后一段 `status=Ongoing` 且 `end_time` 持续漂移 | 入库按 `(symbol, tf, start_time, type)` upsert |
| 新段出现时，前一段立刻变成 `Completed` | 两段可能在同一次响应里同时变化 |
| 极端横盘时可能长时间没有新段 | 正常，不是接口异常 |

---

## 映射到原子

→ `SmartMoneySegment`（见 [../ATOMS.md](../ATOMS.md#21-smartmoneysegment--主力成本段)）

```ts
function parse(resp): SmartMoneySegment[] {
  return resp.smart_money_cost.map(s => ({
    symbol, tf,
    start_time: s.start_time,
    end_time: s.end_time,
    avg_price: s.avg_price,
    type: s.type,
    status: s.status,
  }));
}
```

---

## 与其它指标的关系

| 关系指标 | 共享数据 | 说明 |
|---|---|---|
| `trend_price` | 无 | 是 smart_money_cost 的"右侧投影"视图，但**后端数据结构不同**（trend_price 返回 `order_blocks[]` 带 volume） |
| `trend_purity` | 同时间段 | 提供"每段的纯度百分比"，用于给成本带上色 |
| `micro_poc` | 同时间段 | 提供段内的 POC 价格（更精细的成本点） |

**组合建议**：大屏画成本带时，`smart_money_cost` 提供中心线，`trend_purity` 提供"墙厚度/可信度"，`ob_decay` 提供"剩余血量"。

---

## 大屏使用（映射到三大台）

### 台 1 主力行为监控
```
Ongoing + Accumulation → "吸筹"
Ongoing + Distribution → "派发"
price 靠近 avg_price(Accum) → "护盘明显"
price 靠近 avg_price(Dist) → "压盘明显"
```

### 台 2 市场结构地图
```
每段的 avg_price 投影到图表右侧 = 撑压线
价格带 = [avg_price × 0.997, avg_price × 1.003]（基于经验 ±0.3%）
```

### 台 3 交易决策辅助
```
price 回踩 Accum 段的 avg_price ±0.3% → 回踩做多入场
price 反弹 Dist 段的 avg_price ±0.3% → 反弹做空入场
止损：avg_price × 0.995（破带止损）
```

---

## Schema 与 Sample

- JSON Schema：[`../schemas/smart_money_cost.schema.json`](../schemas/smart_money_cost.schema.json)
- 真实响应样本：[`../samples/smart_money_cost.sample.json`](../samples/smart_money_cost.sample.json)
