# trend_exhaustion — 能量耗竭

> **业务定位**：标记当前 K 线的"能量耗竭"程度（趋势末段信号）。台 1/3。

---

## 请求

```
GET https://dash.hfd.fund/api/pro/pro_data?coin=BTC&indicator=trend_exhaustion&tf=30m
```

---

## 响应结构

```json
{
  "klines": [...],
  "trend_exhaustion": [
    {
      "timestamp": 1760680800000,
      "exhaustion": 8.5,
      "type": "Distribution"
    },
    {
      "timestamp": 1760682600000,
      "exhaustion": 0,
      "type": "Accumulation"
    },
    ...
  ]
}
```

### 字段详解

| 字段 | 类型 | 示例 | 说明 |
|---|---|---|---|
| `trend_exhaustion[].timestamp` | `number` (ms) | `1760680800000` | K 线时间 |
| `trend_exhaustion[].exhaustion` | `number` | `8.5` | **耗竭指数**，0 = 无信号 |
| `trend_exhaustion[].type` | `string` | `Accumulation` / `Distribution` | 吸筹耗竭 / 派发耗竭 |

### 典型数据量

- 30m 周期：约 **4900 个点**（每根 K 线一个）
- **大多数 `exhaustion = 0`**（只有关键转折点才有值）

### 阈值建议

| exhaustion | 含义 | 大屏表现 |
|---|---|---|
| 0 | 无耗竭 | 不显示 |
| 1~5 | 微弱疲软 | 小柱 |
| 5~10 | 明显耗竭 | 大柱 + 黄色 |
| > 10 | 严重耗竭 | 大柱 + 红色告警 |

---

## 更新节拍

- **建议拉取间隔**：K 线收盘 +3s

---

## 已知异常

| 现象 | 处理建议 |
|---|---|
| 大多数 `exhaustion=0` | 只高亮 > 阈值的柱子 |
| 连续多根 `exhaustion > 5` 同向 | 反转概率极高 |

---

## 映射到原子

→ `TrendExhaustionPoint[]`（见 [../ATOMS.md](../ATOMS.md#19-trendexhaustionpoint--能量耗竭)）

---

## 大屏使用

### 台 1 主力行为监控
```
近 3 根 exhaustion > 5 (Distribution) → "派发方能量耗竭"（底部反转预警）
近 3 根 exhaustion > 5 (Accumulation) → "吸筹方能量耗竭"（顶部反转预警）
```

### 台 3 交易决策辅助
```
持多仓 + 上方出现 Accumulation 耗竭 → 提示减仓
持空仓 + 下方出现 Distribution 耗竭 → 提示减仓
```

---

## Schema 与 Sample

- [`../schemas/trend_exhaustion.schema.json`](../schemas/trend_exhaustion.schema.json)
- [`../samples/trend_exhaustion.sample.json`](../samples/trend_exhaustion.sample.json)
