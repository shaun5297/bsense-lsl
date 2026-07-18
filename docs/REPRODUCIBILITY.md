# 复现实验清单

## 软件版本

每次采集记录：

- 操作系统与版本（Windows/macOS）；
- BioMultiLite 版本；
- 录制方式（内置 XDF 或 LabRecorder 兼容模式）；
- 本项目版本；
- Python 和 pylsl 版本；
- BSense-R 设备编号/固件；
- EEG/fNIRS 通道数和物理位置；
- 每条流依据 XDF 时间戳计算的实测采样率及重采样参数。

已验证基线：

```text
BioMultiLite 1.0.9-E-Release
Python 3.13 x64
pylsl 1.18.2
bsense-lsl 0.7.0
EEG 2 channels
Recorder built-in XDF
```

## 采集前

1. 设备电量不低于 60%。
2. 禁用采集电脑睡眠；Windows 设备源电脑同时禁用蓝牙节能。
3. 被试使用固定匿名编号。
4. 清洁皮肤并确认 EEG/光极贴合。
5. BioMultiLite EEG 设置为 2 通道。
6. LSL 勾选全部 7 类流并启动。
7. 录制方式保持“内置 XDF 录制（推荐）”。
8. 不启动 BioMultiLite 本地 REC。
9. 先运行短流程。
10. 正式采集确认已取消“短流程”，并记录所选模块及顺序。
11. 自动扫描确认 EEG、fNIRS、Motion、Metric、Heart Rate 和 General Metric 六类数值流齐全。
12. 确认没有重复发布的第二组 EEG/fNIRS 等设备流；内置录制器遇到同类重复流会拒绝开始，并只录制校验通过的 8 条预期流。
13. 开始录制后不得再启动缺失流；内置录制器会锁定模块开始时的 8 条流。
14. 试听中文女声过渡提示并确认音量舒适；若研究方案不允许听觉提示，应在首页关闭。
15. M1、M2、M4A、M4B 已在正式录制外完成指导与练习。
16. 已确定本次会话是否执行 M5，并预先约定不适事件的停止与处理流程。

## 短流程验收

- 目标 XDF 存在且大小大于 0；
- `_recorder.jsonl` 包含已打开的流、录制开始和正常停止记录；
- XDF 包含 8 条流；
- `BSense Experiment Markers` 有 26 条；
- XDF Marker 与 `_events.jsonl` 逐条一致；
- EEG 为 2 个非恒定通道；
- 用分析读取器确认校正后的 EEG 时间戳单调，并记录是否启用了时钟同步/去抖；
- Metric 按时间戳计算的实测采样率约 25 Hz，不以元数据 250 Hz 直接重建时间轴；
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
- M1 的 `mi_cue`、条件开始、`mi_trial_end` 数量一致，且四个 Run 的总体评分没有缺失；
- M2 每个负荷等级 3 个 Block，每个 Block 60 个刺激，并存在对应 `nback_trial_result`、`nback_task_end` 与恢复边界；
- M2 区块评分和 M3B 的 1–9 KSS/1–5 精神疲劳评分没有缺失；M3B 每段均有开始/结束 Marker、段内位置及 25% 目标比例；
- M3A 动作只标记 `motion_expected` 候选窗口，模态污染结论另行审查；
- 随机化任务的 Marker 均含 `protocol_seed`；
- M4B 每轮恰有一个 `is_target=true` 的高亮；
- M4A Marker 明确为 `externally_cued_intent`，M4B fNIRS 分析范围明确为 `block_level_only`；
- 执行 M5 时，结束问卷所有结构化字段均已提交；
- 被中止的模块保留 `experiment_abort`，不得标记为成功数据。
- 所有实际播放的过渡提示均存在含 `audio_text`、`audio_voice` 的 `audio_cue` Marker；
- 四个缓存语音 WAV 存在且为 24 kHz、单声道、16-bit PCM；
- `participants` 受限资料目录未进入共享或训练数据包。

## 跨电脑复现

另一套采集电脑必须使用相同：

- BioMultiLite 流选择和 EEG 通道数；
- 录制方式；若使用兼容模式，还需保持 LabRecorder 版本和 RCS 端口一致；
- 本项目 Git tag/commit；
- 实验程序版本和事件编码；
- 佩戴位置、动作说明和文件命名规则。

模型复现还必须保存被试级训练/验证/测试划分、预处理代码版本和随机种子。同一被试或同一连续 Block 的相邻窗口不能跨集合，以免时间相关性造成数据泄漏。

首次在新电脑运行时只使用 `pilot` 编号和短流程，不直接采正式被试。
