# HFD 上游数据接口文档（自用版）

> 用途：把 HFD (`dash.hfd.fund`) 所有指标接口的请求方式、响应字段、业务含义、已知异常全部记录在案，方便采集器、解析器、大屏决策引擎统一引用。

---

## 1. 接口总览

- **根路径**：`https://dash.hfd.fund/api/pro/pro_data`
- **请求方法**：`GET`
- **鉴权**：当前公开（如后续加鉴权，在 header 里补 token）
- **响应格式**：JSON
- **字符集**：UTF-8
- **历史长度**：一次请求返回约 **4923 根 K 线**（30m ≈ 102 天）

### 1.1 请求参数

| 参数 | 必填 | 取值 | 示例 |
|---|---|---|---|
| `coin` | ✅ | 币种大写代码 | `BTC` / `ETH` / `SOL` |
| `indicator` | ✅ | 指标名（见下表） | `smart_money_cost` |
| `tf` | ✅ | K 线周期 | `30m` / `1h` / `4h` / `1d` |

> 历史上有文档出现过 `interval=` 参数，**实测 `tf=` 才是当前生效的参数名**。

### 1.2 示例

```
GET https://dash.hfd.fund/api/pro/pro_data?coin=BTC&indicator=smart_money_cost&tf=30m
```

---

## 2. 22 个指标对照表

| 中文名 | indicator | 端点文档 |
|---|---|---|
| 趋势成本带 | `smart_money_cost` | [endpoints/smart_money_cost.md](./endpoints/smart_money_cost.md) |
| 清算痛点地图 | `liq_heatmap` | [endpoints/liq_heatmap.md](./endpoints/liq_heatmap.md) |
| 密集博弈 | `absolute_zones` | [endpoints/absolute_zones.md](./endpoints/absolute_zones.md) |
| 筹码真空区 | `fvg` | [endpoints/fvg.md](./endpoints/fvg.md) |
| 主力大单行动 | `cross_exchange_resonance` | [endpoints/cross_exchange_resonance.md](./endpoints/cross_exchange_resonance.md) |
| 真实价值走势 | `fair_value` | [endpoints/fair_value.md](./endpoints/fair_value.md) |
| 筹码分布 | `inst_volume_profile` | [endpoints/inst_volume_profile.md](./endpoints/inst_volume_profile.md) |
| 趋势撑压 | `trend_price` | [endpoints/trend_price.md](./endpoints/trend_price.md) |
| 订单墙衰减 | `ob_decay` | [endpoints/ob_decay.md](./endpoints/ob_decay.md) |
| 微观成本线 | `micro_poc` | [endpoints/micro_poc.md](./endpoints/micro_poc.md) |
| 趋势筹码纯度 | `trend_purity` | [endpoints/trend_purity.md](./endpoints/trend_purity.md) |
| 均价重心偏移 | `poc_shift` | [endpoints/poc_shift.md](./endpoints/poc_shift.md) |
| 趋势动态防线 | `trailing_vwap` | [endpoints/trailing_vwap.md](./endpoints/trailing_vwap.md) |
| 趋势进度条 | `trend_saturation` | [endpoints/trend_saturation.md](./endpoints/trend_saturation.md) |
| 流动性黑洞预警 | `liq_vacuum` | [endpoints/liq_vacuum.md](./endpoints/liq_vacuum.md) |
| 多空失衡能量条 | `imbalance` | [endpoints/imbalance.md](./endpoints/imbalance.md) |
| 多空力量悬殊比 | `power_imbalance` | [endpoints/power_imbalance.md](./endpoints/power_imbalance.md) |
| 能量耗竭 | `trend_exhaustion` | [endpoints/trend_exhaustion.md](./endpoints/trend_exhaustion.md) |
| 燃料库清算地图 | `liquidation_fuel` | [endpoints/liquidation_fuel.md](./endpoints/liquidation_fuel.md) |
| 真实换手率节点 | `hvn_nodes` | [endpoints/hvn_nodes.md](./endpoints/hvn_nodes.md) |
| 流动性猎杀 | `liquidity_sweep` | [endpoints/liquidity_sweep.md](./endpoints/liquidity_sweep.md) |
| 资金时间热力图 | `time_heatmap` | [endpoints/time_heatmap.md](./endpoints/time_heatmap.md) |

---

## 3. ⚠️ K 线列顺序规范（最重要！）

**HFD 返回的 `klines` 列顺序是非标准的：**

```
HFD  ：[ts, open, close,  low,   high,  volume]   ← 注意 close 在 high 之前
Binance / OKX ：[ts, open, high,  low,   close, volume]   ← 行业标准
```

### 实测验证

第一根 K 线：`[1759276800000, 113988.7, 114181.1, 113899.4, 114246.0, 3773.132]`

- `114246.0` 是最大值 → **只能是 high**（位置 4）
- `113899.4` 是最小值 → **只能是 low**（位置 3）
- 剩下 `113988.7`、`114181.1` 分别是 open、close（位置 1、2）

### 强制归一化

采集层收到 HFD 响应后，**必须**立刻把 `klines` 转换成标准化对象：

```ts
type Kline = {
  ts: number;      // 毫秒时间戳（K 线开盘时间）
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};
```

