# liquidity_sweep — 流动性猎杀

> **业务定位**：主力扫损/扫单事件（价格刺穿后立刻回收的"血滴"）。台 1/3 的核心反转信号。

---

## 请求

```
GET https://dash.hfd.fund/api/pro/pro_data?coin=BTC&indicator=liquidity_sweep&tf=30m
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
  "liquidity_sweep": [
    {
      "timestamp": 1760680800000,
      "price": 108400.5,
      "type": "bullish_sweep",
      "volume": 320.8
    },
    ...
  ],
  "micro_poc": [...],
  "poc_shift": [...],
  "order_blocks": [],
  "volume_profile": []
}
```

### 字段详解

| 字段 | 类型 | 示例 | 说明 |
|---|---|---|---|
| `liquidity_sweep[].timestamp` | `number` (ms) | `1760680800000` | 猎杀发生时间 |
| `liquidity_sweep[].price` | `number` | `108400.5` | 猎杀刺穿的价位 |
| `liquidity_sweep[].type` | `string` | `bullish_sweep` / `bearish_sweep` | 向下扫损（看涨反转）/ 向上扫损（看跌反转） |
| `liquidity_sweep[].volume` | `number` | `320.8` | 扫损成交量 |

### 典型数据量

- 30m 周期：约 **50~150 个事件**

### ⚠️ 命名陷阱

| type | 含义 | 后续走势 |
|---|---|---|
| `bullish_sweep` | 向下刺破低点扫多头止损 | **可能看涨**（反转向上） |
| `bearish_sweep` | 向上刺破高点扫空头止损 | **可能看跌**（反转向下） |

命名遵循"扫损后反向"逻辑，易混淆，务必记住。

---

## 更新节拍

- **建议拉取间隔**：K 线收盘 +5s

### 数据复用
- 本接口同时返回完整 Series 家族数据
- **推荐以此作为 Series 家族的主要拉取点**

---

## 已知异常

| 现象 | 处理建议 |
|---|---|
| 某些事件没有对应的价格刺穿 | HFD 算法允许"内扫"（连续 K 线组合），不要只看单根 |
| 假猎杀（扫后不反转） | 需要与 `cross_exchange_resonance` 交叉验证 |

---

## 映射到原子

→ `LiquiditySweepEvent[]`（见 [../ATOMS.md](../ATOMS.md#32-liquiditysweepevent--流动性猎杀)）

---

## 大屏使用

### 台 1 主力行为监控
```
近 10 根 K 线内出现 sweep 事件 → "猎杀中"
连续多次 sweep 同向 → "持续清洗流动性"
```

### 台 3 交易决策辅助
```
bullish_sweep + cross_exchange_resonance(buy) → "扫损后反手做多" 高分
bearish_sweep + cross_exchange_resonance(sell) → "扫损后反手做空" 高分
突破关键位后立刻 sweep 反向 → "已完成猎杀回收"（假突破）
```

---

## Schema 与 Sample

- [`../schemas/liquidity_sweep.schema.json`](../schemas/liquidity_sweep.schema.json)
- [`../samples/liquidity_sweep.sample.json`](../samples/liquidity_sweep.sample.json)
