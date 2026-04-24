# imbalance — 多空失衡能量条

> **业务定位**：单根 K 线的主动买卖净差（短期动能）。台 1。

---

## 请求

```
GET https://dash.hfd.fund/api/pro/pro_data?coin=BTC&indicator=imbalance&tf=30m
```

---

## ⚠️ imbalance 是 Series 家族空壳

与 `fvg` / `fair_value` 响应**完全相同**。HFD 没提供专属计算，需要基于 `imbalance_series` 直接消费。

---

## 响应结构

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

| 字段 | 说明 | 用于 imbalance 的方式 |
|---|---|---|
| `imbalance_series[]` | 每根 K 线的 buy_vol - sell_vol | **直接画成柱状图** |
| `cvd_series[]` | 累计版 | 累计值对比 |

---

## 更新节拍

- **建议：不独立拉取**
- 数据包含在 `liquidity_sweep` / `micro_poc` / `poc_shift` 中

---

## 映射到原子

→ `ImbalancePoint[]`（见 [../ATOMS.md](../ATOMS.md#13-imbalancepoint--单-k-线净差)）

---

## 大屏使用

### 台 1 主力行为监控
- 柱状图画在 K 线下方
- 正值绿色（主动买）、负值红色（主动卖）
- 连续 5 根同向 → "持续单向进攻"

### 台 3 辅助（次要）
- 入场时用 imbalance 判断当前 K 线的买卖力量

---

## Schema 与 Sample

- [`../schemas/imbalance.schema.json`](../schemas/imbalance.schema.json)
- [`../samples/imbalance.sample.json`](../samples/imbalance.sample.json)
