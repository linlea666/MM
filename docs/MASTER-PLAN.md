# MM 项目落地总纲（Master Plan）

> 本文档是所有设计决策的**单一入口**，子文档为细节展开。
> 修订前请先阅读此文档，再改其它文档。

---

## 一、产品定位

### 是什么
基于 HFD 22 指标数据源的**个人交易作战大屏**，回答 5 个问题：

1. 现在主力在干什么？
2. 现在市场处于什么阶段？
3. 关键位在哪里？
4. 下一步可能往哪边扫流动性？
5. 当前最值得执行的交易动作是什么？

### 不是什么
- ❌ 不是商业产品
- ❌ 不是自动交易机器人（本版本不下单）
- ❌ 不是纯量化平台（不做高频策略、不做全市场扫描）

### 目标用户
- ✅ 仅本人（自用，单用户）
- 服务器：`8.217.240.76`（香港，宝塔面板 + Docker）

---

## 二、最终技术决策（一览）

| 决策项 | 结论 | 依据 |
|--------|------|------|
| 指标组合策略 | **方案 B：三层架构（主/确认/否决）**，阈值可配置 | 无历史回测数据，需抗噪 |
| 后端语言 | **Python 3.11** | 对齐约束，复用 crypto-signal-hub .py 文件 |
| 后端框架 | **FastAPI** | 异步 + WS + Pydantic |
| 前端 | **TypeScript + React + Vite** | 现代大屏标配 |
| 图表库 | **lightweight-charts**（TradingView 开源） | 原生支持多图层叠加 |
| 存储 | **SQLite 3** | 单机自用 |
| 采集调度 | **APScheduler**（动态注册/注销）| 支持按需激活/停用币种 |
| AI | **DeepSeek**，V1.1 引入 | 成本低，能力足 |
| AI 定位 | **观察模式**（非兜底），与规则层物理隔离 | 防幻觉 + 保可解释性 |
| 部署 | **Docker 双容器** 端口 8900/8901/8902 | 避开宝塔现有 6 容器端口 |
| 多币种 | **添加即常驻**（方案 B），默认 BTC，常驻上限 5~6 个 | 大屏与采集解耦，常驻请求量完全可控 |
| 日志 | **结构化 JSON + 四路输出**（控制台/文件/SQLite/WS）+ 前端面板 | 约束 §5 + 对标 LIQ |

---

## 三、多币种管理（添加即常驻 / 方案 B）

> 经讨论确认：大屏读本地，零 HFD 压力；采集器是唯一对外发请求的层。
> 自用场景币种数稳定 5~6 个上限，常驻全采约 200~250 次/h，完全可控。
> **不引入冷却期、动态切换、并发上限**等过度设计。

### 3.1 原则
- **大屏仅读本地 SQLite，零 HFD 压力**
- **添加币种 → 自动 active=1 → 常驻采集**
- **可手动停用长期不看的币种（数据保留）**
- **首次启动默认插入 BTC**
- **切换币种秒切**（数据始终新鲜）

### 3.2 `subscriptions` 表（极简版）

```sql
CREATE TABLE subscriptions (
  symbol          TEXT PRIMARY KEY,             -- BTC, ETH, SOL...
  display_order   INTEGER NOT NULL DEFAULT 0,   -- 前端排序
  active          INTEGER NOT NULL DEFAULT 1,   -- 1=正在采集, 0=已停用
  added_at        TEXT NOT NULL,
  last_viewed_at  TEXT
);

CREATE INDEX idx_sub_active ON subscriptions(active);
```

### 3.3 启动流程

```
应用启动
  ↓
若 subscriptions 为空 → 插入 default_symbols（默认 BTC）
  ↓
读取 WHERE active=1 → 全部注册采集任务
  ↓
启动 API / WS
```

### 3.4 添加新币种流程

