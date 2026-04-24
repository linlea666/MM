# trailing_vwap — 趋势动态防线

> **业务定位**：随趋势移动的 VWAP 防线（绿梯/红梯），可直接作为移动止损。台 2/3。

---

## 请求

```
GET https://dash.hfd.fund/api/pro/pro_data?coin=BTC&indicator=trailing_vwap&tf=30m
```

---

## 响应结构

```json
{
  "klines": [...],
  "trailing_vwap": [
    {
      "timestamp": 1760680800000,
      "resistance": 110850.5,
      "support": 109200.3
    },
    {
      "timestamp": 1760425200000,
      "resistance": null,
      "support": null
    },
    ...
  ]
}
```

### 字段详解

| 字段 | 类型 | 示例 | 说明 |
|---|---|---|---|
| `trailing_vwap[].timestamp` | `number` (ms) | `1760680800000` | K 线时间 |
| `trailing_vwap[].resistance` | `number \| null` | `110850.5` | **红梯**（上方阻力） |
| `trailing_vwap[].support` | `number \| null` | `109200.3` | **绿梯**（下方支撑） |

### 典型数据量

- 30m 周期：约 **4900 个点**（每根 K 线 1 个）

### null 值处理

- 历史早期 `resistance` / `support` 可能为 `null`（需要累计足够样本）
- 大屏绘制时**跳过** null 点

---

## 更新节拍

- **建议拉取间隔**：K 线收盘 +3s
- 原因：每根新 K 线都会追加一个新点

---

## 已知异常

| 现象 | 处理建议 |
|---|---|
| 早期大量 null | 过滤后再绘图 |
| resistance / support 几乎不动 | 趋势强劲时梯子"卡住"，正常 |
| 梯子突然跳跃 | 趋势反转后梯子重置 |

---

## 映射到原子

→ `TrailingVwapPoint[]`（见 [../ATOMS.md](../ATOMS.md#17-trailingvwappoint--动态防线绿红梯)）

---

## 大屏使用

### 台 2 市场结构地图
- 绿梯 / 红梯 作为两条随时间漂移的曲线
- 价格在红梯上方 → 多头优势
- 价格在绿梯下方 → 空头优势
- 价格在梯之间 → 震荡区

### 台 3 交易决策辅助
```
多单持仓：止损 = 绿梯（动态移动）
空单持仓：止损 = 红梯
价格击穿梯 → 趋势反转，平仓信号
```

---

## Schema 与 Sample

- [`../schemas/trailing_vwap.schema.json`](../schemas/trailing_vwap.schema.json)
- [`../samples/trailing_vwap.sample.json`](../samples/trailing_vwap.sample.json)
