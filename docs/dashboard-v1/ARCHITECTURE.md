# MM 项目架构（技术栈 + 模块划分 + 数据契约）

> 对齐用户的 10 条开发约束（一次到位 / 分步实施 / 模块边界 / 配置外置 / 日志体系 / 错误处理）。

---

## 一、技术栈

| 层 | 技术 | 理由 |
|---|---|---|
| 后端 | **Python 3.11 + FastAPI** | 对齐 crypto-signal-hub 约束，复用 exchange_client / models / time_utils 等 |
| 采集调度 | **APScheduler** | 按 K 线收盘时间对齐的 cron |
| 存储 | **SQLite 3** | 单机自用足够，无需 Postgres 的运维成本 |
| 缓存（可选）| Redis 7 | 仅用于 AI 响应缓存 + WS 广播，V1 可不用 |
| WebSocket | FastAPI 原生 WS | 同进程推送原子更新 |
| AI | **DeepSeek API** | V1.1 引入，成本低 |
| 前端 | **TypeScript + React 18 + Vite** | 现代标配 |
| 图表 | **lightweight-charts** (TradingView 开源) | 原生支持叠加层 |
| 状态 | Zustand | 比 Redux 轻，够用 |
| UI 组件 | Tailwind + shadcn/ui | 快速构建深色大屏 |

---

## 二、模块划分（对齐约束 §2 §3 的语言）

```
mm/
├── backend/                          # Python 后端
│   ├── collector/                    # 对应约束的 monitor
│   │   ├── scheduler.py              # 调度器（启动加载 active=1 币种，支持 add/remove jobs）
│   │   ├── subscription_mgr.py       # 币种订阅管理（add/activate/deactivate/remove）
│   │   ├── hfd_client.py             # HFD API 客户端
│   │   ├── exchange_client.py        # Binance/OKX 拉 Kline（复用 crypto-signal-hub）
│   │   ├── kline_normalizer.py       # 丢弃 HFD kline，用 Binance 作真源
│   │   └── parsers/                  # 22 个 endpoint → 原子
│   ├── storage/                      # 存储层
│   │   ├── db.py                     # SQLite 连接池
│   │   ├── schema.sql                # 23 个原子表 DDL
│   │   └── repositories/             # 每个原子一个 repo
│   ├── indicators/                   # 对应约束的 brain 第一层
│   │   └── (目前无独立指标计算，仅做原子上的视图变换)
│   ├── rules/                        # 对应约束的 brain 第二层
│   │   ├── capabilities/             # 5 大能力（见 INDICATOR-COMBINATIONS.md）
│   │   │   ├── behavior_detector.py  # 能力 1：主力行为
│   │   │   ├── cost_and_wall.py      # 能力 2：成本区/攻防线
│   │   │   ├── liquidity_magnet.py   # 能力 3：清算磁吸
│   │   │   ├── support_resistance.py # 能力 4：撑压可信度
│   │   │   └── breakout_judge.py     # 能力 5：真假突破
│   │   ├── modules/                  # 6 个大屏模块
│   │   │   ├── behavior_radar.py     # 模块 ③
│   │   │   ├── state_machine.py      # 模块 ②
│   │   │   ├── participation_gate.py # 模块 ④
│   │   │   ├── key_levels.py         # 模块 ⑤
│   │   │   ├── liquidity_compass.py  # 模块 ⑥
│   │   │   └── action_card.py        # 模块 ①
│   │   └── arbitrator.py             # 冲突裁决 3 层
│   ├── ai/                           # 对应约束 brain 第三层（V1.1）
│   │   ├── deepseek_client.py
│   │   ├── prompts/                  # 4 个用途的 prompt 模板
│   │   └── cache.py                  # 响应缓存
│   ├── api/                          # 对应约束的 executor
│   │   ├── rest/                     # REST endpoints
│   │   ├── ws/                       # WebSocket 推送
│   │   └── schemas/                  # Pydantic 响应模型
│   ├── stats/                        # 对应约束的 stats
│   │   ├── signal_log.py             # 信号准确率记录
│   │   └── daily_review.py           # 日终复盘（AI 生成）
│   ├── core/
│   │   ├── logging.py                # 结构化日志（JSON + SQLite + WS 四路输出）
│   │   ├── health.py                 # 系统状态聚合
│   │   └── exceptions.py             # 统一异常类
│   ├── config/
│   │   ├── app.yaml                  # 主配置
│   │   ├── thresholds.yaml           # 所有指标阈值（可热更新）
│   │   └── .env.example              # 敏感信息模板
│   ├── logs/                         # 日志输出目录
│   ├── models.py                     # 数据结构统一定义（契约）
│   ├── main.py                       # FastAPI 入口
│   ├── pyproject.toml
│   └── requirements.txt
├── frontend/                         # TS 前端
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Dashboard/            # 主大屏页面
│   │   │   │   ├── index.tsx
│   │   │   │   ├── HeroStrip.tsx
│   │   │   │   ├── BehaviorRadar.tsx
│   │   │   │   ├── StateMachine.tsx
│   │   │   │   ├── KeyLevels.tsx
│   │   │   │   ├── LiquidityCompass.tsx
│   │   │   │   ├── ActionCards.tsx   # A/B/C 三情景（规则）
│   │   │   │   ├── AIObservationCard.tsx  # D 情景（AI 观察）
│   │   │   │   ├── MainChart.tsx
│   │   │   │   └── EventTimeline.tsx
│   │   │   └── Logs/                 # 日志面板页面（见 LOGS-MODULE.md）
│   │   │       ├── index.tsx
│   │   │       ├── SystemHealthBar.tsx
│   │   │       ├── LogFilters.tsx
│   │   │       ├── LogTable.tsx
│   │   │       ├── LogRow.tsx
│   │   │       ├── LogDetail.tsx
│   │   │       └── TagBadge.tsx
│   │   ├── stores/                   # Zustand store
│   │   ├── api/                      # REST + WS 客户端
│   │   └── types/                    # 与后端 models.py 对齐
│   ├── index.html
│   ├── package.json
│   └── vite.config.ts
├── docs/                             # 已有的设计文档
├── deploy/
│   ├── Dockerfile.backend
│   ├── Dockerfile.frontend
│   ├── docker-compose.yml
│   └── nginx.conf
├── scripts/
│   ├── dev_backend.sh
│   ├── dev_frontend.sh
│   └── hfd_monitor.py                # HFD 稳定性监控（独立脚本）
└── README.md
```