```
用户点 [+ 添加币种] → 弹窗输入 "SOL"
  ↓
前端 POST /api/symbols {symbol: "SOL"}
  ↓
后端:
  ・规范化 → "SOL"
  ・调 Binance GET /api/v3/exchangeInfo 验证存在
  ・HFD 试探性调用 smart_money_cost?coin=SOL（超时 5s）
  ・若通过 → insert subscriptions (active=1)
  ・立即触发首轮采集（不等 cron）
  ・返回 201
  ↓
前端 UI 立即多出 [SOL ●] tab
约 10 秒首批数据到位
```

### 3.5 切换币种流程（秒切）

```
用户点 [ETH ●]
  ↓
前端读 /api/snapshot?symbol=ETH（本地 SQLite，毫秒级）
  ↓
WS 重新订阅 /ws/dashboard?symbol=ETH
  ↓
大屏切换完毕
```

无需"激活等待" — 因为常驻采集，数据始终新鲜。

### 3.6 停用 / 重新激活 / 移除

```
长按 [DOGE ●] → "停用"
  ↓
POST /api/symbols/DOGE/deactivate
  ・scheduler.remove_jobs("DOGE")
  ・active=0
  ・数据保留
  ↓
UI 变 [DOGE ○]（灰色，可见但不更新）

——————————

点 [DOGE ○] → "重新激活"
  ↓
POST /api/symbols/DOGE/activate
  ・scheduler.add_jobs("DOGE")
  ・active=1
  ・触发首轮采集
  ↓
约 10 秒数据回流

——————————

[DOGE ○] 状态下，长按 → "移除"
  ↓
DELETE /api/symbols/DOGE
  ・若 active=1 → 先 deactivate
  ・DELETE FROM subscriptions WHERE symbol='DOGE'
  ・原子数据可选保留 7 天后清理
```

### 3.7 实际负载预估

| 币种数 | 每小时 HFD 请求 | 每分钟 |
|---|---|---|
| 1 (BTC) | ~40 | < 1 |
| 3 (BTC/ETH/SOL) | ~120 | 2 |
| **6 (常驻上限)** | **~240** | **4** |

完全在 HFD 公开 API 的合理使用范围内。无需任何并发上限或冷却期。

### 3.8 WebSocket 订阅

每个 WS 连接带 `symbol` 查询参数：
```
ws://host:8902/ws/dashboard?symbol=BTC
ws://host:8902/ws/dashboard?symbol=ETH
```

后端广播时只推给订阅了对应 symbol 的客户端。

---

## 四、完整模块地图

```
┌─────────────────── 前端 (frontend/) ───────────────────┐
│                                                        │
│  Dashboard 大屏 (/)         Logs 日志面板 (/logs)      │
│  ├── HeroStrip              ├── SystemHealthBar        │
│  ├── BehaviorRadar          ├── LogFilters             │
│  ├── StateMachine           ├── LogTable               │
│  ├── KeyLevels              └── LogDetail              │
│  ├── LiquidityCompass                                  │
│  ├── ActionCards (A/B/C)    SymbolTabs (币种栏)        │
│  ├── AIObservationCard (D)  ├── activate/deactivate    │
│  └── EventTimeline          └── + 添加币种             │
│                                                        │
└────────┬─────────────────────────────────┬─────────────┘
         │ REST                            │ WebSocket
         ↓                                 ↓
┌─────────────────── 后端 (backend/) ─────────────────────┐
│                                                         │
│  api/                        core/                      │
│  ├── rest/ (snapshot/logs/  ├── logging.py             │
│  │     health/symbols)      ├── health.py              │
│  └── ws/ (dashboard/logs)   └── exceptions.py          │
│                                                         │
│  rules/ (brain 第二层)       ai/ (brain 第三层, V1.1)   │
│  ├── capabilities/          ├── deepseek_client.py     │
│  ├── modules/               ├── observer.py            │
│  └── arbitrator.py          └── cache.py               │
│                                                         │
│  collector/ (monitor)        storage/                   │
│  ├── scheduler (动态)       ├── db.py                  │
│  ├── hfd_client             ├── schema.sql             │
│  ├── exchange_client        └── repositories/          │
│  ├── parsers/                                           │
│  └── subscription_mgr                                   │
│                                                         │
│  stats/  models.py  config/  main.py                    │
└─────────────┬───────────────────────────────────────────┘
              │
              ↓
┌──────────── 外部数据源 ──────────┐
│ HFD / Binance / OKX / DeepSeek  │
└─────────────────────────────────┘
```

