# MM — 主力行为作战大屏

基于 HFD 22 指标 + Binance K 线的个人交易决策辅助大屏。
**自用，非商业**。

---

## 目标

让用户在最短时间内回答 5 个问题：

1. 现在主力在干什么？
2. 现在市场处于什么阶段？
3. 关键位在哪里？
4. 下一步可能往哪边扫流动性？
5. 当前最值得执行的交易动作是什么？

---

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11 + FastAPI + APScheduler |
| 存储 | SQLite 3 (WAL) |
| 前端 | TypeScript + React + Vite + lightweight-charts |
| AI（V1.1） | DeepSeek API（观察模式，非兜底） |
| 部署 | Docker 双容器（端口 8900/8901/8902） |

---

## 设计文档

**先读** [`docs/MASTER-PLAN.md`](docs/MASTER-PLAN.md) 总入口。

子文档：
- [`docs/dashboard-v1/PLAN.md`](docs/dashboard-v1/PLAN.md) — V1 大屏布局
- [`docs/dashboard-v1/PLAN-v1.1-ai-augmented.md`](docs/dashboard-v1/PLAN-v1.1-ai-augmented.md) — V1.1 AI 增强
- [`docs/dashboard-v1/AI-OBSERVER.md`](docs/dashboard-v1/AI-OBSERVER.md) — AI 观察模式
- [`docs/dashboard-v1/INDICATOR-COMBINATIONS.md`](docs/dashboard-v1/INDICATOR-COMBINATIONS.md) — 指标组合手册
- [`docs/dashboard-v1/ARCHITECTURE.md`](docs/dashboard-v1/ARCHITECTURE.md) — 技术架构
- [`docs/dashboard-v1/LOGS-MODULE.md`](docs/dashboard-v1/LOGS-MODULE.md) — 日志模块
- [`docs/dashboard-v1/DEPLOYMENT.md`](docs/dashboard-v1/DEPLOYMENT.md) — Docker 部署
- [`docs/upstream-api/`](docs/upstream-api/) — HFD 22 endpoint 字段文档

---

## 开发

### 后端

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

cp config/.env.example .env
uvicorn main:app --reload --port 8901
```

### 前端（Step 5 后启用）

```bash
cd frontend
npm install
npm run dev
```

### 测试

```bash
cd backend
pytest -v
```

---

## 部署

- **宝塔面板一步步**：[`docs/DEPLOY-BAOTA.md`](docs/DEPLOY-BAOTA.md)（推荐）
- **架构设计**：[`docs/dashboard-v1/DEPLOYMENT.md`](docs/dashboard-v1/DEPLOYMENT.md)

```bash
# 服务器上
cd /www/mm
cp deploy/.env.example deploy/.env  # 填 DEEPSEEK_API_KEY 等
./scripts/deploy.sh                  # 一键拉代码 + 构建 + 启动 + 健康检查
```

访问 `http://your-server:8900`

---

## 当前进度

V1 规则闭环：

| Step | 内容 | 状态 |
|------|------|------|
| 1 | 骨架 + 数据层 | ✅ |
| 2 | 采集器 + 订阅管理（22 原子 repo + 23 parser + APScheduler） | ✅ |
| 3 | 规则引擎（6 能力评分 + 6 模块 builder + RuleRunner） | ✅ |
| 4 | REST + WebSocket + 配置 API + 日志模块 | ✅ |
| 5 | 前端（大屏 + 订阅 + 配置 + 日志 + WS 实时） | ✅ |
| 6.1 | Dockerfile + nginx + compose + 备份脚本 | ✅ |
| 6.2 | 服务器部署联调 | 🟡 进行中 |
| 7 (V1.1) | AI 观察模式 | ⬜ |

后端测试：178/178 passed · 前端 typecheck + build 均绿。
