# absolute_zones — 密集博弈

> **业务定位**：多空双方机构白刃战的价格矩形区，用于识别铁底/铁顶。大屏台 2/3。

---

## 请求

```
GET https://dash.hfd.fund/api/pro/pro_data?coin=BTC&indicator=absolute_zones&tf=30m
```

---

## 响应结构

```json
{
  "klines": [...],
  "order_blocks": [
    {
      "bottom_price": 110693.4,
      "top_price": 111133.9,
      "start_time": 1760547600000,
      "type": "Accumulation"
    }
  ],
  "volume_profile": []
}
```

### 字段详解 ⚠️ 与 trend_price/ob_decay 的 order_blocks 结构不同

| 字段 | 类型 | 示例 | 说明 |
|---|---|---|---|
| `order_blocks[].bottom_price` | `number` | `110693.4` | 矩形下边缘 |
| `order_blocks[].top_price` | `number` | `111133.9` | 矩形上边缘 |
| `order_blocks[].start_time` | `number` (ms) | `1760547600000` | 矩形出现时间 |
| `order_blocks[].type` | `string` | `Accumulation` / `Distribution` | 多头博弈带（绿）/ 空头博弈带（红） |
| `volume_profile` | `array` | `[]` | 永远为空，忽略 |

⚠️ **与其它 OrderBlock 不同**：这里是 `bottom_price` + `top_price`（矩形带），不是 `avg_price` + `volume`。所以要映射到不同的原子。

### 典型数据量

- 30m 周期：约 **411 条**（比普通 OrderBlock 多得多，颗粒度更细）

---

## 更新节拍

- **建议拉取间隔**：30 min
- 原因：密集博弈在短期交易中很有时效性，需要较高频率

---

## 已知异常

| 现象 | 处理建议 |
|---|---|
| 411 个矩形太多，密集到画图会糊 | 前端绘制时按 `intensity = top - bottom` 过滤，只画 Top 50 |

---

## 映射到原子

→ `AbsoluteZone[]`（见 [../ATOMS.md](../ATOMS.md#23-absolutezone--密集博弈带矩形)）

---

## 大屏使用

### 台 2 市场结构地图
- 上方密集红色矩形 → "空头铁顶"
- 下方密集绿色矩形 → "多头铁底"
- 两个矩形之间的空白区 → "单边加速候选区"

### 台 3 交易决策辅助
- 当前价进入 Accumulation 矩形 → 左侧抄底候选
- 当前价突破 Distribution 矩形顶部 → 追多（若有 cross_exchange_resonance 确认）

---

## Schema 与 Sample

- [`../schemas/absolute_zones.schema.json`](../schemas/absolute_zones.schema.json)
- [`../samples/absolute_zones.sample.json`](../samples/absolute_zones.sample.json)
