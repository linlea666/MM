# liq_heatmap — 清算痛点地图

> **业务定位**：全价格轴上的清算单聚集带，用于寻找"流动性磁吸点"（止盈目标位）。大屏台 2/3 的核心输入。

---

## 请求

```
GET https://dash.hfd.fund/api/pro/pro_data?coin=BTC&indicator=liq_heatmap&tf=30m
```

---

## 响应结构

```json
{
  "klines": [...],
  "heatmap_data": [
    {
      "intensity": 0.47,
      "price": 105393.36,
      "start_time": 1760680800000,
      "type": "Accumulation"
    },
    ...
  ],
  "order_blocks": [],
  "volume_profile": []
}
```

### 字段详解

| 字段 | 类型 | 示例 | 说明 |
|---|---|---|---|
| `heatmap_data[].intensity` | `number` | `0.47` | 清算单密度，0~1，越大越值钱 |
| `heatmap_data[].price` | `number` | `105393.36` | 清算带中心价位 |
| `heatmap_data[].start_time` | `number` (ms) | `1760680800000` | 带形成时间 |
| `heatmap_data[].type` | `string` | `Accumulation` / `Distribution` | 做多清算（下方红色）/ 做空清算（上方绿色） |
| `order_blocks` | `array` | `[]` | 永远为空，忽略 |
| `volume_profile` | `array` | `[]` | 永远为空，忽略 |

### 典型数据量

- 30m 周期：约 **30 条** heatmap_data

---

## 更新节拍

- **建议拉取间隔**：1h
- 原因：清算带在短时间内变化不大，但突破后会重新计算

---

## 已知异常

| 现象 | 处理建议 |
|---|---|
| `order_blocks` / `volume_profile` 永远为空 | 忽略 |
| 价格跌穿某条带后该带立刻消失 | 采集器每次全量覆盖旧数据，不做增量合并 |

---

## 映射到原子

→ `HeatmapBand[]`（见 [../ATOMS.md](../ATOMS.md#41-heatmapband--清算痛点带)）

---

## 大屏使用

### 台 2 市场结构地图
- 上方所有 `Distribution` 带 → **空头清算目标**（做多止盈）
- 下方所有 `Accumulation` 带 → **多头清算目标**（做空止盈）
- `intensity × 1/距离` 排序 → 生成"目标位排行榜 Top 3"

### 台 3 交易决策辅助
- 止盈 T1 = 最近的同向 heatmap 带
- 止盈 T2 = 次近的同向带
- 如果上下两侧 intensity 比 > 1.5，触发 "上方空头清算区更吸引" 结论

---

## Schema 与 Sample

- [`../schemas/liq_heatmap.schema.json`](../schemas/liq_heatmap.schema.json)
- [`../samples/liq_heatmap.sample.json`](../samples/liq_heatmap.sample.json)
