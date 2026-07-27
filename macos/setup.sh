#!/bin/zsh
set -eu

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$PROJECT_ROOT/.venv"

has_usable_python() {
  "$1" -c 'import sys, tkinter; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 14) else 1)' >/dev/null 2>&1
}

python_version_of() {
  "$1" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null || echo ""
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

# 安装缺失的 Python/Tk：优先为已存在但缺 Tk 的解释器补装 python-tk，
# 否则通过 Homebrew 安装 python@3.13 与 python-tk@3.13。
install_python() {
  if ! command -v brew >/dev/null 2>&1; then
    echo "[错误] 未找到带 Tk 的 Python 3.11-3.13，且未安装 Homebrew，无法自动安装。"
    echo "请先安装 Homebrew（https://brew.sh），再重新运行本脚本；"
    echo "或手动安装 Python 3.13 后通过 BSENSE_PYTHON 指定解释器。"
    return 1
  fi

  for candidate in python3.13 python3.12 python3.11; do
    if ! command -v "$candidate" >/dev/null 2>&1; then
      continue
    fi
    executable="$(command -v "$candidate")"
    version="$(python_version_of "$executable")"
    case "$version" in
      3.11|3.12|3.13)
        echo "[安装] $candidate 缺少 Tkinter，正在安装 python-tk@$version …"
        brew install "python-tk@$version"
        return 0
        ;;
    esac
  done

  echo "[安装] 未找到 Python 3.11-3.13，正在通过 Homebrew 安装 python@3.13 与 python-tk@3.13 …"
  brew install python@3.13 python-tk@3.13
}

if ! PYTHON="$(find_python)"; then
  install_python
  if ! PYTHON="$(find_python)"; then
    echo "[错误] 安装后仍未找到带 Tk 的 Python 3.11-3.13。"
    echo "可通过 BSENSE_PYTHON 指定解释器后重试。"
    exit 1
  fi
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
