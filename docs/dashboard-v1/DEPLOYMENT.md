# MM 项目部署方案（Docker + 宝塔）

> 服务器：8.217.240.76（香港）
> 宝塔已装 Docker，已有 6 个容器运行中。

---

## 一、现有容器与端口

从宝塔截图读取：

| 容器 | 端口（宿主 → 容器）|
|---|---|
| liq-frontend | 8801 → 3000 |
| liq-backend | 8800 → 8000 |
| discord-signal-copier | 8787 → 8787 |
| cryptosignal-hub | 8686 → 8686 |
| nofx-frontend | 3000 → 80 |
| nofx-trading | 6060 → 6060 |

**已占用的宿主端口**：`3000 / 6060 / 8686 / 8787 / 8800 / 8801`

---

## 二、MM 端口分配

避开以上，使用 **8900 段**，保持连续便于记忆：

| 端口 | 用途 | 容器 | 是否对外 |
|---|---|---|---|
| **8900** | 前端大屏（Nginx）| `mm-frontend` | ✅ 浏览器访问 |
| **8901** | 后端 REST + WebSocket（同一 ASGI 进程）| `mm-backend` | ✅ 前端调用（由前端 Nginx 反代） |
| — | SQLite 持久化 | volume 挂载 | — |
| — | Redis（V1 可选）| 容器内部，不对外 | ❌ |

> **注意**：FastAPI 的 REST 路由与 WebSocket 路由挂在同一个 ASGI 应用，uvicorn 只监听一个端口（8901）。前端 Nginx 把 `/api/` 与 `/ws/` 都反代到 `mm-backend:8901`。
>
> 访问方式：`http://8.217.240.76:8900`
> 后续可在宝塔加 SSL + 域名反代，访问 `https://mm.yourdomain.com`

---

## 三、容器拓扑

```
┌───────────────────────────────────────────────────────┐
│  浏览器 (你的电脑)                                     │
└──────────────────────┬────────────────────────────────┘
                       │ HTTPS / WSS
                       ↓
┌───────────────────────────────────────────────────────┐
│  宝塔 + Nginx 反向代理（可选，V1.1 再加 SSL）           │
└──────────────────────┬────────────────────────────────┘
                       ↓
┌───────────────────────────────────────────────────────┐
│  Docker Network: mm-net                                │
│                                                        │
│  ┌─────────────────┐       ┌─────────────────────┐   │
│  │ mm-frontend     │       │ mm-backend          │   │
│  │ Nginx 静态托管  │──────→│ FastAPI (ASGI)      │   │
│  │ :8900           │       │ :8901 REST + /ws/*  │   │
│  │                 │       │                     │   │
│  └─────────────────┘       └───────────┬─────────┘   │
│                                         │             │
│                                         ↓             │
│                            ┌────────────────────┐     │
│                            │ SQLite (volume)    │     │
│                            │ /data/mm.sqlite    │     │
│                            └────────────────────┘     │
└────────────────────────┬──────────────────────────────┘
                         │ HTTPS 出向
                         ↓
┌───────────────────────────────────────────────────────┐
│  外部 API                                              │
│  ・dash.hfd.fund  (指标)                              │
│  ・api.binance.com  (Kline)                           │
│  ・api.okx.com     (Kline 备份)                       │
│  ・api.deepseek.com (AI，V1.1)                        │
└───────────────────────────────────────────────────────┘
```

---

## 四、Dockerfile & docker-compose

> 实际落地的文件在仓库 `deploy/` 目录下：
> - `deploy/Dockerfile.backend`
> - `deploy/Dockerfile.frontend`
> - `deploy/nginx.conf`
> - `deploy/docker-compose.yml`
> - `deploy/.env.example`
>
> 下面列出要点摘录，完整版以 `deploy/` 内文件为准。

### `deploy/Dockerfile.backend`（要点）

