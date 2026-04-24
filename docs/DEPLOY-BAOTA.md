# 宝塔面板部署手册（MM 作战大屏）

**适用场景**：服务器只能通过宝塔面板（网页终端 / 文件管理 / Docker 管理）操作，不走 SSH。

> 目标服务器：`8.217.240.76`（香港）
> 已占端口：`3000 / 6060 / 8686 / 8787 / 8800 / 8801`
> MM 使用端口：`8900`（前端）+ `8901`（后端 REST+WS）

---

## 一、本地 → GitHub（仅首次）

### 1. 在 GitHub 创建空仓库

- 登录 [github.com/new](https://github.com/new)
- 仓库名：`MM`（或你喜欢的名字）
- 选 **Private**（自用项目）
- **不要** 勾选 "Add a README / .gitignore / license"（会冲突）
- 记下仓库地址：`git@github.com:你的用户名/MM.git`

### 2. 本机推送

```bash
cd ~/code/我的插件/MM

# 已初始化 + 首次 commit 完成，直接绑定远程并推送
git remote add origin git@github.com:你的用户名/MM.git

# 如果本机还没有配 GitHub SSH 密钥：
#   ssh-keygen -t ed25519 -C "your_email@example.com"
#   cat ~/.ssh/id_ed25519.pub  # 把公钥添加到 GitHub → Settings → SSH keys

git push -u origin main
```

---

## 二、宝塔面板 → 首次部署

### 1. 打开宝塔"终端"（左侧菜单 → 终端）

终端里执行：

```bash
# 准备目录（宝塔默认 /www/wwwroot/ 或 /root/）
mkdir -p /www/mm && cd /www/mm

# 首次 clone（HTTPS 方式，不需要配密钥）
git clone https://github.com/你的用户名/MM.git .

# 如果仓库是 Private，会提示输入 GitHub 用户名 + PAT（Personal Access Token）：
#   GitHub → Settings → Developer settings → Tokens (classic) → Generate
#   勾选 `repo` 权限即可

# 或用 SSH 方式（需要在服务器上 ssh-keygen 并把公钥加到 GitHub）：
#   git clone git@github.com:你的用户名/MM.git .
```

### 2. 填写部署环境变量

```bash
cd /www/mm
cp deploy/.env.example deploy/.env
vim deploy/.env
# 按需要填：
#   DEEPSEEK_API_KEY=sk-xxxx     # V1 可留空
#   MM_FRONTEND_PORT=8900        # 遇冲突改这里
#   MM_BACKEND_PORT=8901
```

保存退出 (`Esc → :wq`)。

### 3. 一键部署

```bash
cd /www/mm
./scripts/deploy.sh
```

首次会构建两个镜像（预计 3-5 分钟），完成后会自动做健康检查。成功输出：

```
✓ 后端健康
✓ 前端可访问: http://<server>:8900
部署完成
```

### 4. 浏览器访问

```
http://8.217.240.76:8900
```

正常看到"交易作战指挥大屏"说明成功。

---

## 三、宝塔面板 → 日常运维

### 在宝塔 Docker 面板

左侧 **Docker → 容器编排**（或直接在 **容器** 列表）能看到：
- `mm-frontend`（端口 8900）
- `mm-backend`（端口 8901）

点击容器右侧"日志"按钮可实时查看输出。

### 代码更新（一键）

终端里：

```bash
cd /www/mm
./scripts/deploy.sh
```

脚本会：
1. `git pull` 拉取最新代码
2. `docker compose build` 重建镜像
3. `docker compose up -d` 滚动更新
4. 20 秒后自动健康检查

### 仅重启（不拉代码）

```bash
cd /www/mm
./scripts/deploy.sh --no-pull
```

### 查看状态

```bash
cd /www/mm
./scripts/deploy.sh --status
```

### 手动看日志

```bash
docker compose -f /www/mm/deploy/docker-compose.yml logs -f mm-backend
docker compose -f /www/mm/deploy/docker-compose.yml logs -f mm-frontend
# 或在 MM 前端 → 日志面板，实时 WS 推送更方便
```

### 停止 / 重启

```bash
cd /www/mm/deploy
docker compose stop            # 只停不删
docker compose start           # 启回
docker compose restart         # 重启
docker compose down            # 停并删除（volume 保留，数据不丢）
```

---

## 四、数据备份

### 每日自动备份 SQLite

把 `scripts/backup-mm.sh` 复制到独立位置并加 cron：

```bash
mkdir -p /opt/mm-backup
cp /www/mm/scripts/backup-mm.sh /opt/mm-backup/
chmod +x /opt/mm-backup/backup-mm.sh

# 宝塔 → 计划任务 → 添加任务
#   任务类型：Shell 脚本
#   执行周期：每天 03:30
#   脚本内容：/opt/mm-backup/backup-mm.sh
#
# 或直接 crontab（终端里）：
echo "30 3 * * * /opt/mm-backup/backup-mm.sh >> /var/log/mm-backup.log 2>&1" | crontab -
```

备份文件位置（宿主）：

```
/var/lib/docker/volumes/mm-data/_data/backup/mm-YYYYMMDD-HHMM.sqlite
```

默认保留 30 天（可在脚本里改 `RETAIN_DAYS`）。

### 手动备份一次

```bash
/opt/mm-backup/backup-mm.sh
# 或直接导出 SQLite 文件：
docker cp mm-backend:/data/mm.sqlite ~/mm-$(date +%F).sqlite
```

### 恢复备份

```bash
# 1. 停后端
docker compose -f /www/mm/deploy/docker-compose.yml stop mm-backend

# 2. 把备份文件替换进 volume
docker run --rm -v mm-data:/data -v /path/to/backup:/src alpine \
  cp /src/mm-20260501.sqlite /data/mm.sqlite

# 3. 启后端
docker compose -f /www/mm/deploy/docker-compose.yml start mm-backend
```

---

## 五、常见问题

### 1. 端口被占怎么办

```bash
ss -tlnp | grep -E '890[01]'     # 看是谁占了
# 改 deploy/.env 里的 MM_FRONTEND_PORT / MM_BACKEND_PORT
# 再执行 ./scripts/deploy.sh --no-pull
```

### 2. git pull 冲突

```bash
cd /www/mm
git stash                        # 保存未 commit 的改动
git pull
git stash pop                    # 恢复（或丢弃: git stash drop）
```

### 3. 容器 unhealthy

```bash
docker compose -f /www/mm/deploy/docker-compose.yml logs --tail=100 mm-backend
# 常见原因：
#   - HFD Token 过期 → 采集 401（需查阅 HFD 账户）
#   - SQLite 文件权限 → 确认 volume 目录 rw
#   - 容器内存不足 → 宝塔 → Docker → 资源限制 调大
```

### 4. 前端 WS 提示"离线"（大屏底部红点）

排查顺序：
- 浏览器 F12 → Network → WS，看握手是否 101
- `/backend-health` 是否 200：`curl http://<server>:8900/backend-health`
- nginx 反代有无被防火墙拦截：`ufw status` / 云厂商安全组放行 8900

### 5. 想在宝塔加域名 + HTTPS

宝塔 → **网站 → 添加站点 → 反向代理**：
- 源站：`http://127.0.0.1:8900`
- 开启 WebSocket 支持（宝塔的反代模板里有勾选项）
- 一键申请 Let's Encrypt SSL

访问 `https://mm.你的域名.com`。

---

## 六、升级到 V1.1（AI 观察模式）

当 V1.1 合并后：

```bash
cd /www/mm
git pull
# 确认 deploy/.env 里 DEEPSEEK_API_KEY 已填
./scripts/deploy.sh --no-pull
```

V1.1 会新增 AI 观察面板、每日日终复盘等。

---

## 七、彻底卸载

```bash
cd /www/mm/deploy
docker compose down -v           # -v 会删除 volume，数据清零！请先备份
cd / && rm -rf /www/mm
```
