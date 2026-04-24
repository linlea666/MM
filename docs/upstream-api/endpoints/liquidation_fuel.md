# liquidation_fuel — 燃料库清算地图

> **业务定位**：更精细的清算单带（带"燃料浓度"）。用于寻找止盈目标。台 2/3。

---

## 请求

```
GET https://dash.hfd.fund/api/pro/pro_data?coin=BTC&indicator=liquidation_fuel&tf=30m
```

---

## 响应结构

```json
{
  "klines": [...],
  "liquidation_fuel": [
    {
      "bottom": 108400.0,
      "top": 108800.0,
      "fuel": 3.85
    },
    ...
  ]
}
```

### 字段详解

| 字段 | 类型 | 示例 | 说明 |
|---|---|---|---|
| `liquidation_fuel[].bottom` | `number` | `108400.0` | 带底价 |
| `liquidation_fuel[].top` | `number` | `108800.0` | 带顶价 |
| `liquidation_fuel[].fuel` | `number` | `3.85` | 燃料浓度（越高磁吸越强） |

### 典型数据量

- 30m 周期：约 **15~40 条带**

---

## 更新节拍

- **建议拉取间隔**：1h

---

## 已知异常

| 现象 | 处理建议 |
|---|---|
| 燃料库与 `liq_heatmap.heatmap_data` 位置接近但不完全重合 | 两者是不同维度（燃料 vs 清算单），可同时显示 |
| 低 fuel（< 1）的带 | 可过滤，不画 |

---

## 与 liq_heatmap 的关系

| 指标 | 数据形态 | 用途 |
|---|---|---|
| `liq_heatmap.heatmap_data` | 单价位点（intensity） | 整体清算分布 |
| `liquidation_fuel` | 价格带（bottom/top/fuel） | 精细磁吸带 |

**建议**：两者同时画，liq_heatmap 是"远景磁场"，liquidation_fuel 是"近景燃料库"。

---

## 映射到原子

→ `LiquidationFuelBand[]`（见 [../ATOMS.md](../ATOMS.md#43-liquidationfuelband--燃料库清算带)）

---

## 大屏使用

### 台 2 市场结构地图
- 画带状区域，染色强度 ∝ fuel
- 与 liq_heatmap 叠加显示

### 台 3 交易决策辅助
```
止盈 T1 = 最近的同向燃料库中心
fuel > 3 的带 = 高概率触发点
```

---

## Schema 与 Sample

- [`../schemas/liquidation_fuel.schema.json`](../schemas/liquidation_fuel.schema.json)
- [`../samples/liquidation_fuel.sample.json`](../samples/liquidation_fuel.sample.json)
