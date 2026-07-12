# 复现实验清单

## 软件版本

每次采集记录：

- Windows 版本；
- BioMultiLite 版本；
- LabRecorder 版本；
- 本项目版本；
- Python 和 pylsl 版本；
- BSense-R 设备编号/固件；
- EEG 通道数和物理位置。

已验证基线：

```text
BioMultiLite 1.0.9-E-Release
LabRecorder v1.17.1 release / Windows asset 1.17.0
Python 3.13 x64
pylsl 1.18.2
bsense-lsl 0.2.5
EEG 2 channels
RCS 127.0.0.1:22345
```

## 采集前

1. 设备电量不低于 60%。
2. 禁用 Windows 睡眠和蓝牙节能。
3. 被试使用固定匿名编号。
4. 清洁皮肤并确认 EEG/光极贴合。
5. BioMultiLite EEG 设置为 2 通道。
6. LSL 勾选全部 7 类流并启动。
7. LabRecorder 启用 RCS 22345，当前未录制。
8. 不启动 BioMultiLite 本地 REC。
9. 先运行短流程。

## 短流程验收

- 目标 XDF 存在且大小大于 0；
- `_recorder.jsonl` 中五条 RCS 命令均为 `OK`；
- XDF 包含 8 条流；
- `BSense Experiment Markers` 有 26 条；
- XDF Marker 与 `_events.jsonl` 逐条一致；
- EEG 为 2 个非恒定通道；
- 连续流覆盖首尾 Marker；
- 左转、右转和点头在 Motion 中可辨认。

## 完整流程验收

- XDF 连续覆盖约 408 秒；
- 自动 Marker 共 50 条；
- 每类动作 5 次，无漏做；
- 动作在提示后约 2 秒内开始；
- 左右转 Gyro X 首方向相反；
- 点头主要落在 Gyro Y；
- 摇头取消具有双向 X 波动；
- 所有异常都写入会话备注。

## 跨电脑复现

另一台 Windows 电脑必须使用相同：

- BioMultiLite 流选择和 EEG 通道数；
- LabRecorder RCS 端口；
- 本项目 Git tag/commit；
- 实验程序版本和事件编码；
- 佩戴位置、动作说明和文件命名规则。

首次在新电脑运行时只使用 `pilot` 编号和短流程，不直接采正式被试。
