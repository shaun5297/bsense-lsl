#!/bin/zsh
set -eu

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$PROJECT_ROOT/.venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
  echo "[错误] 未找到 macOS 虚拟环境，请先运行：bash \"$PROJECT_ROOT/macos/setup.sh\""
  exit 1
fi

cd "$PROJECT_ROOT"
exec "$PYTHON" -m bsense_experiment "$@"
