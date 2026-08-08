#!/usr/bin/env bash
set -euo pipefail

HOTSTORY_ROOT=$(cd "$(dirname "$0")/.." && pwd)

(
  cd "$HOTSTORY_ROOT/backend"
  .venv/bin/ruff check app tests
  .venv/bin/pytest
)

(
  cd "$HOTSTORY_ROOT/frontend"
  npm run typecheck
  npm run build
)

echo "HotStory checks passed."

