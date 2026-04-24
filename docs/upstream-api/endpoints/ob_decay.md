# ob_decay — 订单墙衰减

> **业务定位**：已识别 OrderBlock 的"剩余血量"（每次被测试后会衰减）。与 `trend_price` 配合使用。台 2/3。

---

## 请求

```
GET https://dash.hfd.fund/api/pro/pro_data?coin=BTC&indicator=ob_decay&tf=30m
```

---

## ⚠️ 接口响应与 trend_price 完全相同

本接口返回的 `order_blocks` 字段与 `trend_price` **结构一致**（`avg_price` + `volume` + `start_time` + `type`）。

**含义**：HFD 没提供独立的 "decay 百分比"，需要前端/后端基于同一组 OB 自己计算衰减。

**衰减算法（参考）**：
```
对每个 OB：
  initial_volume = order_blocks[i].volume
  current_volume = initial_volume × exp(-λ × (now - start_time) / time_unit)
  decay_pct = 1 - current_volume / initial_volume
  每次价格穿过 avg_price ±0.2%，current_volume × 0.7（消耗）
```

λ 和阈值需要用历史数据拟合，官方没有公开算法。

---

## 响应结构

与 `trend_price` 相同：

```json
{
  "klines": [...],
  "order_blocks": [
    {
      "avg_price": 110450.5,
      "volume": 3890.2,
      "start_time": 1760425200000,
      "type": "Accumulation"
    }
  ]
}
```

---

## 更新节拍

- **建议：不独立拉取**
- 数据完全包含在 `trend_price` 响应里（MD5 一致）
- 采集层拉 `trend_price`，衰减计算在视图层做

---

## 映射到原子

不直接映射（复用 `OrderBlock[]`）。

派生产出（indicator-views 层）：
```ts
type ObDecayView = {
  symbol: string;
  tf: string;
  ob_start_time: number;
  avg_price: number;
  type: "Accumulation" | "Distribution";
  decay_pct: number;       // 0 = 完整, 1 = 已耗尽
  test_count: number;      // 被测试次数
};
```

---

## 大屏使用

### 台 2 市场结构地图
- 每条 OB 的透明度 = 1 - decay_pct
- decay_pct > 0.7 的 OB 标注"濒危"（即将击穿）

### 台 3 交易决策辅助
```
price 逼近目标 OB + decay_pct > 0.7 → "墙体衰减击穿概率升高"
不建议在这种 OB 前反向入场
```

---

## Schema 与 Sample

- [`../schemas/ob_decay.schema.json`](../schemas/ob_decay.schema.json)
- [`../samples/ob_decay.sample.json`](../samples/ob_decay.sample.json)
