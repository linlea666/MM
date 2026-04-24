# fair_value — 真实价值走势

> **业务定位**：基于 CVD + VWAP 推演的"机构眼里的公允价"。价格偏离过大 = 背离信号。大屏台 1/3。

---

## 请求

```
GET https://dash.hfd.fund/api/pro/pro_data?coin=BTC&indicator=fair_value&tf=30m
```

---

## ⚠️ fair_value 是 Series 家族空壳

与 `fvg` / `imbalance` 返回的 JSON **完全相同**。

HFD 没算现成的 "fair_value 曲线"，需要前端/后端自己基于 `cvd_series` + `vwap_series` 推演。

**推演公式（参考）**：
```
fair_value[i] = vwap_series[i].value + alpha × (cvd_series[i].value - baseline)
alpha 常用 0.1~0.3，需要用历史数据拟合
```

---

## 响应结构

同 `fvg`（Series 家族）：

```json
{
  "klines": [...],
  "cvd_series": [[ts, value], ...],
  "imbalance_series": [[ts, value], ...],
  "inst_vol_series": [[ts, value], ...],
  "vwap_series": [[ts, vwap], ...]
}
```

### 字段详解

| 字段 | 说明 | 用于 fair_value 的方式 |
|---|---|---|
| `cvd_series[]` | 累计主动净成交量 | 主要推演依据 |
| `vwap_series[]` | VWAP 基准线 | 作为价值基准 |
| `imbalance_series[]` | 单 K 净差 | 辅助判断短期动能 |
| `inst_vol_series[]` | 机构净量 | 辅助过滤散户噪音 |

---

## 更新节拍

- **建议：不独立拉取**
- 数据完全包含在 `liquidity_sweep` / `micro_poc` / `poc_shift` 的响应中

---

## 映射到原子

不直接映射。消费的原子：
- `CvdPoint[]`
- `VwapPoint[]`
- `InstVolPoint[]`
- `Kline[]`（作为对比基准）

派生产出（由 indicator-views 层计算）：
```ts
type FairValuePoint = {
  symbol: string;
  tf: string;
  ts: number;
  fair_value: number;      // 推演的公允价
  divergence: number;      // price - fair_value
  divergence_pct: number;  // (price - fair_value) / fair_value
};
```

---

## 大屏使用

### 台 1 主力行为监控
```
price 创新高 + fair_value 下行 → "价格诱多，主力撤退"（顶背离）
price 创新低 + fair_value 抬升 → "价格诱空，主力吸筹"（底背离）
```

### 台 3 交易决策辅助
```
顶背离触发 → 反向警报，原持多仓提示减仓
底背离触发 → 反向警报，原持空仓提示减仓
```

---

## Schema 与 Sample

- [`../schemas/fair_value.schema.json`](../schemas/fair_value.schema.json)
- [`../samples/fair_value.sample.json`](../samples/fair_value.sample.json)
