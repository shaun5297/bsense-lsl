# Changelog

## 0.2.5

- Python 发行包名称从 `bsense-lsl-experiment` 统一为 `bsense-lsl`；
- 保留 `bsense_experiment` 导入包和现有命令入口，避免破坏已有脚本；
- Windows 安装时清理虚拟环境中的旧发行包元数据。

## 0.2.4

- Windows 虚拟环境恢复统一使用 `.venv`；
- 安装脚本保留操作系统与 Python 3.13 有效性检查，避免再次使用 macOS 虚拟环境。

## 0.2.3

- 项目元数据支持 Python 3.13；
- Windows 安装脚本固定使用 Python 3.13 和 `.venv-windows`；
- 检测到旧 `.venv` 时明确提示并忽略，避免再次引用其他操作系统的解释器路径。

## 0.2.2

- Windows 脚本改用独立的 `.venv-windows`，避免误用从 macOS/Linux 复制过来的虚拟环境。

## 0.2.1

- 修复默认实时缓冲秒数以浮点数传入 pylsl，导致发现流后接收线程无法创建的问题；
- 实时监测页直接显示 LSL 接收线程错误，不再只显示“等待新样本”。

## 0.2.0

- 新增 BioMultiLite 六类数值 LSL 流的自动发现与并行订阅；
- 新增 EEG、fNIRS、Motion 和生理指标实时波形窗口；
- 新增线程安全的完整通道时间窗接口，供后续分类模型读取；
- 新增独立实时监测入口和 Windows 启动脚本；
- 明确 BioMultiLite、LabRecorder、实时监测与未来设备控制的职责边界。

## 0.1.1

- 新增 LabRecorder RCS `OK` 回执验证；
- 保持单次录制使用同一 TCP 连接；
- 开始任务前验证 XDF 已创建且非零；
- 停止后再次验证 XDF；
- 新增 `_recorder.jsonl` 诊断日志；
- 禁止覆盖已有 XDF 和日志。

## 0.1.0

- 首个 BSense-R device-QC GUI；
- 自动 JSON LSL Marker；
- 短流程与完整流程；
- LabRecorder RCS 自动控制。
