# cross_exchange_resonance — 主力大单行动（跨所共振）

> **业务定位**：多个交易所同一时间爆发同向大单，代表全球主力联合行动。**真假突破判别的核心信号**。大屏台 1/3。

---

## 请求

```
GET https://dash.hfd.fund/api/pro/pro_data?coin=BTC&indicator=cross_exchange_resonance&tf=30m
```

---

## 响应结构

```json
{
  "klines": [...],
  "cross_exchange_resonance": [
    {
      "count": 2,
      "direction": "sell",
      "exchanges": ["binance", "bybit"],
      "price": 108471.4,
      "timestamp": 1760680800000
    },
    ...
  ]
}
```

### 字段详解

| 字段 | 类型 | 示例 | 说明 |
|---|---|---|---|
| `cross_exchange_resonance[].count` | `integer` | `2` | 同步参与的交易所数量（2~5） |
| `cross_exchange_resonance[].direction` | `string` | `buy` / `sell` | 大单方向 |
| `cross_exchange_resonance[].exchanges` | `Array<string>` | `["binance", "bybit"]` | 参与的交易所列表，可能包括 binance / bybit / okx / gate |
| `cross_exchange_resonance[].price` | `number` | `108471.4` | 共振发生时的价格 |
| `cross_exchange_resonance[].timestamp` | `integer` (ms) | `1760680800000` | 共振时间戳 |

### 典型数据量

- 30m 周期：约 **192 条** 共振事件

### count 权重建议

| count | 权重 | 大屏表现 |
|---|---|---|
| 2 | 1.0 | 小圆点 |
| 3 | 2.5 | 中圆点 |
| 4 | 5.0 | 大圆点 |
| 5 | 10.0 | 特大圆点 + 声音告警 |

> 信号权重随参与交易所数量**指数级放大**。

---

## 更新节拍

- **建议拉取间隔**：K 线收盘 +5s
- 原因：事件性信号，越及时越值钱

---

## 已知异常

| 现象 | 处理建议 |
|---|---|
| `count=2` 的事件很多（噪音） | 大屏只高亮 `count >= 3` 的圆点 |
| 某些事件 timestamp 不对齐 K 线开盘时间 | 允许 timestamp 在 K 线区间内任意位置 |

---

## 映射到原子

→ `ResonanceEvent[]`（见 [../ATOMS.md](../ATOMS.md#31-resonanceevent--跨所共振大单)）

---

## 大屏使用

### 台 1 主力行为监控
```
近 30min 内 count>=3 的 buy 事件 > 3 次 → "全球联合进场"（看多）
近 30min 内 count>=3 的 sell 事件 > 3 次 → "全球联合出货"（看空）
```

### 台 3 交易决策辅助
```
突破关键位 + 同时段有 count>=3 同向共振 → "真突破"（强烈追单）
突破关键位 + 无共振 → "假突破概率高"（不追）
```

---

## Schema 与 Sample

- [`../schemas/cross_exchange_resonance.schema.json`](../schemas/cross_exchange_resonance.schema.json)
- [`../samples/cross_exchange_resonance.sample.json`](../samples/cross_exchange_resonance.sample.json)
