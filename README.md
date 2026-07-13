# BSense LSL

面向 BSense-R、BioMultiLite 和官方 LabRecorder 的 Windows 实时数据与实验控制程序。程序提供 BioMultiLite LSL 多模态数据实时可视化、模块化正式采集协议、可复现的随机范式、自动 JSON LSL Marker、LabRecorder RCS 控制以及 XDF 文件存在性验证。

当前版本：`0.4.1`。

## 能做什么

- 自动发布 `BSense Experiment Markers` LSL 流；
- 并行订阅并显示 EEG、fNIRS、Motion、Metric、Heart Rate 和 General Metric；
- 为后续实时分类模型提供线程安全、带原始 LSL 时间戳的数据窗口；
- 控制 LabRecorder 执行 `Update -> Select All -> Filename -> Start -> Stop`；
- 每条 RCS 命令必须收到 `OK`；
- 目标 XDF 实际创建且非零后才开始实验；
- 保存 `events.jsonl` 和 `recorder.jsonl` 诊断日志；
- 可独立或连续执行 M0、M1、M2、M3A、M3B、M4A、M4B；
- 每个模块单独保存 XDF，结束后再决定是否进入下一模块；
- 自动记录 N-Back 反应时、正确性和主观评分；
- 使用大字号箭头/字母、物体图片和全屏内嵌表单；
- 保存受限被试资料，并避免把姓名扩散到 XDF 和 Marker；
- 在长静息/休息结束时播放带 Marker 的 Windows 提示音；
- 采集前自动扫描六类 BioMultiLite 数值流；
- 提供约 74 秒短流程和约 404 秒完整设备 QC；
- `Esc` 中止实验并保存已录数据。

## 系统组成

