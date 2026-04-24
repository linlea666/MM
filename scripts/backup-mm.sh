#!/usr/bin/env bash
# MM SQLite 每日备份脚本
# 放到服务器任意位置，建议 /opt/mm-backup/backup-mm.sh，并用 cron 每日执行一次。
#
# 用法：
#   bash backup-mm.sh                   # 使用默认配置
#   BACKUP_DIR=/path/to/backup bash backup-mm.sh
#
# cron 示例（每日 03:30 执行）：
#   30 3 * * * /opt/mm-backup/backup-mm.sh >> /var/log/mm-backup.log 2>&1
#
# 原理：在容器内 sqlite3 ".backup" 到 /data/backup/mm-YYYYMMDD.sqlite，
#       然后把 docker volume 里的文件 cp 出来保留；30 天前的旧备份自动删。

set -euo pipefail

CONTAINER="${CONTAINER:-mm-backend}"
DATE=$(date +%Y%m%d-%H%M)
DB_INSIDE="/data/mm.sqlite"
BACKUP_INSIDE="/data/backup"
BACKUP_HOST="${BACKUP_DIR:-/var/lib/docker/volumes/mm-data/_data/backup}"
RETAIN_DAYS="${RETAIN_DAYS:-30}"

log() { echo "[$(date '+%F %T')] $*"; }

if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
  log "ERROR: 容器 ${CONTAINER} 未运行"; exit 1
fi

log "备份开始 (container=${CONTAINER})"

# 1) 容器内 SQLite online backup（安全，不阻塞业务）
docker exec "${CONTAINER}" sh -c "mkdir -p ${BACKUP_INSIDE} && \
  python -c 'import sqlite3,sys; \
src=sqlite3.connect(\"${DB_INSIDE}\"); \
dst=sqlite3.connect(\"${BACKUP_INSIDE}/mm-${DATE}.sqlite\"); \
src.backup(dst); dst.close(); src.close(); print(\"ok\")'"

# 2) 宿主侧权限和保留策略
if [[ -d "${BACKUP_HOST}" ]]; then
  log "清理 ${RETAIN_DAYS} 天前的旧备份: ${BACKUP_HOST}"
  find "${BACKUP_HOST}" -maxdepth 1 -name 'mm-*.sqlite' -type f -mtime +${RETAIN_DAYS} -print -delete || true
fi

# 3) 输出结果
SIZE=$(docker exec "${CONTAINER}" du -h "${BACKUP_INSIDE}/mm-${DATE}.sqlite" | awk '{print $1}')
log "备份完成: mm-${DATE}.sqlite (${SIZE})"
