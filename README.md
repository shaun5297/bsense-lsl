# BSense-R LSL Experiment

面向 BSense-R、BioMultiLite 和官方 LabRecorder 的 Windows 实验控制程序。程序提供可复现的设备 QC 范式、自动 JSON LSL Marker、LabRecorder RCS 控制以及 XDF 文件存在性验证。

当前版本：`0.1.1`。

## 能做什么

- 自动发布 `BSense Experiment Markers` LSL 流；
- 控制 LabRecorder 执行 `Update -> Select All -> Filename -> Start -> Stop`；
- 每条 RCS 命令必须收到 `OK`；
- 目标 XDF 实际创建且非零后才开始实验；
- 保存 `events.jsonl` 和 `recorder.jsonl` 诊断日志；
- 提供约 74 秒短流程和约 404 秒完整设备 QC；
- `Esc` 中止实验并保存已录数据。

## 系统组成

```text
BSense-R --Bluetooth--> BioMultiLite --7 LSL streams--+
                                                       |
Experiment app --JSON Marker LSL stream---------------+--> LabRecorder --> XDF
       |
       +--RCS TCP 127.0.0.1:22345---------------------> LabRecorder
```

预期 XDF 共 8 条流：

1. EEG
2. FNIRS/IR
3. Motion
4. Metric
5. Heart Rate
6. BioMultiLite Marker
7. General Metric
8. BSense Experiment Markers

BioMultiLite Marker 可以是空流；正式事件使用第 8 条 JSON Marker 流。

## Windows 前置条件

| 组件 | 已验证版本/要求 |
|---|---|
| Windows | Windows 10/11 x64 |
| Python | 3.11 x64 |
| BioMultiLite | `1.0.9-E-Release` |
| LabRecorder | `v1.17.1` 发布页中的 Windows x64 包 |
| pylsl | `1.18.2`，由安装脚本自动安装 |
| 设备 | BSense-R、蓝牙连接正常 |

BioMultiLite 和 LabRecorder 不包含在本仓库中，需要分别安装。LabRecorder 官方仓库：<https://github.com/labstreaminglayer/App-LabRecorder>。

## 快速开始

### 1. 获取代码

```bat
git clone https://github.com/YOUR_ACCOUNT/bsense-lsl-experiment.git
cd bsense-lsl-experiment
```

也可以下载 GitHub ZIP 并完整解压到纯英文路径，例如：

```text
C:\BCI\bsense-lsl-experiment
```

### 2. 安装环境

双击：

```text
windows\setup.bat
```

它会创建仓库内的 `.venv`，安装固定版本依赖并运行协议自测。

### 3. 准备设备

1. 在 BioMultiLite 连接 BSense-R。
2. EEG 设置为 2 通道。
3. LSL 页面勾选全部 7 类流并点击 `Start`。
4. 打开 LabRecorder。
5. 勾选 `Enable RCS`，端口设为 `22345`。
6. 确认 LabRecorder 当前未在录制。
7. 不点击 BioMultiLite 本地 `REC`。

### 4. 运行短流程

双击：

```text
windows\run.bat
```

首次保留“短流程”勾选，使用新的匿名被试和 Run 编号。程序确认 XDF 已创建后才会进入全屏任务。

默认输出：

```text
C:\BCI\data\bsense\sub-pilot01_ses-01_task-deviceqc_run-001.xdf
C:\BCI\data\bsense\logs\sub-pilot01_ses-01_task-deviceqc_run-001_events.jsonl
C:\BCI\data\bsense\logs\sub-pilot01_ses-01_task-deviceqc_run-001_recorder.jsonl
```

### 5. 完整设备 QC

短流程确认 8 条流和 Marker 后，使用新 Run 编号并取消“短流程”，执行约 404 秒完整流程。

## 实验内容

完整 device-QC 包含：

- 睁眼静息 60 秒；
- 闭眼静息 60 秒；
- 眨眼、轻咬、左转、右转、点头、摇头取消各 5 次；
- 结束睁眼静息 60 秒。

该任务只用于验证设备、同步和动作响应，不作为正式训练集。正式头部动作模型需要随机化 `headgesture` 范式和按被试划分的评估。

## 项目结构

```text
bsense-lsl-experiment/
  src/bsense_experiment/     Python 程序
  windows/                   Windows 安装与启动脚本
  tests/                     协议与 RCS 测试
  config/                    事件编码表
  docs/                      复现和故障排查文档
  data/README.md             本地数据说明，真实数据被 Git 忽略
  .github/workflows/test.yml Windows CI
  pyproject.toml             版本和依赖入口
```

## 测试

Windows 双击：

```text
windows\self_test.bat
```

命令行：

```bat
.venv\Scripts\python -m bsense_experiment --self-test
.venv\Scripts\python -m unittest discover -s tests -v
```

## 数据与隐私

- `.xdf`、`.jsonl`、Raw Data ZIP、模型和输出目录默认被 `.gitignore` 排除。
- 被试编号必须匿名且跨会话保持一致。
- 不要把姓名、手机号或身份证信息写进文件名和 Marker。
- 本项目用于研究和比赛，不提供医疗诊断。

## 上传 GitHub

在项目根目录执行：

```bash
git init
git add .
git commit -m "Initial BSense-R experiment app"
git branch -M main
git remote add origin https://github.com/YOUR_ACCOUNT/bsense-lsl-experiment.git
git push -u origin main
```

执行 `git add .` 前先用 `git status --short` 确认没有数据文件。本项目当前未附带开源许可证；公开仓库前应根据比赛、设备厂商和团队要求选择许可证。

## 文档

- [复现实验清单](docs/REPRODUCIBILITY.md)
- [数据与 Marker 格式](docs/DATA_FORMAT.md)
- [故障排查](docs/TROUBLESHOOTING.md)
- [变更记录](CHANGELOG.md)