```text
BSense-R --Bluetooth--> BioMultiLite --7 LSL streams--+--> 实时监测/后续分类模型
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

BioMultiLite 是当前设备专有蓝牙协议与 LSL 之间的桥。除非厂商提供设备 SDK/协议，当前版本仍必须运行 BioMultiLite；本项目和 LabRecorder 都是它发布的 LSL 数据流的独立订阅者，二者可以同时工作。BioMultiLite 本地 `REC` 不需要开启。

## Windows 前置条件

| 组件 | 已验证版本/要求 |
|---|---|
| Windows | Windows 10/11 x64 |
| Python | 3.13 x64 |
| BioMultiLite | `1.0.9-E-Release` |
| LabRecorder | `v1.17.1` 发布页中的 Windows x64 包 |
| pylsl | `1.18.2`，由安装脚本自动安装 |
| 设备 | BSense-R、蓝牙连接正常 |

BioMultiLite 和 LabRecorder 不包含在本仓库中，需要分别安装。LabRecorder 官方仓库：<https://github.com/labstreaminglayer/App-LabRecorder>。

## 快速开始

### 1. 获取代码

```bat
git clone https://github.com/shaun5297/bsense-lsl.git
cd bsense-lsl
```

也可以下载 GitHub ZIP 并完整解压到纯英文路径，例如：

```text
C:\BCI\bsense-lsl
```

### 2. 安装环境

双击：

```text
windows\setup.bat
```

它会使用 Python 3.13 创建仓库内的 `.venv`，安装固定版本依赖并运行协议自测。安装脚本会拒绝其他操作系统创建的虚拟环境；虚拟环境不能在 macOS、Linux 和 Windows 之间复制。

### 3. 准备设备

1. 在 BioMultiLite 连接 BSense-R。
2. EEG 设置为 2 通道。
3. LSL 页面勾选全部 7 类流并点击 `Start`。
4. 打开 LabRecorder。
5. 勾选 `Enable RCS`，端口设为 `22345`。
6. 确认 LabRecorder 当前未在录制。
7. 不点击 BioMultiLite 本地 `REC`。

### 4. 实时监测

双击：

```text
windows\run_monitor.bat
```

也可以在实验程序首页点击“打开实时监测”。实时窗口默认显示最近 10 秒，可切换 5/10/20 秒；fNIRS 等高通道数流暂时只绘制前 8 个通道，但后台缓冲会保留全部通道。

### 5. 运行与联调

双击：

```text
windows\run.bat
```

启动脚本默认选择“设备 QC”和“短流程”。先在三页表单中填写被试/会话资料、选择模块并完成录制检查。使用新的匿名被试和 Run 编号完成联调；程序确认 XDF 已创建后才会进入全屏任务。

默认输出：

```text
C:\BCI\data\bsense\sub-pilot01_ses-01_task-deviceqc_run-001.xdf
C:\BCI\data\bsense\logs\sub-pilot01_ses-01_task-deviceqc_run-001_events.jsonl
C:\BCI\data\bsense\logs\sub-pilot01_ses-01_task-deviceqc_run-001_recorder.jsonl
```

### 6. 选择正式采集模块

短流程确认 8 条流和 Marker 后：

1. 取消“短流程”；
2. 选择一个或多个正式模块；
3. 老年被试执行 M1 时可启用“老年被试节奏”；
4. M2 可保留原方案由易到难，或在完成练习后选择拉丁方平衡顺序；
5. 多选模块按 M0 → M1 → M2 → M3A → M3B → M4A → M4B 执行；
6. 每个模块结束并保存后，程序询问是否开始下一模块。

首页被试表单包含姓名、年龄、性别、受教育年限和惯用手。姓名可留空；如填写，只保存在：

```text
participants\sub-{participant}_ses-{session}_profile.json
```

该文件包含直接身份信息，应限制访问。姓名不会进入 XDF、文件名或逐条 Marker。相同被试与会话再次运行时，程序会核对资料并拒绝静默改写。

同一组被试、会话和 Run 可以产生多个不同 `task` 的 XDF，不会互相覆盖。例如：

```text
sub-pilot01_ses-01_task-m0_baseline_run-001.xdf
sub-pilot01_ses-01_task-m1_mi_run-001.xdf
sub-pilot01_ses-01_task-m2_nback_run-001.xdf
```

## 实验模块

| 任务名 | 模块 | 主要输出 |
|---|---|---|
| `deviceqc` | 设备 QC | 信号、同步、动作伪迹验证 |
| `m0_baseline` | M0 准备与基线 | 闭/睁眼静息、基线问卷 |
| `m1_mi` | M1 运动想象 | 左手、右手、空闲三分类 |
| `m2_nback` | M2 认知负荷 | 0/1/2-back、反应时、正确性、评分 |
| `m3a_safety` | M3A 安全动作 | 正常与异常 Motion/EEG 标签 |
| `m3b_fatigue` | M3B 疲劳诱导 | 连续 1-back 与阶段疲劳评分 |
| `m4a_intent` | M4A 意图触发 | 拿取意图/无意图二分类 |
| `m4b_target` | M4B 目标选择 | 三物体高亮与目标确认 |

M4A/M4B 从 `assets` 加载水杯、手机和药瓶 PNG；图片缺失时自动回退到大字号文字，不影响 Marker。

完整时序、模块衔接和执行注意事项见[模块化采集协议](docs/PROTOCOLS.md)。

## 设备 QC 内容

完整 device-QC 包含：

- 睁眼静息 60 秒；
- 闭眼静息 60 秒；
- 眨眼、轻咬、左转、右转、点头、摇头取消各 5 次；
- 结束睁眼静息 60 秒。

该任务只用于验证设备、同步和动作响应，不作为正式训练集。正式头部动作模型需要随机化 `headgesture` 范式和按被试划分的评估。

## 项目结构

```text
bsense-lsl/
  assets/                     正式范式物体图片及 Tk 兼容 PNG
  src/bsense_experiment/     GUI、录制控制与协议定义
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
git remote add origin https://github.com/shaun5297/bsense-lsl.git
git push -u origin main
```

执行 `git add .` 前先用 `git status --short` 确认没有数据文件。本项目当前未附带开源许可证；公开仓库前应根据比赛、设备厂商和团队要求选择许可证。

## 文档

- [复现实验清单](docs/REPRODUCIBILITY.md)
- [模块化采集协议](docs/PROTOCOLS.md)
- [数据与 Marker 格式](docs/DATA_FORMAT.md)
- [实时数据与模型接入](docs/REALTIME.md)
- [故障排查](docs/TROUBLESHOOTING.md)
- [变更记录](CHANGELOG.md)
