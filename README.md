# BSense LSL

面向 BSense-R 和 BioMultiLite 的 Windows/macOS 实时数据、实验控制与 XDF 录制程序。程序提供 BioMultiLite LSL 多模态数据实时可视化、模块化正式采集协议、可复现的随机范式、自动 JSON LSL Marker，以及无需 LabRecorder 的内置 XDF 录制。

当前版本：`0.8.0`。

## 能做什么

- 自动发布 `BSense Experiment Markers` LSL 流；
- 并行订阅并显示 EEG、fNIRS、Motion、Metric、Heart Rate 和 General Metric；
- 为后续实时分类模型提供线程安全、带校正单调 LSL 时间戳的数据窗口；
- 内置校验并订阅预期的 7 条 BioMultiLite 流和 1 条实验 Marker，直接写入标准 XDF；
- 保留 LabRecorder RCS 和手动录制作为可选兼容模式；
- 目标 XDF 实际创建且非零后才开始实验；
- 保存 `events.jsonl` 和 `recorder.jsonl` 诊断日志；
- 可独立或连续执行 M0、M1、M2、M3A、M3B、M4A、M4B、M5；
- 每个模块单独保存 XDF，结束后再决定是否进入下一模块；
- 自动记录 N-Back 反应时、正确性和主观评分；字母与中央十字分时显示；
- 使用大字号箭头/字母、物体图片、全屏内嵌表单和大尺寸操作按钮；
- 全屏任务页持续显示 EEG、fNIRS、Motion 的连接、实测采样率、恒定通道和 EEG 贴轨/削顶状态，并可打开完整实时波形；
- N-Back 步骤使用幂等状态机，空格键只能记录当前刺激响应，不能触发隐藏按钮或推进实验；
- M1 明显动作候选自动写入复核 Marker，M2 开始前保留一分钟安静恢复并记录开始状态；
- 保存受限被试资料，并避免把姓名扩散到 XDF 和 Marker；
- 在闭眼、休息和模块过渡边界播放带 Marker 的离线中文女声提示；
- 采集前自动扫描六类 BioMultiLite 数值流；
- 提供约 75 秒短流程和约 409 秒完整设备 QC；
- `Esc` 中止实验并保存已录数据。

## 系统组成