---

## 三、数据契约（约束 §3 模块边界）

所有模块间通信通过 `models.py` 定义的 Pydantic 模型。禁止直接访问他模块内部状态。

### 核心数据流

```
HFD API → [Parser] → Atom → [Capability] → CapabilityScore → [Module] → ModuleOutput → [Arbitrator] → FinalDecision → [API] → 前端
```

### 关键数据结构（`backend/models.py`）

```python
# 原子层（见 ATOMS.md 23 个原子）
class Kline(BaseModel):
    symbol: str
    tf: str
    ts: int          # ms epoch
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str      # "binance" | "okx" | "hfd"

class SmartMoneySegment(BaseModel): ...
class OrderBlock(BaseModel): ...
# ... 23 个原子

# 能力输出层
class BehaviorScore(BaseModel):
    main: Literal["强吸筹", "弱吸筹", "强派发", "弱派发", "横盘震荡", "趋势反转", "无主导"]
    main_score: int
    alerts: list["BehaviorAlert"]

class BehaviorAlert(BaseModel):
    type: Literal["共振爆发", "诱多", "诱空", "衰竭", "变盘临近", "护盘中", "压盘中", "猎杀进行中"]
    strength: int

class LevelLadder(BaseModel):
    r3: Level | None
    r2: Level | None
    r1: Level | None
    current_price: float
    s1: Level | None
    s2: Level | None
    s3: Level | None

class Level(BaseModel):
    price: float
    sources: list[str]
    strength: Literal["strong", "medium", "weak"]
    test_count: int
    decay_pct: float
    fit: Literal["first_test_good", "worn_out", "can_break", "observe"]
    score: int

class PhaseState(BaseModel):
    current: str                      # 8 阶段之一
    current_score: int
    prev_phase: str | None
    next_likely: str | None
    unstable: bool                    # 2 根内翻转 >= 2 次

class ParticipationGate(BaseModel):
    level: Literal["主力真参与", "局部参与", "疑似散户", "垃圾时间"]
    confidence: float                 # 0~1
    evidence: list[str]

class TradingPlan(BaseModel):
    """A/B/C 情景之一"""
    label: Literal["A", "B", "C"]
    action: Literal["追多", "追空", "回踩做多", "反弹做空", "反手", "观望"]
    stars: int                        # 0~5
    entry: list[float] | None         # [low, high]
    stop: float | None
    take_profit: list[float] | None   # [T1, T2]
    position_size: Literal["轻仓", "标仓", "重仓"] | None
    premise: str                      # AI 润色（V1 是规则模板）
    invalidation: str                 # AI 润色（V1 是规则模板）

class DashboardSnapshot(BaseModel):
    """一次完整的决策快照，推给前端用这个"""
    timestamp: int
    symbol: str
    tf: str
    current_price: float

    # Hero Strip 四维
    hero: "HeroStrip"

    # 6 个模块
    behavior: BehaviorScore
    phase: PhaseState
    participation: ParticipationGate
    levels: LevelLadder
    liquidity: "LiquidityCompass"
    plans: list[TradingPlan]          # 3 个（A/B/C）

    # 时间线
    recent_events: list["TimelineEvent"]

    # 健康度
    health: "DashboardHealth"

class HeroStrip(BaseModel):
    main_behavior: str                # 主力状态维度
    market_structure: str             # 市场结构维度
    risk_status: str                  # 风险状态维度
    action_conclusion: str            # 交易结论维度
    stars: int
    invalidation: str
```

