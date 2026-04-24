# micro_poc — 微观成本线

> **业务定位**：在 smart_money_cost 的大段里再切更小的段，给出更精细的成本射线。台 1/2/3。

---

## 请求

```
GET https://dash.hfd.fund/api/pro/pro_data?coin=BTC&indicator=micro_poc&tf=30m
```

---

## 响应结构

```json
{
  "klines": [...],
  "cvd_series": [...],
  "imbalance_series": [...],
  "inst_vol_series": [...],
  "vwap_series": [...],
  "micro_poc": [
    {
      "start_time": 1760680800000,
      "end_time": 1760712000000,
      "poc_price": 110520.5,
      "volume": 1532.8,
      "type": "Accumulation"
    },
    ...
  ],
  "poc_shift": [...],
  "liquidity_sweep": [...],
  "order_blocks": [],
  "volume_profile": []
}
```

### 字段详解（micro_poc 专属）

| 字段 | 类型 | 示例 | 说明 |
|---|---|---|---|
| `micro_poc[].start_time` | `number` (ms) | `1760680800000` | 段起始 |
| `micro_poc[].end_time` | `number \| null` | `1760712000000` / `null` | 段结束；**最后一段为 null**（进行中） |
| `micro_poc[].poc_price` | `number` | `110520.5` | 该段 POC 价格 |
| `micro_poc[].volume` | `number` | `1532.8` | 段累计成交量 |
| `micro_poc[].type` | `string` | `Accumulation` / `Distribution` | 多头微段 / 空头微段 |

### 顺带获得的其它字段
`cvd_series` / `imbalance_series` / `inst_vol_series` / `vwap_series` / `poc_shift` / `liquidity_sweep` — 全部同 Series 家族（复用）。

### 典型数据量

- 30m 周期：约 **150~300 段** micro_poc（比 smart_money_cost 细 3~4 倍）

---

## 更新节拍

- **建议拉取间隔**：K 线收盘 +5s
- 原因：最后一段的 `end_time=null`，是实时追踪的关键

### 数据复用
- 拉 `micro_poc` 同时顺带获得 `poc_shift` / `liquidity_sweep` 的全部数据
- **但实测 poc_shift 接口响应也包含 micro_poc，所以两者只需拉一个即可**

---

## 已知异常

| 现象 | 处理建议 |
|---|---|
| 最后一段 `end_time=null` | 入库时 `COALESCE(end_time, latest_kline_ts)` |
| 段切换时上一段的 end_time 才确定 | 采集层按 `(symbol, tf, start_time)` upsert，旧段会被更新 |

---

## 映射到原子

→ `MicroPocSegment[]`（见 [../ATOMS.md](../ATOMS.md#24-micropocsegment--微观成本段)）

---

## 大屏使用

### 台 1 主力行为监控
- 最后一段 type → 短期主力方向
- 多段连续同向 → 主力高度一致（强信号）

### 台 2 市场结构地图
- 每段投影为一条小水平线（比 trend_price 的 OB 更细）
- 配合 `poc_shift` 一起画"POC 重心轨迹"

### 台 3 交易决策辅助
- 现价靠近最近 micro_poc.poc_price → 短线回踩入场候选

---

## Schema 与 Sample

- [`../schemas/micro_poc.schema.json`](../schemas/micro_poc.schema.json)
- [`../samples/micro_poc.sample.json`](../samples/micro_poc.sample.json)
