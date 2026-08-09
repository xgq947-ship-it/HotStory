#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ "$(basename "$SCRIPT_DIR")" = "MacOS" ] && [ "$(basename "$(dirname "$SCRIPT_DIR")")" = "Contents" ]; then
  ROOT_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"
else
  ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
fi
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
DATA_DIR="$ROOT_DIR/data"
LOG_FILE="$DATA_DIR/hotstory-app.log"
LOG_MAX_BYTES=$((10 * 1024 * 1024))
ARCH_STAMP="$DATA_DIR/.node-arch"
FRONTEND_URL="http://127.0.0.1:3000"
HEALTH_URL="http://127.0.0.1:8000/api/health"
MAX_WAIT_SECONDS=90
MAX_RESTARTS=1

export PATH="/usr/local/bin:/opt/homebrew/bin:${HOME}/.local/bin:${PATH:-/usr/bin:/bin:/usr/sbin:/sbin}"

mkdir -p "$DATA_DIR"

# 日志之前是无限增长的 append，出事时翻不动。启动时按大小滚一次，保留最近 3 份。
if [ -f "$LOG_FILE" ]; then
  log_size=$(wc -c <"$LOG_FILE" 2>/dev/null || echo 0)
  if [ "$log_size" -gt "$LOG_MAX_BYTES" ]; then
    rm -f "$LOG_FILE.3"
    [ -f "$LOG_FILE.2" ] && mv "$LOG_FILE.2" "$LOG_FILE.3"
    [ -f "$LOG_FILE.1" ] && mv "$LOG_FILE.1" "$LOG_FILE.2"
    mv "$LOG_FILE" "$LOG_FILE.1"
  fi
fi
exec >>"$LOG_FILE" 2>&1

timestamp() {
  date "+%Y-%m-%d %H:%M:%S"
}

log() {
  printf "[%s] %s\n" "$(timestamp)" "$*"
}

show_error() {
  local message="$1"
  log "ERROR: $message"
  if command -v osascript >/dev/null 2>&1; then
    osascript -e "display dialog \"$message\n\n日志：$LOG_FILE\" buttons {\"打开日志\", \"关闭\"} default button \"打开日志\" with title \"HotStory 启动失败\" with icon stop" >/dev/null 2>&1
    if [ "$?" -eq 0 ]; then
      open "$LOG_FILE" >/dev/null 2>&1 || true
    fi
  fi
}

service_ready() {
  curl --silent --show-error --fail --max-time 2 "$1" >/dev/null 2>&1
}

# Apple Silicon 上必须固定用 arm64 跑 node，否则 npm install 会装出
# x64 的原生模块（曾经复现：Cannot find module '../lightningcss.darwin-x64.node'）。
host_arch() {
  if [ "$(/usr/sbin/sysctl -n hw.optional.arm64 2>/dev/null || true)" = "1" ]; then
    echo "arm64"
  else
    echo "x86_64"
  fi
}

HOST_ARCH="$(host_arch)"

run_node() {
  if [ "$HOST_ARCH" = "arm64" ]; then
    /usr/bin/arch -arm64 "$@"
  else
    "$@"
  fi
}

cleanup() {
  local exit_code="${1:-0}"
  trap - EXIT INT TERM

  for service_pid in "${BACKEND_PID:-}" "${FRONTEND_PID:-}"; do
    if [ -n "$service_pid" ] && kill -0 "$service_pid" 2>/dev/null; then
      log "正在停止 HotStory 服务（PID ${service_pid}）"
      kill "$service_pid" 2>/dev/null || true
    fi
  done

  [ -z "${BACKEND_PID:-}" ] || wait "$BACKEND_PID" 2>/dev/null || true
  [ -z "${FRONTEND_PID:-}" ] || wait "$FRONTEND_PID" 2>/dev/null || true

  log "HotStory 已退出（状态 ${exit_code}）"
  exit "$exit_code"
}

trap 'cleanup "$?"' EXIT INT TERM

frontend_ready=0
backend_ready=0
service_ready "$FRONTEND_URL" && frontend_ready=1
service_ready "$HEALTH_URL" && backend_ready=1

if [ "$frontend_ready" -eq 1 ] && [ "$backend_ready" -eq 1 ]; then
  log "检测到 HotStory 已在运行，直接打开页面"
  open "$FRONTEND_URL" >/dev/null 2>&1 || true
  exit 0
fi

if [ "$frontend_ready" -eq 1 ] || [ "$backend_ready" -eq 1 ]; then
  show_error "检测到 3000 或 8000 端口已有服务，但 HotStory 前后端状态不完整。请先关闭占用端口的服务。"
  exit 1
fi

if [ ! -f "$ROOT_DIR/.env" ]; then
  cp "$ROOT_DIR/.env.example" "$ROOT_DIR/.env"
  chmod 600 "$ROOT_DIR/.env"
  show_error "已创建 .env，请配置 LLM Provider 后再次双击启动。"
  exit 1
fi

if [ ! -x "$BACKEND_DIR/.venv/bin/python" ]; then
  UV_BIN=$(command -v uv || true)
  if [ -z "$UV_BIN" ]; then
    show_error "缺少 uv，请先在终端运行：brew install uv"
    exit 1
  fi
  log "首次运行：创建 Python 环境并安装后端依赖"
  "$UV_BIN" venv "$BACKEND_DIR/.venv" --python 3.12 || {
    show_error "Python 虚拟环境创建失败，请查看日志。"
    exit 1
  }
  "$UV_BIN" pip install --python "$BACKEND_DIR/.venv/bin/python" -r "$BACKEND_DIR/requirements.txt" || {
    show_error "后端依赖安装失败，请查看日志。"
    exit 1
  }
