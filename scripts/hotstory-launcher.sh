#!/usr/bin/env bash
# HotStory.app 的启动器。
#
# 打包后的应用是自包含的：Contents/Resources 里有后端源码和前端静态产物，
# 首次启动在 ~/Library/Application Support/HotStory 下建一个 Python 环境，
# 之后每次启动只拉起一个进程（FastAPI 同时提供 API 和界面，不需要 Node）。
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$(basename "$SCRIPT_DIR")" = "MacOS" ] && [ "$(basename "$(dirname "$SCRIPT_DIR")")" = "Contents" ]; then
  BUNDLED=1
  ROOT_DIR="$(cd "$SCRIPT_DIR/../Resources" && pwd)"
  SUPPORT_DIR="$HOME/Library/Application Support/HotStory"
else
  # 从源码目录直接运行（未打包）
  BUNDLED=0
  ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
  SUPPORT_DIR="$ROOT_DIR"
fi

BACKEND_DIR="$ROOT_DIR/backend"
DATA_DIR="$SUPPORT_DIR/data"
VENV_DIR="$SUPPORT_DIR/venv"
LOG_FILE="$DATA_DIR/hotstory-app.log"
LOG_MAX_BYTES=$((10 * 1024 * 1024))
PORT="${HOTSTORY_PORT:-8000}"
APP_URL="http://127.0.0.1:${PORT}"
HEALTH_URL="${APP_URL}/api/health"
MAX_WAIT_SECONDS=120
MAX_RESTARTS=1
REQUIREMENTS="$BACKEND_DIR/requirements.txt"
STAMP_FILE="$SUPPORT_DIR/.deps-stamp"

export PATH="/usr/local/bin:/opt/homebrew/bin:${HOME}/.local/bin:${PATH:-/usr/bin:/bin:/usr/sbin:/sbin}"

mkdir -p "$DATA_DIR"

# 日志按大小滚动，保留最近 3 份。
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

log() {
  printf "[%s] %s\n" "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
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
  curl --silent --fail --max-time 2 "$HEALTH_URL" >/dev/null 2>&1
}

cleanup() {
  local exit_code="${1:-0}"
  trap - EXIT INT TERM
  if [ -n "${SERVER_PID:-}" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
    log "正在停止 HotStory（PID ${SERVER_PID}）"
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  log "HotStory 已退出（状态 ${exit_code}）"
  exit "$exit_code"
}

trap 'cleanup "$?"' EXIT INT TERM

if service_ready; then
  log "检测到 HotStory 已在运行，直接打开页面"
  open "$APP_URL" >/dev/null 2>&1 || true
  exit 0
fi

if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  show_error "端口 ${PORT} 已被其他程序占用。请关闭它，或设置环境变量 HOTSTORY_PORT 换一个端口。"
  exit 1
fi

# —— Python 环境 ——
PYTHON_BIN="$VENV_DIR/bin/python"

create_environment() {
  local uv_bin
  uv_bin=$(command -v uv || true)
  if [ -n "$uv_bin" ]; then
    log "使用 uv 创建 Python 环境（必要时会自动下载 Python 3.12）"
    "$uv_bin" venv "$VENV_DIR" --python 3.12 && return 0
    log "uv 创建环境失败，尝试系统 Python"
  fi
  local candidate
  for candidate in python3.13 python3.12 python3; do
    local found
    found=$(command -v "$candidate" || true)
    [ -z "$found" ] && continue
    if "$found" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
      log "使用 $found 创建 Python 环境"
      "$found" -m venv "$VENV_DIR" && return 0
    fi
  done
  return 1
}

install_dependencies() {
  local uv_bin
  uv_bin=$(command -v uv || true)
  if [ -n "$uv_bin" ]; then
    "$uv_bin" pip install --python "$PYTHON_BIN" -r "$REQUIREMENTS" && return 0
    log "uv 安装依赖失败，改用 pip"
  fi
  "$PYTHON_BIN" -m pip install --upgrade pip >/dev/null 2>&1 || true
  "$PYTHON_BIN" -m pip install -r "$REQUIREMENTS"
}

if [ ! -x "$PYTHON_BIN" ]; then
  log "首次启动：准备运行环境（这一步只做一次，可能需要几分钟）"
  if ! create_environment; then
    show_error "没有可用的 Python 3.12+。请安装 uv（brew install uv）或 Python 3.12 后重试。"
    exit 1
  fi
fi

# requirements 变了就重装，避免升级后跑在旧依赖上。
REQ_HASH=$(shasum -a 256 "$REQUIREMENTS" 2>/dev/null | cut -d' ' -f1)
if [ "$(cat "$STAMP_FILE" 2>/dev/null || echo '')" != "$REQ_HASH" ]; then
  log "安装/更新后端依赖"
  if ! install_dependencies; then
    show_error "后端依赖安装失败，请查看日志。"
    exit 1
  fi
  printf "%s" "$REQ_HASH" >"$STAMP_FILE"
fi

if [ ! -f "$ROOT_DIR/webui/index.html" ] && [ ! -f "$ROOT_DIR/frontend/out/index.html" ]; then
  show_error "缺少前端界面文件。请重新运行 scripts/build_app.sh 生成应用。"
  exit 1
fi

export DATA_DIR
export DATABASE_URL="${DATABASE_URL:-sqlite:///$DATA_DIR/hotstory.db}"
# 打包后配置写在应用支持目录，不写进 .app 内部（否则移动或覆盖安装就丢了）。
if [ "$BUNDLED" -eq 1 ] && [ -f "$SUPPORT_DIR/.env" ]; then
  export ENV_FILE="$SUPPORT_DIR/.env"
fi

start_server() {
  (
    cd "$BACKEND_DIR"
    exec "$PYTHON_BIN" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
  ) &
  SERVER_PID=$!
}

wait_ready() {
  local second
  for ((second = 1; second <= MAX_WAIT_SECONDS; second++)); do
    kill -0 "$SERVER_PID" 2>/dev/null || return 1
    service_ready && return 0
    sleep 1
  done
  return 2
}

restarts=0
while true; do
  log "启动 HotStory（端口 ${PORT}，单进程）"
  start_server
  if ! wait_ready; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
    SERVER_PID=""
    if [ "$restarts" -lt "$MAX_RESTARTS" ]; then
      restarts=$((restarts + 1))
      log "启动未就绪，自动重试第 ${restarts} 次"
      sleep 2
      continue
    fi
    show_error "HotStory 启动失败，请查看日志。"
    exit 1
  fi

  log "HotStory 已就绪，打开 ${APP_URL}"
  open "$APP_URL" >/dev/null 2>&1 || true
  wait "$SERVER_PID"
  SERVER_PID=""

  if [ "$restarts" -lt "$MAX_RESTARTS" ]; then
    restarts=$((restarts + 1))
    log "服务意外退出，自动重启第 ${restarts} 次"
    sleep 2
    continue
  fi
  show_error "HotStory 意外退出，请查看日志。"
  exit 1
done
