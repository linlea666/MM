# liq_vacuum — 流动性黑洞预警

> **业务定位**：价格轴上的"真空带"（极少筹码）。一旦价格进入就会被加速吸穿。台 2/3。

---

## 请求

```
GET https://dash.hfd.fund/api/pro/pro_data?coin=BTC&indicator=liq_vacuum&tf=30m
```

---

## 响应结构（元组格式）

```json
{
  "klines": [...],
  "liq_vacuum": [
    [105200.0, 106500.0],
    [108900.0, 109800.0],
    ...
  ]
}
```

### 字段详解

| 字段 | 类型 | 说明 |
|---|---|---|
| `liq_vacuum[][0]` | `number` | 带底价 (low) |
| `liq_vacuum[][1]` | `number` | 带顶价 (high) |

> 注意是 **2 元素元组**，不是对象。

### 典型数据量

- 30m 周期：约 **5~20 个真空带**

---

## 更新节拍

- **建议拉取间隔**：1h
- 原因：真空带分布变化缓慢，但突破后会重算

---

## 已知异常

| 现象 | 处理建议 |
|---|---|
| 真空带重叠 | 合并或保留最大带 |
| 极小真空带（< 0.3% 宽度） | 过滤，不画 |

---

## 映射到原子

→ `VacuumBand[]`（见 [../ATOMS.md](../ATOMS.md#42-vacuumband--流动性真空带)）

```ts
function parse(resp): VacuumBand[] {
  return resp.liq_vacuum.map(([low, high]) => ({
    symbol, tf, low, high
  }));
}
```

---

## 大屏使用

### 台 2 市场结构地图
- 真空带画成半透明矩形（不同于 OrderBlock）
- 带宽越宽，染色越深

### 台 3 交易决策辅助
```
price 进入真空带 → "进入低阻力真空区"
真空带是单边加速的"滑滑梯" → 顺势持仓/加仓
反向真空带 = 不要在里面反向入场
```

---

## Schema 与 Sample

- [`../schemas/liq_vacuum.schema.json`](../schemas/liq_vacuum.schema.json)
- [`../samples/liq_vacuum.sample.json`](../samples/liq_vacuum.sample.json)
