#!/bin/zsh
set -eu

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$PROJECT_ROOT/.venv"

has_usable_python() {
  "$1" -c 'import sys, tkinter; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 14) else 1)' >/dev/null 2>&1
}

find_python() {
  if [[ -n "${BSENSE_PYTHON:-}" ]]; then
    candidates=("$BSENSE_PYTHON")
  else
    candidates=(python3.13 python3.12 python3.11 python3)
  fi

  for candidate in "${candidates[@]}"; do
    if ! command -v "$candidate" >/dev/null 2>&1; then
      continue
    fi
    executable="$(command -v "$candidate")"
    if has_usable_python "$executable"; then
      echo "$executable"
      return 0
    fi
  done
  return 1
}

if ! PYTHON="$(find_python)"; then
  echo "[错误] 需要带 Tk 的 Python 3.11-3.13，本脚本不自动下载安装。"
  echo "可任选一种方式后重试："
  echo "  1. 使用 Homebrew 安装：brew install python@3.13 python-tk@3.13"
  echo "  2. 已有其他兼容解释器时指定：BSENSE_PYTHON=/path/to/python3.12 bash \"$0\""
  exit 1
fi

if [[ -e "$VENV" && ! -x "$VENV/bin/python" ]]; then
  backup="$VENV.bak.$(date +%Y%m%d%H%M%S)"
  echo "[提示] $VENV 来自其他系统或不完整，已移动到 $backup 并重新创建。"
  mv "$VENV" "$backup"
fi

if [[ -x "$VENV/bin/python" ]] && ! has_usable_python "$VENV/bin/python"; then
  backup="$VENV.bak.$(date +%Y%m%d%H%M%S)"
  echo "[提示] $VENV 不是有效的 macOS Python 3.11-3.13 Tk 环境，已移动到 $backup 并重新创建。"
  mv "$VENV" "$backup"
fi

if [[ ! -x "$VENV/bin/python" ]]; then
  "$PYTHON" -m venv "$VENV"
fi

if ! has_usable_python "$VENV/bin/python"; then
  echo "[错误] $VENV 创建失败或仍不是有效的 Python 3.11-3.13 Tk 环境。"
  exit 1
fi

"$VENV/bin/python" -m pip install -e "$PROJECT_ROOT"
"$VENV/bin/python" -m bsense_experiment --self-test
"$VENV/bin/python" -m unittest discover -s "$PROJECT_ROOT/tests" -v

echo "[完成] macOS 环境已就绪：$VENV"
echo "运行实验：bash \"$PROJECT_ROOT/macos/run.sh\""
