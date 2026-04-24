# inst_volume_profile — 筹码分布（机构 Volume Profile）

> **业务定位**：价格轴上每个价位的成交量分布（横向柱状图）。大屏台 2 的"筹码分布柱"。

---

## 请求

```
GET https://dash.hfd.fund/api/pro/pro_data?coin=BTC&indicator=inst_volume_profile&tf=30m
```

---

## 响应结构

```json
{
  "klines": [...],
  "volume_profile": [
    {
      "accum": 120.5,       // 主动买入量
      "dist": 83.4,         // 主动卖出量
      "total": 203.9,       // 总量
      "price": 109200.0     // 价位
    },
    ...
  ]
}
```

### 字段详解

| 字段 | 类型 | 说明 |
|---|---|---|
| `volume_profile[].price` | `number` | 价位（按固定步长分桶） |
| `volume_profile[].accum` | `number` | 该价位的主动买入量 |
| `volume_profile[].dist` | `number` | 该价位的主动卖出量 |
| `volume_profile[].total` | `number` | = accum + dist |

### 典型数据量

- 30m 周期：约 **100~300 个价位桶**
- 统计范围：全部历史 K 线的分布聚合

---

## 更新节拍

- **建议拉取间隔**：1h
- 原因：分布变化缓慢，高频拉取无意义

---

## 已知异常

| 现象 | 处理建议 |
|---|---|
| `price` 不是等距间隔 | 前端做柱状图时不要假设等距，按实际 price 定位 |
| 部分价位 `accum` 和 `dist` 都为 0 | 有成交但主动方向判断失败（忽略即可） |

---

## 映射到原子

→ `VolumeProfileBucket[]`（见 [../ATOMS.md](../ATOMS.md#45-volumeprofilebucket--筹码分布桶)）

---

## 大屏使用

### 台 2 市场结构地图
- 把 Volume Profile 画在图表右侧（横向柱状图）
- accum > dist 的价位 → 绿色柱（多头区）
- dist > accum 的价位 → 红色柱（空头区）
- total 最大的价位 → POC（Point of Control，历史核心成本）

### 配合使用
- 和 `hvn_nodes` 对比：HVN 是 Top 10 防线，Volume Profile 是全量分布

---

## Schema 与 Sample

- [`../schemas/inst_volume_profile.schema.json`](../schemas/inst_volume_profile.schema.json)
- [`../samples/inst_volume_profile.sample.json`](../samples/inst_volume_profile.sample.json)
