#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
APP_DIR="$ROOT_DIR/HotStory.app"
FRONTEND_DIR="$ROOT_DIR/frontend"

# 双击版跑的是 next start，需要先有生产构建；不预构建的话首次启动要等一次完整 build。
if [ -d "$FRONTEND_DIR/node_modules" ]; then
  echo "构建前端生产包…"
  (cd "$FRONTEND_DIR" && npm run build)
else
  echo "跳过前端构建：frontend/node_modules 不存在，首次启动时由启动器安装并构建。" >&2
fi

mkdir -p "$APP_DIR/Contents/MacOS" "$APP_DIR/Contents/Resources"
cp "$ROOT_DIR/scripts/hotstory-launcher.sh" "$APP_DIR/Contents/MacOS/HotStory"
cp "$ROOT_DIR/scripts/HotStory-Info.plist" "$APP_DIR/Contents/Info.plist"
chmod +x "$APP_DIR/Contents/MacOS/HotStory"

echo "已生成：$APP_DIR"
echo "双击 HotStory.app 即可启动。"