### 模块对应约束 §2

| 约束 | MM 模块 |
|---|---|
| monitor | collector |
| brain | indicators + rules + ai |
| executor | api |
| stats | stats |
| web | frontend |

### 子文档索引

| 文档 | 范围 |
|------|------|
| [`dashboard-v1/PLAN.md`](dashboard-v1/PLAN.md) | V1 大屏总体布局 |
| [`dashboard-v1/PLAN-v1.1-ai-augmented.md`](dashboard-v1/PLAN-v1.1-ai-augmented.md) | V1.1 AI 增强 |
| [`dashboard-v1/AI-OBSERVER.md`](dashboard-v1/AI-OBSERVER.md) | AI 观察模式（红线+校验器） |
| [`dashboard-v1/INDICATOR-COMBINATIONS.md`](dashboard-v1/INDICATOR-COMBINATIONS.md) | 5 能力 × 指标组合细节 |
| [`dashboard-v1/ARCHITECTURE.md`](dashboard-v1/ARCHITECTURE.md) | 技术栈 + 目录结构 + 数据契约 |
| [`dashboard-v1/LOGS-MODULE.md`](dashboard-v1/LOGS-MODULE.md) | 日志模块（后端 + 前端面板） |
| [`dashboard-v1/DEPLOYMENT.md`](dashboard-v1/DEPLOYMENT.md) | Docker / 端口 / 宝塔 |
| [`upstream-api/`](upstream-api/) | HFD 22 endpoint 字段文档 |

---

## 五、六步落地路径

> 约束 §1b：每步都是可独立运行的完整单元，**完成度检查通过后再下一步**。

### Step 1：骨架 + 数据层（1.5 天）

**交付物**
- 目录结构 + pyproject.toml + requirements.txt
- `backend/models.py`：23 原子 + 6 模块输出的完整 Pydantic 定义
- `backend/storage/schema.sql`：原子表 + `subscriptions` 表 + `logs` 表
- `backend/storage/db.py`：SQLite 连接池 + WAL 模式
- `backend/storage/repositories/` 每类原子一个 repo
- `backend/core/logging.py`：四路输出（文本/控制台/SQLite/WS 预留钩子）
- `backend/config/app.yaml` + `thresholds.yaml` + `.env.example`
- `scripts/dev_backend.sh`
- 单元测试：
  - 原子 upsert / 查询
  - 日志格式 + SQLite 入库
  - subscriptions 初始化（default_symbols → BTC active=1）

**完成度检查**
- [ ] `pytest` 全部通过
- [ ] 应用能启动（空 API）且日志格式对齐约束 §5
- [ ] 重启后 subscriptions 状态恢复
- [ ] 无任何硬编码魔数（`grep -rn '[0-9]\+' --include='*.py' backend/` 审一遍）
- [ ] config 外置，所有阈值走 `thresholds.yaml`
- [ ] logs 表 7 天自动清理任务挂载

**禁止**：Step 1 不写指标计算、不写 API、不写采集。

---

### Step 2：采集器 + 订阅管理（3 天）

**交付物**
- `backend/collector/hfd_client.py`：重试/退避/超时/日志
- `backend/collector/exchange_client.py`：Binance 主 + OKX 备（Kline）
- `backend/collector/scheduler.py`：**DynamicScheduler**（按需启停）
- `backend/collector/subscription_mgr.py`：激活/停用/冷却期管理
- `backend/collector/parsers/`：22 个 endpoint → 原子
- `backend/collector/kline_normalizer.py`：HFD kline 被丢弃，用 Binance 的
- `scripts/hfd_monitor.py`：独立稳定性监控（30min 一次）
- 单元测试 + 集成测试：
  - 单 endpoint 拉取 + parser 正确性（用 `docs/upstream-api/samples/` 做 fixture）
  - HFD 连续失败触发告警
  - Binance 失败切 OKX
  - activate/deactivate 的 scheduler 任务注册/注销
  - 冷却期清理任务