```text
BSense-R --Bluetooth--> Windows / BioMultiLite --7 LSL streams--+
                                                                +--> bsense-lsl --> XDF
bsense-lsl --JSON Marker LSL stream------------------------------+
       |
       +--> 实时监测/后续分类模型
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

BioMultiLite 是当前设备专有蓝牙协议与 LSL 之间的桥。除非厂商提供设备 SDK/协议，仍必须有一台 Windows 电脑运行 BioMultiLite。`bsense-lsl` 可以运行在同一台或同局域网内另一台 Windows/macOS 电脑，直接订阅设备流并保存 XDF；BioMultiLite 本地 `REC` 不需要开启。

> macOS 边界：厂商 BioMultiLite 仍是 Windows `.exe`。使用 Mac 录制时，只需同一局域网中的 Windows 电脑运行 BioMultiLite 并发布 LSL 流；Mac 不需要安装或运行 LabRecorder。

推荐双机部署：

| 电脑 | 系统 | 运行程序 |
|---|---|---|
| 设备机 | Windows | BioMultiLite，仅负责蓝牙连接和发布 7 类 LSL 流 |
| 实验机 | Windows 或 macOS | `bsense-lsl`，负责实验、Marker、实时监测和 XDF 录制 |

两台电脑只需要位于同一可互通局域网。实验机不需要安装 BioMultiLite，设备机也不需要运行 LabRecorder 或 `bsense-lsl`。

## macOS 快速开始

```bash
cd "/path/to/bsense-lsl"
bash "macos/setup.sh"
bash "macos/run.sh"
```

独立打开实时监测：

```bash
bash "macos/run_monitor.sh"
```

macOS 需要带 Tk 的 Python 3.11–3.13；安装脚本会自动选择兼容解释器并创建本项目专用 `.venv`。默认数据目录是 `~/Documents/BCI/data/bsense`。完整的双机连接、权限设置和验证流程见 [macOS 使用说明](docs/MACOS.md)。

## Windows 前置条件

| 组件 | 已验证版本/要求 |
|---|---|
| Windows | Windows 10/11 x64 |
| Python | 3.13 x64 |
| BioMultiLite | `1.0.9-E-Release` |
| pylsl | `1.18.2`，由安装脚本自动安装 |
| 设备 | BSense-R、蓝牙连接正常 |

BioMultiLite 不包含在本仓库中，需要安装在连接 BSense-R 的 Windows 设备机。LabRecorder 不是默认运行依赖，只在选择兼容模式时使用。

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

以下操作在连接 BSense-R 的 Windows 设备机完成：

1. 在 BioMultiLite 连接 BSense-R。
2. EEG 设置为 2 通道。
3. LSL 页面勾选全部 7 类流并点击 `Start`。
4. 确认 BioMultiLite 设备机与实验机处于同一局域网。
5. 不点击 BioMultiLite 本地 `REC`。

### 4. 实时监测

双击：

```text
windows\run_monitor.bat
```

也可以在实验程序首页点击“打开实时监测”。实时窗口默认显示最近 10 秒，可切换 5/10/20 秒，并按设备软件的信号语义显示：

- EEG：Fp1/Fp2 去直流波形、最高 45 Hz（同时受实测 Nyquist 频率限制）的频谱；频带超出 Nyquist 时明确显示部分可见或 `N/A`；
- fNIRS：8 个源-检测器通道，每行叠加 735/850 nm 波形；
- Motion：三轴加速度与三轴陀螺仪分组；
- Metric、Heart Rate、General Metric：当前值卡片与趋势图；厂商未公开 Metric/General Metric 通道语义，因此按索引显示，不作生理含义推断。

去直流、稳健纵轴和频谱只用于显示，内置录制器仍原样写入 LSL 样本和原始时间戳。实时订阅会对时间戳执行 LSL 时钟校正、去抖和单调化，界面同时显示实测采样率；当实测值明显偏离元数据时会并列提示。实时窗口只刷新当前页签，后台继续缓冲全部六类流，以降低 Tk 绘图占用。

### 5. 运行与联调

双击：

```text
windows\run.bat
```

启动脚本默认不启用“短流程”，并预选 M0。先在三页表单中填写被试/会话资料、选择模块并完成录制检查；程序确认 XDF 已创建后才会进入全屏任务。只有进行流程联调时才显式启用短流程：macOS 使用 `bash "macos/run.sh" --short`，Windows 使用 `windows\run.bat --short`。

默认输出：

```text
C:\BCI\data\bsense\sub-pilot01_ses-01_task-m0_baseline_run-001.xdf
C:\BCI\data\bsense\logs\sub-pilot01_ses-01_task-m0_baseline_run-001_events.jsonl
C:\BCI\data\bsense\logs\sub-pilot01_ses-01_task-m0_baseline_run-001_recorder.jsonl
```

### 6. 选择正式采集模块

完成设备联调后：

1. 正式采集保持“短流程”关闭；
2. 可从“采集批次预设”一键选择两批 A/B 或三批方案；手动修改任一模块后自动切回“自定义”；
3. 老年被试执行 M1 时可启用“老年被试节奏”；
4. M2 正式组间比较建议在完成练习后选择拉丁方平衡顺序；保留由易到难仅用于原方案兼容，界面会提示时间/疲劳混杂；
5. M2 的按键正误颜色反馈只用于练习/联调，正式采集保持关闭；
6. 多选模块按 M0 → M1 → M2 → M3A → M3B → M4A → M4B → M5 执行；
7. 每个模块结束并保存后，程序询问是否开始下一模块。

不建议一次选择全部 M0–M5。推荐拆成两次采集，并在每次开始时执行 M0：

| 采集批次 | 选择模块 | 自动计时 | 用途 |
|---|---|---:|---|
| A：探索性运动与意图 | M0、M1、M4A、M4B | 约 52.4 分钟 | 运动想象、提示后意图和目标注意 |
| B：核心认知与疲劳 | M0、M2、M3A、M3B、M5 | 约 51.6 分钟，另加 M5 问卷 | 认知负荷、安全动作、疲劳和结束评估 |

设备 QC 不计入固定批次：每个采集日首次佩戴设备后执行；若中途重新佩戴或调整传感器，应再次执行。两次采集若跨日，应分别使用 `session=01`、`session=02`；M5 只在最终批次执行。老年或容易疲劳的被试建议进一步拆成三次：`M0+M1+M4A`、`M0+M2+M4B`、`M0+M3A+M3B+M5`。

应用批次预设会自动关闭短流程并清除未属于该批次的模块。每条 JSON Marker 会记录 `acquisition_batch`、`short_protocol` 和 `older_adult_timing`，因此即使数据跨 Session 保存，也能审计当时实际使用的批次和计时模式。

首页被试表单包含姓名、年龄、性别、受教育年限和惯用手。姓名可留空；如填写，只保存在：

```text
participants\sub-{participant}_ses-{session}_profile.json
```

该文件包含直接身份信息，应限制访问。macOS/Linux 会自动把 `participants` 目录和资料文件分别设为 `0700`/`0600`；Windows 应为数据目录配置仅研究人员可访问的 ACL。姓名不会进入 XDF、文件名或逐条 Marker。相同被试与会话再次运行时，程序会核对资料并拒绝静默改写。

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
| `m1_mi` | M1 运动想象（探索） | 左手、右手、空闲三分类、动作候选复核及 Run 级主观评分 |
| `m2_nback` | M2 认知负荷 | 前置安静恢复、开始状态、0/1/2-back、反应时、正确性、评分 |
| `m3a_safety` | M3A 安全动作 | 运动伪迹候选窗口与离线质量审查标签 |
| `m3b_fatigue` | M3B 疲劳诱导 | 分段持续 1-back、阶段 KSS/精神疲劳与任务后恢复 |
| `m4a_intent` | M4A 提示后意图（探索） | 外部提示后的拿取意图/无意图二分类 |
| `m4b_target` | M4B 目标注意（探索） | 三物体串行高亮与目标注意，不使用运动想象 |
| `m5_debrief` | M5 结束问卷 | 困倦、任务体验、设备舒适度与不适记录 |

M4A/M4B 从 `assets` 加载水杯、手机和药瓶 PNG；图片缺失时自动回退到大字号文字，不影响 Marker。

设备能力的保守边界是：Fp1/Fp2 不覆盖典型感觉运动区或顶叶 P300 最优位置，额部 fNIRS 也不适合判定单次快速高亮。因此 M1、M4A、M4B 均按探索性模块管理；M2/M3B 是主要验证方向。任何比赛准确率都必须来自按被试划分的留出评估，不能由范式直接预估。

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
  src/bsense_experiment/      GUI、内置 XDF 录制、离线语音与协议定义
  packaging/                  桌面发行入口和随包说明
  macos/                      macOS 安装、启动、自测与构建脚本
  windows/                    Windows 安装、启动、自测与构建脚本
  tools/                      发行构建和中文女声生成工具
  tests/                      协议、XDF、资源与发行构建测试
  config/                     事件编码表
  docs/                       协议、数据、复现、发行和故障排查文档
  data/README.md              本地数据说明，真实数据被 Git 忽略
  .github/workflows/          跨平台测试与发行工作流
  pyproject.toml              版本、运行依赖和构建依赖入口
```