任何下游模块**永远不许**直接消费数组式 kline，避免列序错位导致策略反向。

---

## 4. 接口特性（实测）

### 4.1 klines 在 22 个接口里完全相同

实测 MD5 哈希：所有 22 个接口响应里的 `klines` 字段**完全一致**。

含义：
- 任何一次请求都白送一份完整的 K 线历史
- **我们的采集策略是：只存一份 klines（来自 Binance 更可靠），HFD 响应里的 klines 丢弃**

### 4.2 有几个"空壳接口"返回相同数据

`fair_value` / `fvg` / `imbalance` 三个接口返回的 JSON **完全相同**（Series 家族），都只有 4 条 series（`cvd_series`、`imbalance_series`、`inst_vol_series`、`vwap_series`）+ 空的事件列表。

含义：
- 这 3 个指标是**前端基于 series 自己画的**，HFD 没做任何服务端聚合
- 请求时三者任选其一即可，建议拉 `liquidity_sweep`（最大的 Series 超集，多带 sweep 事件）

### 4.3 部分接口有"共享载荷"

| 重复组 | 接口 | 共享字段 | 去重建议 |
|---|---|---|---|
| Series 家族 | `fair_value` / `fvg` / `imbalance` / `liquidity_sweep` / `micro_poc` / `poc_shift` | `cvd_series` + `imbalance_series` + `inst_vol_series` + `vwap_series` | 拉 3 次（`liquidity_sweep` + `micro_poc` + `poc_shift`）覆盖全部 6 个 |
| OrderBlocks 家族 | `trend_price` / `ob_decay` | `order_blocks[]`（avg_price 形态）| 拉 1 次 `trend_price` 覆盖 2 个 |

### 4.4 实际最少请求数

22 个指标 → 实测最少 **18 次**上游请求即可覆盖全部数据：

```
Series 家族：liquidity_sweep + micro_poc + poc_shift（3 次，白送 fair_value/fvg/imbalance）
OrderBlocks：trend_price（1 次，白送 ob_decay）
独立接口：其余 14 个各 1 次
总计：3 + 1 + 14 = 18 次
```

---

## 5. 建议的刷新节拍

| 档位 | 指标 | 节拍 | 理由 |
|---|---|---|---|
| 🔴 K 线节拍 | `power_imbalance` / `trailing_vwap` / `trend_exhaustion` | K 线收盘 +3s | 每根新 K 线必更新 |
| 🔴 K 线节拍 | `liquidity_sweep` / `micro_poc` / `poc_shift` / `cross_exchange_resonance` | K 线收盘 +5s | 事件追加式 |
| 🟡 中频 | `smart_money_cost` / `trend_price` / `trend_purity` / `absolute_zones` | 30min | 段结构变化慢 |
| 🟡 中频 | `trend_saturation` | 5min | `progress` 随 current_vol 漂移 |
| 🟢 低频 | `liq_heatmap` / `liq_vacuum` / `liquidation_fuel` / `hvn_nodes` / `inst_volume_profile` | 1h | 价格带变化慢 |
| ⚪ 超低频 | `time_heatmap` | 4h | 24 小时聚合 |

**调度策略**：按"K 线收盘时间 + 固定延迟"触发，而非固定频率轮询。例：30m 周期在 `00:00:05 / 00:30:05 / 01:00:05 …` 拉取。

---

## 6. 限流与重试

- 单 IP 限流阈值未知，建议全局令牌桶 **≤ 5 QPS**
- 失败重试：指数退避（1s → 2s → 4s），最多 3 次
- 连续失败 3 次 → 告警，该 bundle 本轮跳过，下轮补拉
- 超时：单次请求 30s

---

## 7. 响应异常清单（实测发现）

| 现象 | 说明 | 处理建议 |
|---|---|---|
| `power_imbalance[*]` 大量 `buy_vol=0 / sell_vol=0 / ratio=0` | 指标"静默期"，非实时活跃 | 前端判断 ratio>阈值 才显示 |
| `trend_exhaustion[*].exhaustion = 0` | 大部分 K 线无耗竭信号 | 只高亮 > 阈值的柱子 |
| `trailing_vwap[早期]` 的 `resistance / support = null` | 需要累计足够样本 | 过滤 null 后再画 |
| `micro_poc[-1].end_time = null` | 最后一段是 Ongoing 状态 | 视为进行中，按最新 K 线时间对齐 |
| 偶发 SSL 握手失败 | 网络抖动 | 指数退避重试 3 次 |

---

## 8. 相关文档

- [ATOMS.md](./ATOMS.md) — 10 个原子数据模型的权威定义
- [DASHBOARD.md](./DASHBOARD.md) — 22 个指标如何映射到三大作战台
- [endpoints/](./endpoints/) — 每个 endpoint 的详细字段文档
- [schemas/](./schemas/) — JSON Schema，可用于入口响应校验
- [samples/](./samples/) — 真实响应样本，方便本地 mock

---

## 9. 文档维护

- 每周跑一次全量采样对比，如字段变动立刻更新本文档
- 所有字段变更必须同步更新：`endpoints/*.md` + `schemas/*.schema.json`
- 采集器入库前通过 JSON Schema 强制校验，校验失败 = 告警
