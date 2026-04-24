# hvn_nodes — 真实换手率节点

> **业务定位**：历史 Top 10 成交密集价位（High Volume Nodes）。铁底/铁顶位。台 2/3。

---

## 请求

```
GET https://dash.hfd.fund/api/pro/pro_data?coin=BTC&indicator=hvn_nodes&tf=30m
```

---

## 响应结构

```json
{
  "klines": [...],
  "hvn_nodes": [
    {"rank": 1, "price": 108500.0, "volume": 15890.5},
    {"rank": 2, "price": 110200.0, "volume": 12430.8},
    ...
  ]
}
```

### 字段详解

| 字段 | 类型 | 说明 |
|---|---|---|
| `hvn_nodes[].rank` | `integer` | 排名 1~10（按 volume 降序） |
| `hvn_nodes[].price` | `number` | 价位 |
| `hvn_nodes[].volume` | `number` | 累积成交量 |

### 典型数据量

- **固定 10 条**（Top 10）

---

## 更新节拍

- **建议拉取间隔**：1h
- 原因：Top 10 价位变化缓慢

---

## 已知异常

| 现象 | 处理建议 |
|---|---|
| Top 1 可能远离当前价 | 历史强位不等于当前强位，但仍是关键参考 |
| 两条 HVN 价位接近 | 可合并为一条"HVN 区" |

---

## 映射到原子

→ `HvnNode[]`（见 [../ATOMS.md](../ATOMS.md#44-hvnnode--真实换手率节点)）

---

## 大屏使用

### 台 2 市场结构地图
- 画 10 条粗水平线（排名越高越粗）
- 配合 `inst_volume_profile` 使用（HVN 是其 Top 10 子集）

### 台 3 交易决策辅助
```
price 逼近 rank=1 的 HVN → 极强支撑/阻力
突破 Top 5 的 HVN + cross_exchange_resonance 确认 → 真突破高分
```

---

## Schema 与 Sample

- [`../schemas/hvn_nodes.schema.json`](../schemas/hvn_nodes.schema.json)
- [`../samples/hvn_nodes.sample.json`](../samples/hvn_nodes.sample.json)
