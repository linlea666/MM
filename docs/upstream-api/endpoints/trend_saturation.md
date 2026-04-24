# trend_saturation — 趋势进度条

> **业务定位**：当前 Ongoing 段走到"能量天花板"的百分比，用于变盘预警。台 1/3。

---

## 请求

```
GET https://dash.hfd.fund/api/pro/pro_data?coin=BTC&indicator=trend_saturation&tf=30m
```

---

## 响应结构（唯一的单对象响应）

```json
{
  "klines": [...],
  "trend_saturation": {
    "type": "Accumulation",
    "start_time": "2026-04-20 21:00:00",
    "avg_vol": 2850.3,
    "current_vol": 2475.1,
    "progress": 86.84
  }
}
```

### 字段详解

| 字段 | 类型 | 示例 | 说明 |
|---|---|---|---|
| `trend_saturation.type` | `string` | `Accumulation` / `Distribution` | 当前 Ongoing 段类型 |
| `trend_saturation.start_time` | `string` (UTC) | `"2026-04-20 21:00:00"` | ⚠️ **是字符串**，不是 ms 时间戳 |
| `trend_saturation.avg_vol` | `number` | `2850.3` | 历史同类型段的平均成交量 |
| `trend_saturation.current_vol` | `number` | `2475.1` | 当前段已累积的成交量 |
| `trend_saturation.progress` | `number` | `86.84` | 百分比 = current_vol / avg_vol × 100，**可能 > 100** |

### 入库注意

```ts
// start_time 必须转换
const ts = new Date(resp.trend_saturation.start_time + ' UTC').getTime();
```

---

## 更新节拍

- **建议拉取间隔**：5 min
- 原因：`current_vol` 随每笔成交变化，高频拉取有意义

---

## 已知异常

| 现象 | 处理建议 |
|---|---|
| `progress > 100` | 能量超额，变盘迫在眉睫（特别关注） |
| `start_time` 字符串格式 | 入库前 UTC 转毫秒 |

### progress 阈值建议

| progress | 含义 | 大屏表现 |
|---|---|---|
| 0~40% | 新段启动 | 进度条 1/3 填充 |
| 40~80% | 段中期 | 进度条 2/3 填充 |
| 80~100% | 接近能量临界 | 进度条接近满格 + 黄色预警 |
| > 100% | 超额透支 | 红色告警 + "变盘即至" |

---

## 映射到原子

→ `TrendSaturationStat`（见 [../ATOMS.md](../ATOMS.md#52-trendsaturationstat--趋势进度单对象)）

---

## 大屏使用

### 台 1 主力行为监控
```
progress ≥ 80%  → 标签 "变盘预警"
progress ≥ 100% → 标签 "变盘在即"（强提示）
```

### 台 3 交易决策辅助
```
progress < 40% 且 type = Accumulation → "吸筹早期，回踩做多可行"
progress > 80% 且 type = Distribution → "派发末期，做空谨慎"（可能即将反转）
```

---

## Schema 与 Sample

- [`../schemas/trend_saturation.schema.json`](../schemas/trend_saturation.schema.json)
- [`../samples/trend_saturation.sample.json`](../samples/trend_saturation.sample.json)
