# trend_purity — 趋势筹码纯度

> **业务定位**：每段的"纯度百分比"（主动买卖占比），给成本带/撑压线上色。台 1/2。

---

## 请求

```
GET https://dash.hfd.fund/api/pro/pro_data?coin=BTC&indicator=trend_purity&tf=30m
```

---

## 响应结构

```json
{
  "klines": [...],
  "trend_purity": [
    {
      "start_time": 1760425200000,
      "end_time": 1760709600000,
      "avg_price": 110450.5,
      "buy_vol": 2850.3,
      "sell_vol": 1039.9,
      "total_vol": 3890.2,
      "purity": 73.27,
      "type": "Accumulation"
    },
    ...
  ]
}
```

### 字段详解

| 字段 | 类型 | 示例 | 说明 |
|---|---|---|---|
| `trend_purity[].start_time` | `number` (ms) | `1760425200000` | 段起始 |
| `trend_purity[].end_time` | `number \| null` | `1760709600000` / `null` | 最后一段为 null |
| `trend_purity[].avg_price` | `number` | `110450.5` | 段均价 |
| `trend_purity[].buy_vol` | `number` | `2850.3` | 主动买入量 |
| `trend_purity[].sell_vol` | `number` | `1039.9` | 主动卖出量 |
| `trend_purity[].total_vol` | `number` | `3890.2` | 总量 |
| `trend_purity[].purity` | `number` | `73.27` | **纯度百分比 0~100**（由 buy_vol / total_vol 或 sell_vol / total_vol 计算） |
| `trend_purity[].type` | `string` | `Accumulation` / `Distribution` | 吸筹段 / 派发段 |

### 典型数据量

- 30m 周期：约 **76 段**（与 smart_money_cost 段数基本一致）

---

## 更新节拍

- **建议拉取间隔**：30 min
- 原因：段级指标，变化缓慢

---

## 已知异常

| 现象 | 处理建议 |
|---|---|
| `purity` 极低（< 40）| 该段其实是拉锯战，无明显方向 |
| 最后一段 `end_time=null` | 进行中，`purity` 会随新 K 线变化 |

### 纯度阈值建议

| purity | 含义 | 大屏表现 |
|---|---|---|
| ≥ 80 | 主力意志强烈 | 成本带饱和色 + 加粗 |
| 60~80 | 趋势清晰 | 成本带正常色 |
| 40~60 | 拉锯震荡 | 虚线 |
| < 40 | 无明显方向 | 灰色或不画 |

---

## 映射到原子

→ `TrendPuritySegment[]`（见 [../ATOMS.md](../ATOMS.md#25-trendpuritysegment--筹码纯度段)）

---

## 大屏使用

### 台 1 主力行为监控
- Ongoing 段 purity ≥ 80 → 加入 "主力意志强烈" 标签
- 连续 3 段 purity < 50 → 加入 "市场犹豫" 标签

### 台 2 市场结构地图
- 根据 purity 给每条 OB / smart_money_cost 段的线上色
- 颜色深浅 = 可信度

---

## Schema 与 Sample

- [`../schemas/trend_purity.schema.json`](../schemas/trend_purity.schema.json)
- [`../samples/trend_purity.sample.json`](../samples/trend_purity.sample.json)