- 基于 `python:3.11-slim`
- WORKDIR 设为 `/app`，仓库 `backend/` 整体 COPY 到 `/app/backend/`，启动命令 `uvicorn backend.main:app`（保持 import 路径一致）
- 通过环境变量重定向路径：`MM_DATABASE__PATH=/data/mm.sqlite`、`MM_LOGGING__FILE__PATH=/logs/mm.log`
- healthcheck 使用 Python 内置 `urllib`，无需 curl：
  ```python
  python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8901/health', timeout=3).status==200 else 1)"
  ```
- 暴露 8901（REST + WS 合一）

### `deploy/Dockerfile.frontend`（要点）

- 多阶段：`node:20-alpine` 做 Vite 构建 → `nginx:1.25-alpine` 托管 `dist/`
- 把 `deploy/nginx.conf` 复制到 `/etc/nginx/conf.d/default.conf`
- healthcheck 使用 `wget` 探 `/`

### `deploy/nginx.conf`（前端容器内，要点）

- SPA 入口：`try_files $uri $uri/ /index.html;`
- `/api/` 反代到 `http://mm-backend:8901`
- `/ws/` 反代到 `http://mm-backend:8901`（同一端口，加 `Upgrade` / `Connection: upgrade` 头，`proxy_read_timeout 3600s`）
- 静态资源按 content hash 强缓存 `Cache-Control: public, immutable; expires 1y`
- 额外暴露 `/backend-health` 让宝塔可以直接 curl 探后端健康

### `deploy/docker-compose.yml`（要点）

- 两个服务共用 `mm-net` bridge 网络
- `mm-backend`：暴露 `${MM_BACKEND_PORT:-8901}:8901`；挂 `mm-data → /data`、`mm-logs → /logs`
- `mm-frontend`：暴露 `${MM_FRONTEND_PORT:-8900}:80`；`depends_on: mm-backend`
- 配置文件**不再挂载**到容器（已随 `backend/config/` 打包进镜像）。如需修改阈值：前端 `配置页`（`/settings`）在线改；代码层面改则 `docker compose build mm-backend` 即可
- 宿主端口通过 `MM_FRONTEND_PORT / MM_BACKEND_PORT` 环境变量可覆盖，避免与未来新项目冲突

---

## 五、部署流程

### A. 本地开发 → Git 仓库 → 服务器拉取

```bash
# 本地
cd ~/code/我的插件/MM
git add .
git commit -m "feat: Step X 完成"
git push origin main

# 服务器（SSH）
cd /path/to/MM
git pull origin main

# 重建 + 启动
cd deploy
docker compose build
docker compose up -d

# 查看日志
docker compose logs -f mm-backend
docker compose logs -f mm-frontend

# 查看容器状态（或直接在宝塔面板看）
docker compose ps
```

### B. 宝塔面板可视化管理

Docker 拉起后，在宝塔 **Docker → 容器编排** 里：
- `mm-backend` / `mm-frontend` 会出现在列表
- 点击"管理"可以看日志、重启、停止
- 和现有 6 个容器并列，互不影响

### C. 配置文件管理

V1 采用**双源配置**（设计决定）：

1. **出厂默认**：`backend/config/rules.default.yaml`（打进镜像，不可改）
2. **运行时覆盖**：SQLite `config_overrides` 表（由 `/settings` 前端页面修改，热生效、审计入库）

阈值调整**无需重启**：直接在前端 `/settings` 改保存即可，`RulesConfigService` 会自动下发到 `RuleRunner` 并清 snapshot 缓存。

应用框架配置（`app.yaml` 里的端口、采集间隔等）需要改代码 + rebuild：
```bash
docker compose build mm-backend
docker compose up -d mm-backend
```

敏感信息走 `deploy/.env`（不入镜像，由 compose 注入）：
```
DEEPSEEK_API_KEY=sk-xxx
```

---

## 六、数据持久化

### SQLite 数据

挂载 volume `mm-data` → 容器内 `/data/mm.sqlite`

**备份方案**：
```bash
# 每日备份脚本，放 /etc/cron.daily/mm-backup.sh
#!/bin/bash
DATE=$(date +%Y%m%d)
docker exec mm-backend sqlite3 /data/mm.sqlite ".backup /data/backup/mm-${DATE}.sqlite"
# 保留最近 30 天
find /var/lib/docker/volumes/mm-data/_data/backup/ -name "mm-*.sqlite" -mtime +30 -delete
```

