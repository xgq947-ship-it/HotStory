#!/usr/bin/env bash
set -euo pipefail

HOTSTORY_ROOT=$(cd "$(dirname "$0")/.." && pwd)
DATA_DIR="$HOTSTORY_ROOT/data"

if [ "${1:-}" != "--yes" ]; then
  echo "这会把数据库和研究档案移动到 data/trash/。确认后运行：" >&2
  echo "./scripts/reset_db.sh --yes" >&2
  exit 1
fi

if [ ! -f "$HOTSTORY_ROOT/README.md" ] || [ ! -d "$DATA_DIR" ]; then
  echo "拒绝执行：无法确认 HotStory 项目目录。" >&2
  exit 1
fi

timestamp=$(date +%Y%m%d-%H%M%S)
archive_dir="$DATA_DIR/trash/$timestamp"
mkdir -p "$archive_dir"

for database_file in "$DATA_DIR/hotstory.db" "$DATA_DIR/hotstory.db-shm" "$DATA_DIR/hotstory.db-wal"; do
  if [ -f "$database_file" ]; then
    mv "$database_file" "$archive_dir/"
  fi
done

if [ -d "$DATA_DIR/projects" ]; then
  mkdir -p "$archive_dir/projects"
  find "$DATA_DIR/projects" -mindepth 1 -maxdepth 1 -type d -exec mv {} "$archive_dir/projects/" \;
fi

mkdir -p "$DATA_DIR/projects"
touch "$DATA_DIR/projects/.gitkeep"
echo "旧数据已移动到：$archive_dir"

