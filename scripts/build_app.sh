#!/usr/bin/env bash
# 生成项目内的 HotStory 调试启动器；它不安装应用，也不构建 DMG。
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
APP_DIR="$ROOT_DIR/HotStory.app"
ICON_SOURCE="$ROOT_DIR/src-tauri/icons/icon.icns"
STAGING_DIR=""

cleanup() {
  if [ -n "$STAGING_DIR" ] && [ -d "$STAGING_DIR" ]; then
    rm -rf "$STAGING_DIR"
  fi
}
trap cleanup EXIT INT TERM

if [ "$(uname -s)" != "Darwin" ]; then
  echo "scripts/build_app.sh 只负责生成 macOS 调试启动器。" >&2
  exit 1
fi

if [ ! -f "$ICON_SOURCE" ]; then
  echo "→ 生成应用图标"
  (cd "$ROOT_DIR" && npm run runtime:icons >/dev/null)
fi

echo "→ 生成项目内 Tauri 调试启动器"
STAGING_DIR=$(mktemp -d "$ROOT_DIR/.hotstory-app-build.XXXXXX")
STAGED_APP="$STAGING_DIR/HotStory.app"
mkdir -p "$STAGED_APP/Contents/MacOS" "$STAGED_APP/Contents/Resources"

cp "$ROOT_DIR/scripts/hotstory-dev-launcher.sh" "$STAGED_APP/Contents/MacOS/HotStory"
cp "$ROOT_DIR/scripts/HotStory-Info.plist" "$STAGED_APP/Contents/Info.plist"
cp "$ICON_SOURCE" "$STAGED_APP/Contents/Resources/HotStory.icns"
chmod +x "$STAGED_APP/Contents/MacOS/HotStory"

plutil -lint "$STAGED_APP/Contents/Info.plist" >/dev/null
test -x "$STAGED_APP/Contents/MacOS/HotStory"

# 先完成临时包，再替换旧启动器，避免中断后留下残缺 .app。
PREVIOUS_APP="$STAGING_DIR/HotStory.previous.app"
if [ -e "$APP_DIR" ]; then
  mv "$APP_DIR" "$PREVIOUS_APP"
fi
if ! mv "$STAGED_APP" "$APP_DIR"; then
  if [ -e "$PREVIOUS_APP" ]; then
    mv "$PREVIOUS_APP" "$APP_DIR"
  fi
  echo "替换 HotStory.app 失败，已恢复原启动器。" >&2
  exit 1
fi

if command -v codesign >/dev/null 2>&1; then
  codesign --force --deep --sign - "$APP_DIR" >/dev/null
fi

echo "已生成：$APP_DIR"
echo "双击后会运行当前项目源码并打开 Tauri 应用窗口，不会安装应用或打开浏览器。"
