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
bsense-lsl 0.4.1
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
10. 正式采集确认已取消“短流程”，并记录所选模块及顺序。
11. 自动扫描确认 EEG、fNIRS、Motion、Metric、Heart Rate 和 General Metric 六类数值流齐全。
12. 试听过渡提示音并确认音量舒适；若研究方案不允许听觉提示，应在首页关闭。
13. M1、M2、M4A、M4B 已在正式录制外完成指导与练习。

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

## 正式模块验收

- 每个完成模块都有独立、非零的 XDF、`events.jsonl` 和 `recorder.jsonl`；
- M1 每个 Run 的左手、右手、空闲各 10 Trial，四个 Run 合计每类 40 Trial；
- M2 每个负荷等级 3 个 Block，每个 Block 60 个刺激，并存在对应 `nback_trial_result`；
- M2 区块评分和 M3B 两分钟评分没有缺失；
- 随机化任务的 Marker 均含 `protocol_seed`；
- M4B 每轮恰有一个 `is_target=true` 的高亮；
- 被中止的模块保留 `experiment_abort`，不得标记为成功数据。
- 所有实际播放的过渡提示音均存在 `audio_cue` Marker；
- `participants` 受限资料目录未进入共享或训练数据包。

## 跨电脑复现

另一台 Windows 电脑必须使用相同：

- BioMultiLite 流选择和 EEG 通道数；
- LabRecorder RCS 端口；
- 本项目 Git tag/commit；
- 实验程序版本和事件编码；
- 佩戴位置、动作说明和文件命名规则。

首次在新电脑运行时只使用 `pilot` 编号和短流程，不直接采正式被试。