### 日志

挂载 volume `mm-logs` → 容器内 `/app/logs`

logrotate 自动处理（见 `config/app.yaml` 里的 logging 配置，Python 的 RotatingFileHandler 会自动切）。

---

## 七、健康检查与告警

### Docker HEALTHCHECK（已写在 Dockerfile）

```bash
# 查看健康状态
docker inspect --format='{{.State.Health.Status}}' mm-backend
```

### 应用层健康 `GET http://localhost:8901/health`（容器内）
### 或经前端反代 `GET http://localhost:8900/backend-health`（宿主）

```json
{
  "status": "ok",
  "ts": 1745489510123,
  "uptime_seconds": 86400,
  "active_symbols": ["BTC"],
  "scheduler_running": true,
  "scheduler_jobs": 15,
  "circuits": []
}
```

### 告警（V1 简单版）

- 连续 3 次采集失败 → 写 WARNING 日志 + 发送到告警 webhook（可选）
- 数据陈旧 > 1h → 写 ERROR 日志
- V1.1 可接 Telegram / Discord / 邮箱

---

## 八、端口冲突预防

部署前，在服务器上检查：

```bash
# 查看是否已被占用（现在只需 8900 / 8901 两个）
ss -tlnp | grep -E '890[01]'

# 或
netstat -tlnp | grep -E '890[01]'

# 应该返回空（无占用）；若占用可改 deploy/.env 中的 MM_FRONTEND_PORT / MM_BACKEND_PORT
```

如果未来要加其它项目，**建议遵守项目段分配**：
- `8700~8799`：discord/signal 类
- `8800~8899`：liquidation 类
- `8900~8999`：MM 作战大屏
- `8400~8499`：nofx
- `3000~3999`：前端展示类

---

## 九、开发流程

### 本地开发

```bash
# 后端
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8901

# 前端
cd frontend
npm install
npm run dev  # 默认启动在 5173，代理到 localhost:8901
```

### 本地 Docker 测试

```bash
cd deploy
docker compose -f docker-compose.yml up --build
# 访问 http://localhost:8900
```

### 推送部署

```bash
git push
# 服务器侧运行拉取脚本（可设置 CI/CD，V1 手动即可）
```

---

## 十、.env 与敏感信息

`deploy/.env.example`：
```
DEEPSEEK_API_KEY=
```

`deploy/.env`（实际，**不入 Git**）：
```
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxx
```

`.gitignore`：
```
deploy/.env
backend/.env
config/secrets.yaml
*.sqlite
logs/
```

---

## 十一、首次部署 Checklist

- [ ] 服务器端口 8900~8902 未被占用（`ss -tlnp` 确认）
- [ ] 宝塔 Docker 服务正常
- [ ] 拉取仓库代码到 `/path/to/MM`
- [ ] `config/app.yaml` 和 `config/thresholds.yaml` 已根据生产环境调整
- [ ] `deploy/.env` 已填入 DEEPSEEK_API_KEY（V1.1 需要）
- [ ] `docker compose build` 成功
- [ ] `docker compose up -d` 启动
- [ ] `docker compose ps` 确认 2 个容器都是 `healthy`
- [ ] 浏览器访问 `http://8.217.240.76:8900` 看到大屏
- [ ] WS 连接正常（F12 看 Network 有 ws 长连接）
- [ ] 查看后端日志，确认采集器在跑

---

## 十二、后续扩展方向

- **反向代理 + HTTPS**：宝塔可以一键给 `8.217.240.76:8900` 加 SSL，或配域名 `mm.xxx.com`
- **手机访问**：纯 Web 页面，默认就支持手机，但要做响应式 UI 适配（V1.1 再做）
- **多用户**：目前自用，单人访问。如果要分享朋友，需要加简单登录（OAuth 或 固定 token）
- **备份策略**：V1.1 考虑每日把 SQLite 同步到对象存储（阿里 OSS / 腾讯 COS）
