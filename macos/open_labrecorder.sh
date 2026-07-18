#!/bin/zsh
set -eu

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ -n "${LABRECORDER_APP:-}" ]]; then
  candidates=("$LABRECORDER_APP")
else
  candidates=(
    "$PROJECT_ROOT/../LabRecorder-1.17.0-macOS_universal-signed/LabRecorder.app"
    "/Applications/LabRecorder.app"
    "$HOME/Applications/LabRecorder.app"
    "/opt/homebrew/opt/labrecorder/LabRecorder/LabRecorder.app"
    "/usr/local/opt/labrecorder/LabRecorder/LabRecorder.app"
  )
fi

for app_path in "${candidates[@]}"; do
  if [[ -f "$app_path/Contents/MacOS/LabRecorder" ]]; then
    /usr/bin/open "$app_path"
    echo "[完成] 已打开：$app_path"
    exit 0
  fi
done

echo "[错误] 未找到 LabRecorder.app。可将它放到 /Applications，或设置 LABRECORDER_APP。"
exit 1
