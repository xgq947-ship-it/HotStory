#!/usr/bin/env bash
# 生成自包含的 HotStory.app。
#
# 产物结构：
#   HotStory.app/Contents/MacOS/HotStory   启动器
#   HotStory.app/Contents/Resources/backend  后端源码
#   HotStory.app/Contents/Resources/webui    前端静态产物
#
# 运行时只需要 uv 或系统 Python 3.12+，不需要 Node。
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
APP_DIR="$ROOT_DIR/HotStory.app"
FRONTEND_DIR="$ROOT_DIR/frontend"
RESOURCES="$APP_DIR/Contents/Resources"

echo "→ 构建前端静态产物"
if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
  (cd "$FRONTEND_DIR" && npm install)
fi
(cd "$FRONTEND_DIR" && npm run build)
if [ ! -f "$FRONTEND_DIR/out/index.html" ]; then
  echo "前端静态导出失败：找不到 frontend/out/index.html" >&2
  exit 1
fi

echo "→ 组装应用包"
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR/Contents/MacOS" "$RESOURCES"

cp "$ROOT_DIR/scripts/hotstory-launcher.sh" "$APP_DIR/Contents/MacOS/HotStory"
cp "$ROOT_DIR/scripts/HotStory-Info.plist" "$APP_DIR/Contents/Info.plist"
chmod +x "$APP_DIR/Contents/MacOS/HotStory"

# 后端源码：排除虚拟环境、缓存和测试。
rsync -a \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude '.ruff_cache' \
  --exclude 'tests' \
  --exclude '.env' \
  "$ROOT_DIR/backend/" "$RESOURCES/backend/"

rsync -a --delete "$FRONTEND_DIR/out/" "$RESOURCES/webui/"

cp "$ROOT_DIR/.env.example" "$RESOURCES/.env.example"

SIZE=$(du -sh "$APP_DIR" | cut -f1)
echo "已生成：$APP_DIR（$SIZE）"
echo "双击 HotStory.app 即可启动；首次启动会在 ~/Library/Application Support/HotStory 下准备运行环境。"
