# time_heatmap — 资金时间热力图

> **业务定位**：24 小时聚合分布，找出主力最活跃的时段。台 3 的"信号时段过滤器"。

---

## 请求

```
GET https://dash.hfd.fund/api/pro/pro_data?coin=BTC&indicator=time_heatmap&tf=30m
```

---

## 响应结构

```json
{
  "klines": [...],
  "time_heatmap": [
    {"hour": 0,  "accum": 12580.5, "dist": 9820.3, "total": 22400.8},
    {"hour": 1,  "accum": 10230.8, "dist": 11420.9, "total": 21651.7},
    ...
    {"hour": 23, "accum": 18950.1, "dist": 17330.5, "total": 36280.6}
  ]
}
```

### 字段详解

| 字段 | 类型 | 说明 |
|---|---|---|
| `time_heatmap[].hour` | `integer` | **UTC** 小时 0~23 |
| `time_heatmap[].accum` | `number` | 该小时聚合的主动买入量 |
| `time_heatmap[].dist` | `number` | 该小时聚合的主动卖出量 |
| `time_heatmap[].total` | `number` | accum + dist |

### 固定数据量

- **24 条**（每小时一条）

### 时区

- HFD 返回的 `hour` 是 **UTC**
- 北京时间 = UTC + 8，例如 UTC 12:00 = BJT 20:00

---

## 更新节拍

- **建议拉取间隔**：4h
- 原因：全局聚合指标，变化极缓

---

## 已知异常

| 现象 | 处理建议 |
|---|---|
| 某些小时 total 非常小 | 正常（低活跃时段） |
| 统计范围未知 | 估计是最近 N 天滚动窗口，HFD 未明确 |

---

## 映射到原子

→ `TimeHeatmapHour[]`（见 [../ATOMS.md](../ATOMS.md#51-timeheatmaphour--24-小时活跃度)）

---

## 大屏使用

### 台 3 交易决策辅助（核心用途）

**活跃度系数**：
```ts
const currentHour = new Date().getUTCHours();
const currentTotal = time_heatmap[currentHour].total;
const avgTotal = mean(time_heatmap.map(h => h.total));
const activityCoef = currentTotal / avgTotal;
```

**应用**：
- `activityCoef > 1.2` → 当前是活跃时段，交易信号可信度 × 1.2
- `activityCoef < 0.5` → 非活跃时段，直接触发 "当前不值得交易"

### 台 2 结构地图（辅助）
- 画成 24 格圆形热力图（像钟表）
- 高亮当前小时 + Top 3 最活跃小时

---

## Schema 与 Sample

- [`../schemas/time_heatmap.schema.json`](../schemas/time_heatmap.schema.json)
- [`../samples/time_heatmap.sample.json`](../samples/time_heatmap.sample.json)
