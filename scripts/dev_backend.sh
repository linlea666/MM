#!/usr/bin/env bash
# 开发模式启动 backend，自动 reload。

set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -d backend/.venv ]; then
    echo "▶ 创建虚拟环境 backend/.venv"
    python3.11 -m venv backend/.venv
fi

# shellcheck disable=SC1091
source backend/.venv/bin/activate

pip install -q -r backend/requirements.txt -r backend/requirements-dev.txt

cd backend
PYTHONPATH=.. uvicorn backend.main:app --reload --host 0.0.0.0 --port "${MM_PORT:-8901}"