**完成度检查**
- [ ] 默认激活 BTC，跑 24h 原子表完整（每个 endpoint 有数据）
- [ ] 手动激活 ETH，采集立即启动
- [ ] 停用后 scheduler 无 ETH 任务（用 `scheduler.get_jobs()` 验证）
- [ ] HFD 重试日志完整（含 tag `[HFD]`）
- [ ] Binance→OKX 切换有 WARNING 日志（tag `[FAILOVER]`）
- [ ] 所有异常有 ERROR + 完整 traceback
- [ ] 连续 3 次某 endpoint 失败 → 告警日志（tag `[CIRCUIT]`）
- [ ] HFD 监控脚本可独立运行

**禁止**：Step 2 不写规则引擎、不写 API。

---

### Step 3：规则引擎（4 天）

**交付物**
- `backend/rules/capabilities/`：5 个能力
  - `behavior_detector.py`（能力 1）
  - `cost_and_wall.py`（能力 2）
  - `liquidity_magnet.py`（能力 3）
  - `support_resistance.py`（能力 4）
  - `breakout_judge.py`（能力 5）
- `backend/rules/modules/`：6 个模块
  - `behavior_radar.py` / `state_machine.py` / `participation_gate.py`
  - `key_levels.py` / `liquidity_compass.py` / `action_card.py`
- `backend/rules/arbitrator.py`：3 层冲突裁决
- `backend/rules/engine.py`：编排所有能力和模块，产出 `DashboardSnapshot`
- 所有阈值来自 `thresholds.yaml`
- 每个能力的单元测试（用 samples fixture）
- 集成测试：给定一组原子 → 产出确定的 snapshot（可复现）

**完成度检查**
- [ ] 同一份原子数据，两次运行 snapshot 完全一致
- [ ] 5 能力单元测试覆盖率 ≥ 80%
- [ ] 每个能力的分数变化有 DEBUG 日志
- [ ] 阶段切换 / 警报 有 INFO 日志 + 对应 tag
- [ ] 高星级信号（≥4★）有 WARNING + `[URGENT]` tag
- [ ] 冲突裁决触发有 WARNING + `[CONFLICT]` tag
- [ ] `grep -rn '[0-9]\+\.*[0-9]*' backend/rules/` 无魔数
- [ ] 通过 "regression fixture"：保存 20 种手工构造的典型行情场景（吸筹/派发/假突破/…），期望输出固定

**禁止**：Step 3 不调 AI、不写 API 层。

---

### Step 4：API + WS + 日志模块（2.5 天）

**交付物**

REST：
- `GET  /api/snapshot?symbol=&tf=`
- `GET  /api/history?symbol=&tf=&from=&to=`
- `GET  /api/symbols`（列表）
- `POST /api/symbols`（添加）
- `DELETE /api/symbols/{symbol}`
- `POST /api/symbols/{symbol}/activate`
- `POST /api/symbols/{symbol}/deactivate`
- `GET  /api/logs?level=&module=&keyword=&symbol=&from=&to=&limit=`
- `GET  /api/logs/export`
- `GET  /api/system/health`

WebSocket：
- `/ws/dashboard?symbol=` 推送该币种实时快照
- `/ws/logs` 推送实时日志

其它：
- Pydantic schema 响应校验
- CORS 配置（自用，开放）
- Rate limit（自用，宽松）
- 健康检查 + 优雅关闭

