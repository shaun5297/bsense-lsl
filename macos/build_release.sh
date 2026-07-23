#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ "$(uname -m)" != "arm64" ]]; then
  echo "错误：macOS 发行版必须在 Apple Silicon (arm64) 环境构建。" >&2
  exit 1
fi

if [[ ! -x ".venv/bin/python" ]]; then
  echo "错误：未找到 .venv。请先运行 bash macos/setup.sh。" >&2
  exit 1
fi

.venv/bin/python -m pip install -e ".[release]"
.venv/bin/python tools/build_release.py "$@"