fi

NPM_BIN=$(command -v npm || true)
NODE_BIN=$(command -v node || true)
if [ -z "$NPM_BIN" ] || [ -z "$NODE_BIN" ]; then
  show_error "缺少 Node.js 或 npm，请先安装 Node.js 20 以上版本。"
  exit 1
fi

NODE_ARCH=$(run_node "$NODE_BIN" -p process.arch 2>/dev/null || echo unknown)
RECORDED_ARCH=$(cat "$ARCH_STAMP" 2>/dev/null || echo "")
if [ -d "$FRONTEND_DIR/node_modules" ] && [ "$RECORDED_ARCH" != "$NODE_ARCH" ]; then
  log "node_modules 架构（${RECORDED_ARCH:-未知}）与当前 node（${NODE_ARCH}）不一致，重新安装前端依赖"
  rm -rf "$FRONTEND_DIR/node_modules"
fi

install_frontend_deps() {
  log "安装前端依赖（arch=${NODE_ARCH}）"
  (cd "$FRONTEND_DIR" && run_node "$NPM_BIN" install) || return 1
  printf "%s" "$NODE_ARCH" >"$ARCH_STAMP"
}

if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
  install_frontend_deps || {
    show_error "前端依赖安装失败，请查看日志。"
    exit 1
  }
fi

PYTHON_BIN="$BACKEND_DIR/.venv/bin/python"
NEXT_BIN="$FRONTEND_DIR/node_modules/next/dist/bin/next"
if [ ! -f "$NEXT_BIN" ]; then
  show_error "Next.js 启动文件不存在，请删除 frontend/node_modules 后重新启动。"
  exit 1
fi

# 生产构建：以前双击版跑的是 next dev（按需编译、每次导航重编译、内存 2-3 倍）。
BUILD_STAMP="$FRONTEND_DIR/.next/BUILD_ID"
if [ -f "$BUILD_STAMP" ]; then
  stale=$(find "$FRONTEND_DIR" -newer "$BUILD_STAMP" \
    -not -path "*/node_modules/*" -not -path "*/.next/*" -type f -print -quit 2>/dev/null)
  if [ -n "$stale" ]; then
    log "前端源码比生产包新（${stale}），重新构建"
    rm -f "$BUILD_STAMP"
  fi
fi
if [ ! -f "$BUILD_STAMP" ]; then
  log "构建前端生产包"
  if ! (cd "$FRONTEND_DIR" && run_node "$NPM_BIN" run build); then
    log "生产构建失败，尝试重装依赖后重试"
    rm -rf "$FRONTEND_DIR/node_modules"
    install_frontend_deps && (cd "$FRONTEND_DIR" && run_node "$NPM_BIN" run build)
  fi
fi
if [ ! -f "$BUILD_STAMP" ]; then
  show_error "前端生产构建失败，请查看日志。"
  exit 1
fi

start_services() {
  (
    cd "$BACKEND_DIR"
    exec "$PYTHON_BIN" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
  ) &
  BACKEND_PID=$!

  (
    cd "$FRONTEND_DIR"
    if [ "$HOST_ARCH" = "arm64" ]; then
      exec /usr/bin/arch -arm64 "$NODE_BIN" "$NEXT_BIN" start --hostname 127.0.0.1 --port 3000
    fi
    exec "$NODE_BIN" "$NEXT_BIN" start --hostname 127.0.0.1 --port 3000
  ) &
  FRONTEND_PID=$!
}

wait_ready() {
  local second
  for ((second = 1; second <= MAX_WAIT_SECONDS; second++)); do
    if ! kill -0 "$BACKEND_PID" 2>/dev/null || ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
      return 1
    fi
    if service_ready "$FRONTEND_URL" && service_ready "$HEALTH_URL"; then
      return 0
    fi
    sleep 1
  done
  return 2
}

stop_services() {
  for service_pid in "${BACKEND_PID:-}" "${FRONTEND_PID:-}"; do
    if [ -n "$service_pid" ] && kill -0 "$service_pid" 2>/dev/null; then
      kill "$service_pid" 2>/dev/null || true
    fi
  done
  [ -z "${BACKEND_PID:-}" ] || wait "$BACKEND_PID" 2>/dev/null || true
  [ -z "${FRONTEND_PID:-}" ] || wait "$FRONTEND_PID" 2>/dev/null || true
  BACKEND_PID=""
  FRONTEND_PID=""
}

restarts=0
while true; do
  log "启动 HotStory 后端和前端"
  start_services
  if ! wait_ready; then
    stop_services
    if [ "$restarts" -lt "$MAX_RESTARTS" ]; then
      restarts=$((restarts + 1))
      log "启动未就绪，自动重试第 ${restarts} 次"
      sleep 2
      continue
    fi
    show_error "HotStory 服务启动失败，请查看日志。"
    exit 1
  fi

  log "HotStory 已就绪，打开 ${FRONTEND_URL}"
  open "$FRONTEND_URL" >/dev/null 2>&1 || true
  while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
    sleep 2
  done

  stop_services
  if [ "$restarts" -lt "$MAX_RESTARTS" ]; then
    restarts=$((restarts + 1))
    log "服务意外退出，自动重启第 ${restarts} 次"
    sleep 2
    continue
  fi
  show_error "HotStory 服务意外退出，请查看日志。"
  exit 1
done
