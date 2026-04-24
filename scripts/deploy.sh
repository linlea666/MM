#!/usr/bin/env bash
# MM 一键部署 / 更新脚本（服务器侧）
# 用法：
#   ./scripts/deploy.sh          # 拉取最新代码并重新构建
#   ./scripts/deploy.sh --no-pull    # 不拉代码，仅 rebuild & restart
#   ./scripts/deploy.sh --status     # 只查看状态

set -euo pipefail

cd "$(dirname "$0")/.."

NO_PULL=0
STATUS=0
for arg in "$@"; do
  case "$arg" in
    --no-pull) NO_PULL=1 ;;
    --status)  STATUS=1  ;;
    -h|--help)
      sed -n '2,8p' "$0"; exit 0 ;;
  esac
done

log() { echo -e "\033[36m[$(date '+%F %T')] $*\033[0m"; }
err() { echo -e "\033[31m[$(date '+%F %T')] $*\033[0m" >&2; }

if [[ "$STATUS" == "1" ]]; then
  log "容器状态"
  docker compose -f deploy/docker-compose.yml ps
  log "最近 50 行后端日志"
  docker compose -f deploy/docker-compose.yml logs --tail=50 mm-backend || true
  exit 0
fi

if [[ ! -f deploy/.env ]]; then
  err "缺少 deploy/.env，先执行: cp deploy/.env.example deploy/.env && vim deploy/.env"
  exit 1
fi

if [[ "$NO_PULL" == "0" ]]; then
  log "拉取最新代码"
  git pull --ff-only
fi

log "构建镜像（首次可能 3-5 分钟）"
docker compose -f deploy/docker-compose.yml build

log "启动 / 更新容器"
docker compose -f deploy/docker-compose.yml up -d

log "等待 20s 后做健康检查"
sleep 20

log "容器状态"
docker compose -f deploy/docker-compose.yml ps

BACKEND_PORT=$(grep -E '^MM_BACKEND_PORT=' deploy/.env 2>/dev/null | cut -d= -f2)
BACKEND_PORT=${BACKEND_PORT:-8901}
FRONTEND_PORT=$(grep -E '^MM_FRONTEND_PORT=' deploy/.env 2>/dev/null | cut -d= -f2)
FRONTEND_PORT=${FRONTEND_PORT:-8900}

log "Backend /health"
if curl -fsS "http://127.0.0.1:${BACKEND_PORT}/health" | head -c 500; then
  echo
  log "✓ 后端健康"
else
  err "✗ 后端健康检查失败，查看 docker compose logs mm-backend"
  exit 2
fi

log "Frontend /"
if curl -fsS -o /dev/null -w "HTTP %{http_code}\n" "http://127.0.0.1:${FRONTEND_PORT}/"; then
  log "✓ 前端可访问: http://<server>:${FRONTEND_PORT}"
else
  err "✗ 前端检查失败，查看 docker compose logs mm-frontend"
  exit 3
fi

log "部署完成"
