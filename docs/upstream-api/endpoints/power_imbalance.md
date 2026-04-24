# power_imbalance — 多空力量悬殊比

> **业务定位**：每根 K 线的 buy_vol / sell_vol 碾压比。用于识别"逼空/逼多"行情。台 1/3。

---

## 请求

```
GET https://dash.hfd.fund/api/pro/pro_data?coin=BTC&indicator=power_imbalance&tf=30m
```

---

## 响应结构

```json
{
  "klines": [...],
  "power_imbalance": [
    {
      "timestamp": 1760680800000,
      "buy_vol": 3520.5,
      "sell_vol": 820.3,
      "ratio": 4.29
    },
    {
      "timestamp": 1760682600000,
      "buy_vol": 0,
      "sell_vol": 0,
      "ratio": 0
    },
    ...
  ]
}
```

### 字段详解

| 字段 | 类型 | 示例 | 说明 |
|---|---|---|---|
| `power_imbalance[].timestamp` | `number` (ms) | `1760680800000` | K 线时间 |
| `power_imbalance[].buy_vol` | `number` | `3520.5` | 主动买入量 |
| `power_imbalance[].sell_vol` | `number` | `820.3` | 主动卖出量 |
| `power_imbalance[].ratio` | `number` | `4.29` | **碾压比**；大量 K 线 = 0（静默期） |

### 典型数据量

- 30m 周期：约 **4900 个点**（每根 K 线一个）
- 但 **大多数为 0**（非活跃时段）

### ratio 阈值建议

| ratio | 含义 | 大屏表现 |
|---|---|---|
| 0 | 静默期 | 不显示 |
| 1~2 | 轻微倾向 | 忽略 |
| 2~3 | 明显压制 | 小柱 |
| 3~5 | 碾压 | 大柱 + 黄色 |
| > 5 | 逼空 / 逼多 | 大柱 + 红色告警 |

---

## 更新节拍

- **建议拉取间隔**：K 线收盘 +3s
- 原因：每根新 K 线必更新

---

## 已知异常

| 现象 | 处理建议 |
|---|---|
| 大量 `ratio=0` | 正常，过滤后再显示 |
| `sell_vol=0` 且 `buy_vol>0` | ratio 会变成 infinity，前端按 999 截断 |

---

## 映射到原子

→ `PowerImbalancePoint[]`（见 [../ATOMS.md](../ATOMS.md#18-powerimbalancepoint--多空力量悬殊)）

---

## 大屏使用

### 台 1 主力行为监控
```
连续 3 根 ratio > 3 (buy) → "逼空行情"
连续 3 根 ratio > 3 (sell) → "逼多行情"（下跌碾压）
```

### 台 3 交易决策辅助
```
突破关键位 + 同时 ratio > 3 (同向) → 真突破确认
突破关键位 + ratio < 2 → 突破未获力量确认（谨慎）
```

---

## Schema 与 Sample

- [`../schemas/power_imbalance.schema.json`](../schemas/power_imbalance.schema.json)
- [`../samples/power_imbalance.sample.json`](../samples/power_imbalance.sample.json)
