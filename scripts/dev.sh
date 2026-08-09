#!/usr/bin/env bash
set -euo pipefail

HOTSTORY_ROOT=$(cd "$(dirname "$0")/.." && pwd)
BACKEND_DIR="$HOTSTORY_ROOT/backend"
FRONTEND_DIR="$HOTSTORY_ROOT/frontend"

if ! command -v uv >/dev/null 2>&1; then
  echo "缺少 uv。请先运行：brew install uv" >&2
  exit 1
fi

if [ ! -f "$HOTSTORY_ROOT/.env" ]; then
  cp "$HOTSTORY_ROOT/.env.example" "$HOTSTORY_ROOT/.env"
  chmod 600 "$HOTSTORY_ROOT/.env"
  echo "已创建 .env，请配置 LLM Provider 后重新运行。" >&2
  exit 1
fi

if [ ! -x "$BACKEND_DIR/.venv/bin/python" ]; then
  uv venv "$BACKEND_DIR/.venv" --python 3.12
  uv pip install --python "$BACKEND_DIR/.venv/bin/python" -r "$BACKEND_DIR/requirements.txt"
fi

if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
  (cd "$FRONTEND_DIR" && npm install)
fi

backend_pid=""
frontend_pid=""

cleanup() {
  trap - EXIT INT TERM
  if [ -n "$backend_pid" ] && kill -0 "$backend_pid" 2>/dev/null; then
    kill "$backend_pid" 2>/dev/null || true
  fi
  if [ -n "$frontend_pid" ] && kill -0 "$frontend_pid" 2>/dev/null; then
    kill "$frontend_pid" 2>/dev/null || true
  fi
  wait 2>/dev/null || true
}

trap cleanup EXIT INT TERM

echo "HotStory API: http://127.0.0.1:8000"
echo "HotStory UI:  http://127.0.0.1:3000"

(
  cd "$BACKEND_DIR"
  exec .venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
) &
backend_pid=$!

(
  cd "$FRONTEND_DIR"
  # 打包后前后端同源，api.ts 默认走相对路径；开发时两个端口，必须显式指向后端。
  export NEXT_PUBLIC_API_BASE_URL="http://127.0.0.1:8000/api"
  exec npm run dev -- --hostname 127.0.0.1 --port 3000
) &
frontend_pid=$!

wait "$backend_pid" "$frontend_pid"

