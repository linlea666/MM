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

详见 [`docs/dashboard-v1/DEPLOYMENT.md`](docs/dashboard-v1/DEPLOYMENT.md)。

```bash
cd deploy
docker compose up -d --build
```

访问 http://your-server:8900

---

## 当前进度

V1 规则闭环按 6 步推进：

| Step | 内容 | 状态 |
|------|------|------|
| 1 | 骨架 + 数据层 | 🟡 进行中 |
| 2 | 采集器 + 订阅管理 | ⬜ |
| 3 | 规则引擎（5 能力 + 6 模块） | ⬜ |
| 4 | API + WS + 日志模块 | ⬜ |
| 5 | 前端（大屏 + 日志面板） | ⬜ |
| 6 | 整体联调 + Docker 部署 | ⬜ |
| 7 (V1.1) | AI 观察模式 | ⬜ |