---

## 四、配置外置（约束 §7）

### `config/app.yaml`
```yaml
app:
  name: MM
  version: 1.0.0
  env: production  # development | production

server:
  host: 0.0.0.0
  rest_port: 8901
  ws_port: 8902
  cors_origins: ["*"]  # 自用，反正内网

database:
  path: /data/mm.sqlite

redis:
  enabled: false  # V1 先关
  host: localhost
  port: 6379

collector:
  # 全局限流
  global_rps: 5
  request_timeout: 30

  # 多币种管理（添加即常驻，见 MASTER-PLAN.md §3）
  default_symbols: ["BTC"]            # 首次启动 seed subscriptions 表
  timeframes: ["30m", "1h", "4h"]

  # HFD API
  hfd_base_url: "https://dash.hfd.fund/api/pro/pro_data"

  # Kline 权威源（不用 HFD 的 klines）
  kline_sources:
    primary: "binance"
    fallback: ["okx"]

  # 采集节拍（见 README.md § 5）
  schedule:
    kline_close:
      - power_imbalance
      - trailing_vwap
      - trend_exhaustion
      - liquidity_sweep       # Series 家族主拉点
      - micro_poc
      - poc_shift
      - cross_exchange_resonance
    every_30min:
      - smart_money_cost
      - trend_price           # 同时覆盖 ob_decay
      - trend_purity
      - absolute_zones
    every_5min:
      - trend_saturation
    every_1h:
      - liq_heatmap
      - liq_vacuum
      - liquidation_fuel
      - hvn_nodes
      - inst_volume_profile
    every_4h:
      - time_heatmap

ai:
  enabled: false  # V1.1 再开
  provider: deepseek
  model: deepseek-chat
  base_url: "https://api.deepseek.com/v1"
  cache_ttl_minutes: 5

logging:
  format: "[%(asctime)s] [%(levelname)s] %(name)s: %(message)s"
  datefmt: "%Y-%m-%d %H:%M:%S"
  level: INFO
  handlers:
    - type: console
    - type: file
      path: logs/mm.log
      max_size_mb: 100
      backup_count: 10
```

### `config/thresholds.yaml`（所有指标阈值，约束 §7）
```yaml
behavior:
  purity_veto_threshold: 50        # 否决阈值
  activity_veto_threshold: 0.5
  smart_money_ongoing_base: 60
  resonance_bonus_cap: 15
  # ...

key_levels:
  merge_threshold_pct: 0.003       # 0.3% 合并
  min_spacing_pct: 0.005           # 档间最小 0.5%
  decay_weight_min: 0.3            # 衰减 70% 时 × 0.3

breakout:
  real_score_threshold_strong: 70  # 真突破启动
  real_score_threshold_weak: 40    # 未获确认
  fake_score_threshold: 30         # 假突破
  reverse_sweep_score: 40
  exhaustion_veto_threshold: 7
  # ...

state_machine:
  phase_score_threshold: 60        # 阶段分数下限
  instability_window: 2            # 2 根内不稳定
```

### `.env.example`（敏感信息）
```
DEEPSEEK_API_KEY=
# 未来可能需要的交易所 Key（本 V1 只读 K 线不需要）
BINANCE_API_KEY=
BINANCE_API_SECRET=
```

---

## 五、日志体系（约束 §5）

统一格式 `[%(asctime)s] [%(levelname)s] %(name)s: %(message)s`，分级与约束 §5 完全一致。

