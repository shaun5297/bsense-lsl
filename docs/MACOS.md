# macOS 使用说明

## 支持范围

macOS 版本支持：

- 运行 BSense 实验控制 GUI；
- 发布 `BSense Experiment Markers` LSL 流；
- 实时订阅并显示 BioMultiLite 发布的数据流；
- 内置订阅全部可见 LSL 流并直接保存、验证 XDF；
- 保存事件日志和录制诊断日志；
- 使用 macOS 系统音播放实验过渡提示。

厂商 `BioMultiLite_1.0.9-E-Release.exe` 仍只能在 Windows 上运行。它负责设备蓝牙协议和 LSL 发布，不能仅靠本项目或 LabRecorder 替代。

推荐拓扑：

```text
BSense-R --Bluetooth--> Windows / BioMultiLite --LSL over LAN--+
                                                               +--> macOS / bsense-lsl --> XDF
macOS / bsense-lsl 实验 Marker --------------------------------+
```

Windows 和 Mac 必须接入同一可信局域网。优先使用同一个路由器的有线网络或稳定 Wi-Fi，不建议在正式采集时依赖虚拟机蓝牙透传、手机热点、VPN 或网络代理。

## 1. 准备 Python 环境

要求：

- Apple Silicon 或 Intel Mac；
- 带 Tk 的 Python 3.11、3.12 或 3.13；
- 当前用户对 `~/Documents/BCI/data/bsense` 有写权限。

在终端执行：

```bash
cd "/path/to/bsense-lsl"
bash "macos/setup.sh"
```

安装脚本只在仓库内创建 `.venv`，安装固定版本 `pylsl==1.18.2`，然后执行协议和单元测试。脚本只使用机器上已有的 Python，不自动下载安装；找不到带 Tk 的 Python 3.11–3.13 时会给出安装指引（如 `brew install python@3.13 python-tk@3.13`）并退出。损坏或来自其他系统的 `.venv` 会自动移开（`.venv.bak.*`）并重建，无需手动删除。若默认 `python3` 不合适，也可通过环境变量指定兼容解释器：

```bash
BSENSE_PYTHON="/path/to/python3.12" bash "macos/setup.sh"
```

虚拟环境不能在 Windows 与 macOS 之间复制。

## 2. LabRecorder 是可选兼容组件

默认“内置 XDF 录制（推荐）”不依赖 `LabRecorder.app`，无需打开已下载的 App-LabRecorder 源码或应用包。

只有需要复现旧版 RCS 工作流时，才使用本工作区已下载的：

```text
LabRecorder-1.17.0-macOS_universal-signed/LabRecorder.app
```

兼容模式打开方式：

```bash
bash "macos/open_labrecorder.sh"
```

也可在实验程序的“录制检查”页点击“打开 LabRecorder（兼容模式）”。程序依次查找：

1. `LABRECORDER_APP` 指定路径；
2. `bsense-lsl` 相邻目录中的已下载版本；
3. `/Applications/LabRecorder.app`；
4. Homebrew 安装位置。

选择 `LabRecorder RCS（兼容）` 时确认：

- `Enable RCS` 已勾选；
- `RCS Port` 是 `22345`；
- 当前没有正在进行的录制。

下载包内的默认配置已经设置 `RCSEnabled=1` 和 `RCSPort=22345`。这部分不属于默认部署要求。

## 3. 发布 Windows 设备流

在 Windows 电脑上：

1. 连接 BSense-R；
2. 打开 BioMultiLite，EEG 设置为 2 通道；
3. 在 LSL 页面勾选全部 7 类流并点击 `Start`；
4. 不开启 BioMultiLite 本地 `REC`；
5. 关闭 VPN、代理和非必要虚拟网卡；
6. 保持 Windows 与 Mac 在同一局域网。

macOS 第一次发现局域网流时，系统可能请求“本地网络”权限。请允许终端/Python 访问本地网络；拒绝后可在“系统设置 → 隐私与安全性 → 本地网络”中重新开启。

## 4. 验证与运行

先启动实时监测：

```bash
bash "macos/run_monitor.sh"
```

应发现 EEG、fNIRS、Motion、Metric、Heart Rate 和 General Metric 六类数值流。然后运行实验程序：

```bash
bash "macos/run.sh"
```

在“录制检查”页：

1. 点击“自动扫描 LSL 数据流”；
2. 点击“发送测试 Marker”；
3. 录制方式保持默认“内置 XDF 录制（推荐）”；
4. 使用新的匿名被试和 Run 编号执行短流程；
5. 完成后用 XDF 读取工具确认设备流和 `BSense Experiment Markers` 均存在。

默认输出示例：

```text
~/Documents/BCI/data/bsense/sub-pilot01_ses-01_task-deviceqc_run-001.xdf
~/Documents/BCI/data/bsense/logs/sub-pilot01_ses-01_task-deviceqc_run-001_events.jsonl
~/Documents/BCI/data/bsense/logs/sub-pilot01_ses-01_task-deviceqc_run-001_recorder.jsonl
```

## 5. 自测

```bash
bash "macos/self_test.sh"
```

此命令验证协议构建、文件命名、内置 XDF 写入、兼容 RCS 命令和平台适配逻辑。真实设备联调只需启动 Windows BioMultiLite 与 macOS `bsense-lsl`。
