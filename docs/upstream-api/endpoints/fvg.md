# fvg — 筹码真空区（Fair Value Gap）

> **业务定位**：K 线快速跳空产生的"流动性断层"，未来会被磁吸回补。大屏台 2/3。

---

## 请求

```
GET https://dash.hfd.fund/api/pro/pro_data?coin=BTC&indicator=fvg&tf=30m
```

---

## ⚠️ 重要：fvg 是 Series 家族空壳

`fvg` / `fair_value` / `imbalance` 三个接口返回的 JSON **完全相同**，都只给 Series，没有专属字段。

**含义**：HFD 服务端没算 FVG，需要我们基于 K 线自己在前端/后端识别 FVG 缺口。

**识别算法**（三 K 线规则）：
```
对 K[n-2], K[n-1], K[n]：
  看涨 FVG：K[n-2].high < K[n].low  → 缺口 = [K[n-2].high, K[n].low]
  看跌 FVG：K[n-2].low  > K[n].high → 缺口 = [K[n].high,  K[n-2].low]
```

---

## 响应结构

```json
{
  "klines": [...],
  "cvd_series": [[ts, value], ...],
  "imbalance_series": [[ts, value], ...],
  "inst_vol_series": [[ts, value], ...],
  "vwap_series": [[ts, vwap], ...],
  "liquidity_sweep": [],
  "micro_poc": [],
  "order_blocks": [],
  "poc_shift": [],
  "volume_profile": []
}
```

### 字段详解（Series 家族共用）

| 字段 | 类型 | 说明 |
|---|---|---|
| `cvd_series[]` | `Array<[ts, value]>` | 累计主动净成交量 |
| `imbalance_series[]` | `Array<[ts, value]>` | 每根 K 线的净差 |
| `inst_vol_series[]` | `Array<[ts, value]>` | 机构识别量 |
| `vwap_series[]` | `Array<[ts, value]>` | VWAP 基准线 |
| 其它 `[]` | — | 永远为空 |

---

## 更新节拍

- **建议：不独立拉取**
- `fvg` 的数据完全包含在 `liquidity_sweep` / `micro_poc` / `poc_shift` 的响应中
- 只拉这三个其中之一，FVG 所需的所有 series 都到手，自己用 K 线算 FVG 缺口即可

---

## 映射到原子

不直接映射。消费的原子：
- `Kline[]`（用于识别 FVG）
- `VwapPoint[]`（辅助判断 FVG 有效性）

派生产出：
```ts
type FvgGap = {
  symbol: string;
  tf: string;
  start_ts: number;      // 缺口形成 K 线
  low: number;           // 缺口下边
  high: number;          // 缺口上边
  type: "bullish" | "bearish";
  mitigated: boolean;    // 是否已被回补
};
```

---

## 大屏使用

### 台 2 市场结构地图
- 下方 bullish FVG → 做多回踩目标
- 上方 bearish FVG → 做空反弹目标

### 台 3 交易决策辅助
- 价格进入 FVG 未回补区 → 挂单买/卖
- 止损放在 FVG 远端之外

---

## Schema 与 Sample

- [`../schemas/fvg.schema.json`](../schemas/fvg.schema.json)
- [`../samples/fvg.sample.json`](../samples/fvg.sample.json)