### 每模块的 logger 命名

```python
logger = logging.getLogger("collector.scheduler")       # 采集调度
logger = logging.getLogger("collector.hfd_client")      # HFD 请求
logger = logging.getLogger("rules.behavior_detector")   # 行为识别
logger = logging.getLogger("rules.arbitrator")          # 冲突裁决
logger = logging.getLogger("api.ws")                    # WS 推送
logger = logging.getLogger("ai.deepseek")               # AI 调用
logger = logging.getLogger("stats.daily_review")        # 日终
```

### 关键操作日志要求

| 操作 | Level | 必含字段 |
|---|---|---|
| 采集一轮完成 | INFO | symbol / tf / 耗时 / 原子数 |
| HFD 请求失败 | ERROR | endpoint / 重试次数 / 完整 traceback |
| 能力评分计算 | DEBUG | 能力名 / 输入原子数量 / 输出分数 |
| 状态机切换 | INFO | from_phase / to_phase / score |
| 决策生成 | INFO | action / stars / entry / stop / tp |
| 参与度 = 垃圾时间 | WARNING | 当前小时 / 活跃度 |
| 冲突裁决触发 | WARNING | 两个冲突阶段 / 最终选择 |
| AI 响应缺证据 | WARNING | prompt 摘要 / 被过滤的句子 |
| AI 调用失败 | ERROR | 用途 / 错误类型 / 降级方案 |

---

## 六、错误处理（约束 §6）

### 三大外部调用的降级

```python
# HFD 失败 → 指数退避重试 3 次 → 本轮跳过 + 告警
async def fetch_hfd(indicator: str) -> dict:
    for attempt in (1, 2, 3):
        try:
            return await hfd_client.get(indicator)
        except Exception as e:
            if attempt == 3:
                logger.error(f"HFD {indicator} 连续 3 次失败", exc_info=True)
                await alert_service.send(f"HFD {indicator} 不可用")
                raise
            await asyncio.sleep(2 ** attempt)

# Binance Kline 失败 → 降级到 OKX
async def fetch_klines(symbol, tf) -> list[Kline]:
    try:
        return await binance.klines(symbol, tf)
    except Exception as e:
        logger.warning(f"Binance 失败, 切 OKX: {e}")
        return await okx.klines(symbol, tf)

# AI 失败 → 规则结论兜底
async def enhance_with_ai(decision: Decision) -> Decision:
    try:
        narrative = await deepseek.generate(decision)
        return decision.with_narrative(narrative)
    except Exception as e:
        logger.error(f"AI 失败, 降级为纯规则: {e}", exc_info=True)
        return decision.with_fallback_narrative()
```

### 熔断机制

```python
# 连续 3 次 AI 失败 → 暂停 AI 15 分钟
circuit_breaker = CircuitBreaker(failure_threshold=3, recovery_seconds=900)
```

---

## 七、完成度检查清单（约束 §10）

每个交付的功能必须过：

- [ ] (a) 正常流程跑通且日志完整
- [ ] (b) 异常流程有兜底且不崩溃
- [ ] (c) 所有参数可配置化（查 `grep` 有没有魔数）
- [ ] (d) 多周期/多币种场景互不干扰
- [ ] (e) 日志足够定位线上问题（含 traceback）

---

## 八、分步实施清单（约束 §1b）

V1 规则闭环分 **5 步**，每步都是**可独立运行的完整单元**。

> **详细 Step 清单已移到 [`MASTER-PLAN.md §5`](../MASTER-PLAN.md)，此处仅保留架构层摘要**

### Step 1: 骨架 + 数据层
**交付物**：
- 仓库结构 + pyproject + requirements
- `models.py` 完整 23 个原子 + 6 个模块输出结构
- `storage/schema.sql`（原子表 + **subscriptions 表** + logs 表）
- SQLite 连接池 + 每个原子的 repository
- 日志配置（四路输出）
- 单元测试：原子 upsert / 查询 / subscriptions 初始化

**完成度检查**：
- 所有原子表能建/查/写
- 日志格式对齐约束 §5
- 配置文件外置
- subscriptions 启动时按 `default_symbols` 初始化

**禁止**：在 Step 1 里写任何指标计算逻辑。

---