## 测试

macOS：

```bash
bash "macos/self_test.sh"
```

Windows 双击：

```text
windows\self_test.bat
```

命令行：

```bat
.venv\Scripts\python -m bsense_experiment --self-test
.venv\Scripts\python -m unittest discover -s tests -v
```

## 可发行版

项目可构建不依赖目标电脑 Python 环境的两个 ZIP：

- Windows 10/11 x64；
- macOS 15+ Apple Silicon（ARM64）。

本地构建：

```bash
bash "macos/build_release.sh"
```

```bat
windows\build_release.bat
```

GitHub Actions 也可手动构建两个平台；推送与项目版本一致的 `v*` 标签时才会创建
GitHub Release。构建过程会校验目标架构、运行冻结程序自检并生成 SHA-256。完整说明
见[发行构建文档](docs/RELEASE.md)。

### 重新生成中文女声（仅维护者）

正式运行不需要 `edge-tts` 或网络。只有需要修改提示语时才执行：

```bash
python -m pip install ".[voice-generation]"
python "tools/generate_voice_cues.py"
```

只补齐缺少的语音文件时可追加 `--missing-only`。生成器固定使用 `zh-CN-XiaoxiaoNeural`，将联网生成的音频转换并裁剪为项目内置的 24 kHz 单声道 PCM WAV。实验程序在 Windows 使用 `winsound`、在 macOS 使用 `afplay` 播放缓存文件；文件缺失时回退到原系统提示音。

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
- [macOS 使用说明](docs/MACOS.md)
- [发行构建与验收](docs/RELEASE.md)
- [故障排查](docs/TROUBLESHOOTING.md)
- [变更记录](CHANGELOG.md)