**完成度检查**
- [ ] curl 能拉到完整 `DashboardSnapshot`
- [ ] curl 能拉到最近 300 条日志
- [ ] `/api/system/health` 反映 HFD/Binance/OKX/DeepSeek/SQLite 状态
- [ ] WS `dashboard` 在规则计算完立即推送
- [ ] WS `logs` 每条日志立即推送
- [ ] 多币种 WS 订阅互不串扰（BTC 订阅不收到 ETH）
- [ ] 添加币种时 Binance 校验失败 → 400 + 明确错误
- [ ] 超过 max_concurrent_symbols 激活 → 409 + 清晰提示
- [ ] 响应时间 P99 < 100ms
- [ ] 所有 API 错误返回统一格式 `{error: {code, message, detail}}`

**禁止**：Step 4 不碰前端、不引入 AI。

---

### Step 5：前端（大屏 + 日志面板 + 币种管理）（4 天）

**交付物**

主大屏 `/`：
- HeroStrip（4 维度结论）
- BehaviorRadar / StateMachine / ParticipationGate / KeyLevels / LiquidityCompass
- ActionCards（A/B/C，规则）
- AIObservationCard（D，V1 占位，V1.1 启用）
- MainChart（lightweight-charts + 叠加层）
- EventTimeline（异动时间线）
- SymbolTabs（顶部币种切换栏 + 添加按钮）

日志页 `/logs`（对标 LIQ 截图加强版）：
- SystemHealthBar / LogFilters / LogTable（虚拟滚动）/ LogRow / LogDetail
- 级别/模块/币种/时间过滤
- 关键词搜索
- 标签高亮（URGENT/AI/CONFLICT/HFD/…）
- 行展开看 traceback
- 自动刷新（WS）/ 手动刷新
- 导出

共享：
- WS 双通道管理（dashboard + logs）+ 断线重连
- 路由（React Router）
- Zustand stores
- Tailwind + shadcn/ui 暗色主题
- TypeScript types 与后端 models.py 对齐

**完成度检查**
- [ ] 浏览器访问 `http://localhost:8900/` 看到完整大屏
- [ ] 切换币种 BTC↔ETH 流畅，WS 无冗余订阅
- [ ] 添加新币种（如 SOL）成功
- [ ] 移除币种成功
- [ ] `/logs` 页面所有过滤功能可用
- [ ] 实时推送新日志到列表头部
- [ ] 点击 ERROR 行展开完整 traceback
- [ ] WS 手动断网模拟 → 3 秒内重连
- [ ] 暗色主题 + 响应式基础适配（桌面优先）

**禁止**：Step 5 不做 AI 观察模式（V1.1）。

---

### Step 6：整体联调 + Docker 部署（2 天）

**交付物**
- `deploy/Dockerfile.backend` + `Dockerfile.frontend`
- `deploy/docker-compose.yml`
- `deploy/nginx.conf`
- `deploy/.env.example`
- `README.md`（部署 + 开发指南）
- 首次部署 Checklist 执行
- 真实数据跑 3 天，记录误判案例 → 生成调参建议 Issue

**完成度检查**
- [ ] 本地 `docker compose up --build` 成功
- [ ] 浏览器访问 `http://localhost:8900` 看到大屏
- [ ] 推送仓库 → 服务器 git pull → `docker compose up -d`
- [ ] 宝塔面板看到 `mm-backend` / `mm-frontend` 容器，healthy
- [ ] 端口不冲突（宿主 8900/8901/8902 独占）
- [ ] 浏览器访问 `http://8.217.240.76:8900` 看到大屏
- [ ] 重启服务器后 subscriptions 状态恢复
- [ ] 3 天数据 + 日志观察无 ERROR 累积
- [ ] 手动验证 5 个能力在真实场景下输出合理

---

### V1.1：AI 观察模式（1 周，V1 稳定后）

详见 [`AI-OBSERVER.md`](dashboard-v1/AI-OBSERVER.md)。
- DeepSeek 客户端
- Observer 任务（5 分钟一次）
- AIObservationCard 激活
- 日终复盘
- AI 解释按钮

---

### Step 7：动能能量柱 + 目标投影（V1.1 增量）

> 把"现在多空哪边在烧油 / 油烧完前价格的磁吸目的地在哪"做成两张可视卡 + 多 TF 灯带。
> 全部基于已有 `FeatureSnapshot` 字段派生，不引入新原子表。