### Step 2: 采集器 + 订阅管理
**交付物**：
- `collector/hfd_client.py` 带重试/退避/熔断
- `collector/exchange_client.py` Kline 源（Binance 主 / OKX 备）
- `collector/scheduler.py` 启动时加载 active=1 币种 + 支持 add/remove jobs
- `collector/subscription_mgr.py` add/activate/deactivate/remove
- 22 个 parser，每个把 HFD 响应拆成原子
- `scripts/hfd_monitor.py` 独立稳定性监控（30min 一次）

**完成度检查**：
- 默认激活 BTC，18 个 endpoint 一次性拉完
- 手动 add ETH 后立即触发首轮采集，约 10 秒内数据到位
- 手动 deactivate ETH，scheduler 移除该币种任务
- 重新 activate ETH，任务恢复
- HFD 挂了自动指数退避
- Binance 被封自动切 OKX
- 所有异常有 ERROR 日志 + traceback
- 连续 3 次失败 → 告警
- 运行 24h，观察原子表数据完整性

**禁止**：在 Step 2 里写规则计算。

---

### Step 3: 规则引擎（5 大能力 + 6 大模块）
**交付物**：
- 5 个 capability 文件（纯函数 `(atoms, config) -> Score`）
- 6 个 module 文件（组装 capability 输出）
- `rules/arbitrator.py` 三层冲突裁决
- 所有阈值来自 `thresholds.yaml`
- 每个 capability 的单元测试（用 samples/*.json 做 fixture）
- `DashboardSnapshot` 组装逻辑

**完成度检查**：
- 同一份历史数据两次运行结果完全一致（可复现）
- 每个能力的分数变化有 DEBUG 日志
- 阶段切换 / 警报触发 有 INFO 日志
- 无任何魔数（`grep -rn '[0-9]\+\.*[0-9]*'` 扫过）
- 5 大能力的测试覆盖率 ≥ 80%

**禁止**：在 Step 3 里调 AI。

---

### Step 4: API + WebSocket + 日志模块
**交付物**：
- REST `GET /api/snapshot?symbol=BTC&tf=30m` 拉最新快照
- REST `GET /api/history?from=X&to=Y` 拉历史快照
- REST `GET /api/logs?level=&module=&keyword=...` 日志查询
- REST `GET /api/system/health` 系统健康聚合
- REST `GET /api/logs/export` 诊断数据导出
- WS `/ws/dashboard` 推送实时快照
- WS `/ws/logs` 推送实时日志
- Pydantic schema 响应校验

**完成度检查**：
- curl 能拉到完整 `DashboardSnapshot`
- curl 能拉到最近 300 条日志
- `/api/system/health` 正确反映各数据源状态
- WS 在规则引擎计算完立即推送
- WS 断线重连机制
- 响应时间 < 100ms

---

### Step 5: 前端（大屏 + 日志面板）
**交付物**：
- **Dashboard 主页** `/`
  - Hero Strip 4 维度
  - 6 个模块卡片
  - 主图 + 多图层叠加
  - A/B/C 三情景卡
  - 异动时间线
- **Logs 日志页** `/logs`
  - 顶部系统状态栏
  - 级别 / 模块 / 币种 / 时间过滤
  - 关键词搜索
  - 行展开 context + traceback
  - WS 实时推送新日志
  - 虚拟滚动
  - 导出按钮
- 共享：WS 连接管理 / 主题 / 路由

**完成度检查**：
- 大屏页面完整展示所有 6 模块
- 日志页面满足 LOGS-MODULE.md 所有功能清单
- WS 双通道（snapshot + logs）都能断线重连
- 各模块在信号冲突时显示 ⚠️

---

### Step 整体联调
- 跑 3 天真实数据，观察状态机输出
- 对比实际行情走势，记录误判案例
- 生成 V1.1 的调参建议

---

## 九、相关文档

- [**MASTER-PLAN.md**](../MASTER-PLAN.md) — **落地总纲（从这里开始读）**
- [PLAN.md](./PLAN.md) — V1 总体布局
- [PLAN-v1.1-ai-augmented.md](./PLAN-v1.1-ai-augmented.md) — V1.1 AI 增强
- [AI-OBSERVER.md](./AI-OBSERVER.md) — **AI 观察模式（副驾驶，不是兜底）**
- [INDICATOR-COMBINATIONS.md](./INDICATOR-COMBINATIONS.md) — 指标组合手册
- [LOGS-MODULE.md](./LOGS-MODULE.md) — **日志模块（结构化 + 可视化面板）**
- [DEPLOYMENT.md](./DEPLOYMENT.md) — Docker 部署与端口规划
- [../upstream-api/](../upstream-api/) — 字段文档
