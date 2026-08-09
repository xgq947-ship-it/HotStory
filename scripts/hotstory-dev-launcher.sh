#!/usr/bin/env bash
# Finder 双击入口：从当前项目源码启动 Tauri 调试窗口。
set -u

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_DIR=$(cd "$SCRIPT_DIR/../../.." && pwd)
LOG_FILE="$PROJECT_DIR/data/hotstory-dev-app.log"
LOG_MAX_BYTES=$((10 * 1024 * 1024))
DEBUG_BIN="$PROJECT_DIR/src-tauri/target/debug/hotstory"

export PATH="/opt/homebrew/bin:/usr/local/bin:${HOME}/.cargo/bin:${PROJECT_DIR}/node_modules/.bin:${PATH:-/usr/bin:/bin:/usr/sbin:/sbin}"

mkdir -p "$PROJECT_DIR/data"
if [ -f "$LOG_FILE" ]; then
  log_size=$(wc -c <"$LOG_FILE" 2>/dev/null || echo 0)
  if [ "$log_size" -gt "$LOG_MAX_BYTES" ]; then
    mv "$LOG_FILE" "$LOG_FILE.1"
  fi
fi
exec >>"$LOG_FILE" 2>&1

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

show_error() {
  local message="$1"
  local dialog_result
  log "ERROR: $message"
  dialog_result=$(osascript -e "display dialog \"$message\\n\\n日志：$LOG_FILE\" buttons {\"打开日志\", \"关闭\"} default button \"打开日志\" with title \"HotStory 调试启动失败\" with icon stop" 2>/dev/null || true)
  if [[ "$dialog_result" == *"button returned:打开日志"* ]]; then
    open "$LOG_FILE" >/dev/null 2>&1 || true
  fi
}

existing_pid=""
for candidate_pid in $(pgrep -x hotstory 2>/dev/null || true); do
  executable_path=$(lsof -a -p "$candidate_pid" -d txt -Fn 2>/dev/null | sed -n 's/^n//p' | head -1)
  if [ "$executable_path" = "$DEBUG_BIN" ]; then
    existing_pid="$candidate_pid"
    break
  fi
done
if [ -n "$existing_pid" ] && kill -0 "$existing_pid" 2>/dev/null; then
  log "HotStory 调试窗口已运行（PID ${existing_pid}），切换到前台"
  osascript \
    -e 'tell application "System Events"' \
    -e "set matches to every application process whose unix id is ${existing_pid}" \
    -e 'if (count of matches) > 0 then set frontmost of item 1 of matches to true' \
    -e 'end tell' >/dev/null 2>&1 || true
  exit 0
fi

for required_command in node npm cargo; do
  if ! command -v "$required_command" >/dev/null 2>&1; then
    show_error "缺少调试依赖：${required_command}。"
    exit 1
  fi
done

if [ ! -f "$PROJECT_DIR/package.json" ]; then
  show_error "找不到 HotStory 项目源码：$PROJECT_DIR"
  exit 1
fi

cd "$PROJECT_DIR" || exit 1
if [ ! -x "$PROJECT_DIR/node_modules/.bin/tauri" ]; then
  log "首次启动：安装桌面端开发依赖"
  if ! npm install; then
    show_error "npm 依赖安装失败。"
    exit 1
  fi
fi
if [ ! -x "$PROJECT_DIR/frontend/node_modules/.bin/next" ]; then
  log "首次启动：安装界面开发依赖"
  if ! (cd "$PROJECT_DIR/frontend" && npm install); then
    show_error "界面依赖安装失败。"
    exit 1
  fi
fi

log "从当前源码启动 HotStory Tauri 调试窗口"
npm run desktop:dev
status=$?
case "$status" in
  0|130|143)
    log "HotStory 调试进程已正常结束（状态 ${status}）"
    exit 0
    ;;
  *)
    log "HotStory 调试进程异常退出（状态 ${status}）"
    show_error "HotStory 调试窗口启动失败，请查看日志。"
    exit "$status"
    ;;
esac
