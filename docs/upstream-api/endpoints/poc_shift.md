# poc_shift — 均价重心偏移

> **业务定位**：POC（Point of Control，成交核心价）随时间的漂移轨迹。对比价格 MA 判断"暗吸筹/暗派发"。台 1。

---

## 请求

```
GET https://dash.hfd.fund/api/pro/pro_data?coin=BTC&indicator=poc_shift&tf=30m
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
  "poc_shift": [
    [1760680800000, 110520.5, 1532.8],
    [1760682600000, 110580.2, 1645.3],
    ...
  ],
  "micro_poc": [...],
  "liquidity_sweep": [...],
  "order_blocks": [],
  "volume_profile": []
}
```

### 字段详解（元组格式 ⚠️）

| 字段 | 类型 | 说明 |
|---|---|---|
| `poc_shift[][0]` | `number` (ms) | 时间戳 |
| `poc_shift[][1]` | `number` | POC 价格 |
| `poc_shift[][2]` | `number` | 该时刻的成交量 |

> 注意这是 **3 元素元组**，不是对象。入库时要显式解构。

### 典型数据量

- 30m 周期：约 **4900 个点**（接近每根 K 线 1 个点）

---

## 更新节拍

- **建议拉取间隔**：K 线收盘 +5s

### 数据复用
- 本接口响应 = `micro_poc` 响应 = `liquidity_sweep` 响应（Series 家族）
- 三者只需拉一个即可覆盖全部（实测 MD5 有差异的只是 micro_poc / poc_shift / liquidity_sweep 的专属字段）

---

## 已知异常

| 现象 | 处理建议 |
|---|---|
| 某些时刻 POC 跳变过大 | 可能是成交量激增 K 线，正常 |
| 连续时刻 POC 不变 | 价格盘整，正常 |

---

## 映射到原子

→ `PocShiftPoint[]`（见 [../ATOMS.md](../ATOMS.md#16-pocshiftpoint--poc-重心轨迹)）

---

## 大屏使用

### 台 1 主力行为监控（核心应用）
```
# 暗吸筹信号
价格 MA20 横盘 + POC 持续上移 → "暗吸筹"（主力偷偷建仓）

# 暗派发信号
价格 MA20 横盘 + POC 持续下移 → "暗派发"（主力偷偷出货）

# 同向确认
价格 + POC 同步上移 → 趋势延续（明牌吸筹）
```

伪代码：
```ts
const maSlope = slope(MA20, -10);  // 最近 10 根 MA 斜率
const pocSlope = slope(poc_shift, -10);  // 最近 10 个 POC 点斜率

if (abs(maSlope) < ε && pocSlope > threshold) return "暗吸筹";
if (abs(maSlope) < ε && pocSlope < -threshold) return "暗派发";
```

---

## Schema 与 Sample

- [`../schemas/poc_shift.schema.json`](../schemas/poc_shift.schema.json)
- [`../samples/poc_shift.sample.json`](../samples/poc_shift.sample.json)
