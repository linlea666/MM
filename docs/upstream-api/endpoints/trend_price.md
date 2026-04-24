# trend_price — 趋势撑压

> **业务定位**：把历史 OrderBlock 投影到右侧作为撑压水平线。大屏台 2 的核心。

---

## 请求

```
GET https://dash.hfd.fund/api/pro/pro_data?coin=BTC&indicator=trend_price&tf=30m
```

---

## 响应结构

```json
{
  "klines": [...],
  "order_blocks": [
    {
      "avg_price": 110450.5,
      "volume": 3890.2,
      "start_time": 1760425200000,
      "type": "Accumulation"
    },
    ...
  ]
}
```

### 字段详解（OrderBlocks 家族 — avg_price 形态）

| 字段 | 类型 | 示例 | 说明 |
|---|---|---|---|
| `order_blocks[].avg_price` | `number` | `110450.5` | OB 的核心价位（画水平线用） |
| `order_blocks[].volume` | `number` | `3890.2` | OB 累积成交量（决定线的粗细） |
| `order_blocks[].start_time` | `number` (ms) | `1760425200000` | OB 形成时间 |
| `order_blocks[].type` | `string` | `Accumulation` / `Distribution` | 撑（多）/ 压（空） |

⚠️ **与 absolute_zones 的 order_blocks 字段结构不同**（那边是 `bottom_price`+`top_price` 矩形）。

### 典型数据量

- 30m 周期：约 **260 条**

---

## 更新节拍

- **建议拉取间隔**：30 min
- 原因：短周期 OB 频繁更新

### 数据复用
- `ob_decay` 返回的 `order_blocks` 与本接口**完全相同**
- **只拉 trend_price 即可覆盖 ob_decay**（见 README § 4.3）

---

## 已知异常

| 现象 | 处理建议 |
|---|---|
| 260 条 OB 画满屏幕 | 只画距离现价 ±5% 内的 OB |
| 老旧 OB 失效 | 配合 `ob_decay` 的"剩余血量"过滤 |

---

## 映射到原子

→ `OrderBlock[]`（见 [../ATOMS.md](../ATOMS.md#22-orderblock--订单块avg_price-形态)）

---

## 大屏使用

### 台 2 市场结构地图
- 每个 OB 画一条水平线到图表右侧
- 线粗 ∝ `volume`
- 颜色：Accum = 绿、Dist = 红
- 配合 `trend_purity` 上色（纯度高 → 饱和色）
- 配合 `ob_decay` 调透明度（衰减高 → 透明）

### 台 3 交易决策辅助
- 现价之上第一条 Dist OB → 做空入场区
- 现价之下第一条 Accum OB → 做多入场区
- 止损：OB avg_price ± 0.5%

---

## Schema 与 Sample

- [`../schemas/trend_price.schema.json`](../schemas/trend_price.schema.json)
- [`../samples/trend_price.sample.json`](../samples/trend_price.sample.json)
