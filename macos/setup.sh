#!/bin/zsh
set -eu

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$PROJECT_ROOT/.venv"

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
    if "$executable" -c 'import sys, tkinter; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 14) else 1)' >/dev/null 2>&1; then
      echo "$executable"
      return 0
    fi
  done
  return 1
}

if ! PYTHON="$(find_python)"; then
  echo "[错误] 需要带 Tk 的 Python 3.11-3.13。"
  echo "可使用 Homebrew 安装 Python 3.13 与对应的 Tk，或通过 BSENSE_PYTHON 指定解释器。"
  exit 1
fi

if [[ -e "$VENV/pyvenv.cfg" && ! -x "$VENV/bin/python" ]]; then
  echo "[错误] $VENV 来自其他系统或不完整。请先将它重命名，再重新运行本脚本。"
  exit 1
fi

if [[ ! -x "$VENV/bin/python" ]]; then
  "$PYTHON" -m venv "$VENV"
fi

if ! "$VENV/bin/python" -c 'import sys, tkinter; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 14) else 1)' >/dev/null 2>&1; then
  echo "[错误] $VENV 不是有效的 macOS Python 3.11-3.13 Tk 环境。"
  exit 1
fi

"$VENV/bin/python" -m pip install -e "$PROJECT_ROOT"
"$VENV/bin/python" -m bsense_experiment --self-test
"$VENV/bin/python" -m unittest discover -s "$PROJECT_ROOT/tests" -v

echo "[完成] macOS 环境已就绪：$VENV"
echo "运行实验：bash \"$PROJECT_ROOT/macos/run.sh\""