详见 [`MOMENTUM-PULSE.md`](dashboard-v1/MOMENTUM-PULSE.md)（含数据契约 / 配置 / 公式 / 风险）。

- Step 7.1：S1 后端派生 view（`FeatureExtractor` 末尾增加 `_derive_momentum_pulse` / `_derive_target_projection`）
- Step 7.2：S2 后端 DTO + cards 装入 + `rules.default.yaml` 新节 + 多 TF API `/api/momentum_pulse`
- Step 7.3：S3 前端 `momentum-pulse.tsx` / `target-projection.tsx` + 多 TF 灯带 + 三只时钟
- Step 7.4：S4 真实数据 24h 跑测，记录误判 → `MOMENTUM-TUNING-LOG.md`

---

## 六、里程碑时间线

| 里程碑 | 耗时 | 目标 |
|--------|------|------|
| M1：Step 1 骨架 | 1.5 天 | 基础设施就绪 |
| M2：Step 2 采集器 | 3 天 | 数据层自动跑 |
| M3：Step 3 规则引擎 | 4 天 | 可产 snapshot |
| M4：Step 4 API + 日志 | 2.5 天 | 后端完整 |
| M5：Step 5 前端 | 4 天 | 大屏可用 |
| M6：Step 6 联调部署 | 2 天 | 上线宝塔 |
| **V1 合计** | **~17 天** | **规则闭环可用** |
| M7：V1.1 AI 观察 | 7 天 | AI 副驾驶上线 |

---

## 七、风险清单

| 风险 | 可能性 | 影响 | 规避 |
|------|-------|------|------|
| HFD 单源风险 | 中 | 高 | 稳定性监控脚本 + 字段文档化 + 架构预留多源 adapter |
| Binance 地区限制 | 低 | 中 | 服务器在香港 + OKX 备份 |
| 规则阈值不准 | 高 | 中 | 全部可配置化 + V1.1 AI 日终复盘自动调参 |
| HFD 改字段 | 中 | 中 | JSON Schema 强校验，失败告警 |
| 切换币种卡顿 | 低 | 低 | 冷却期机制 + WS 预连接 |
| AI 幻觉 | 中 | 高 | 观察模式隔离 + Pydantic 校验器 + 禁止词 |
| SQLite 数据量大 | 低 | 低 | logs 表 7 天清理 + 定期 VACUUM |
| 容器端口冲突 | 低 | 高 | 8900 段独占 + 部署前 `ss -tlnp` 检查 |
| 宝塔面板影响 | 低 | 低 | 用 `docker compose` 独立管理，面板只读模式 |

---

## 八、约束映射自检表

| 约束 | 本项目落实 |
|------|-----------|
| §1 一次到位 | 每步完整交付（含正常+异常+日志+配置）|
| §1b 分步实施 | 6 步清单 + 每步完成度检查 |
| §2 架构先行 | 5 层架构 + 模块边界 |
| §3 模块边界 | `models.py` 统一契约，跨模块只传 Pydantic |
| §4 多账户隔离 | V1 单账户（自用无需），V1.1 如加多用户时按 symbol 隔离 |
| §5 日志体系 | 见 LOGS-MODULE.md，四路输出 + 前端面板 |
| §6 错误处理 | try/except + 重试 + 降级 + 熔断 |
| §7 配置外置 | `app.yaml` + `thresholds.yaml` + `.env` |
| §8 复用来源 | crypto-signal-hub 的 exchange_client/models/time_utils 作起点 |
| §9 先说后做 | 所有多文件改动前先落文档 |
| §10 完成度检查 | 每步 5 项 (a)(b)(c)(d)(e) |

---

## 九、现在启动

在你最终确认本文档后，我立即开 **Step 1（骨架 + 数据层）**。

Step 1 交付我会**跑完所有单元测试**并在本地启动空 API 验证，完成度 5 项全部 ✅ 才进入 Step 2。

期间任何偏离本 MASTER-PLAN 的改动都先回这份文档更新，再动代码。
