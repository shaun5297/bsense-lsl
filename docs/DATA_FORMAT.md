# 数据与 Marker 格式

## XDF

LabRecorder 将 7 条 BioMultiLite 流和 1 条实验 Marker 流写进同一个 XDF。分析必须使用每条流的 `time_stamps`，不能按名义采样率重建时间轴。

已观察到：

- EEG 标称与实际采样率约 250 Hz；
- FNIRS/Heart Rate 约 25 Hz；
- Motion 约 12.5 Hz；
- General Metric 约 4 Hz；
- Metric 元数据标称 250 Hz，但实际约 25 Hz。

## JSON Marker

示例：

```json
{"code":301,"event":"mi_left","block":"run_1","trial":1,"condition":"mi_left","participant":"pilot01","session":"01","run":"001","task":"m1_mi","protocol_seed":123456789,"module_index":1,"module_count":3,"app_version":"0.4.1","unix_time":1783840000.0,"lsl_timestamp":416000.123456}
```

字段：

| 字段 | 含义 |
|---|---|
| `code` | 稳定事件编码 |
| `event` | 可读事件名称 |
| `block` | 动作/区块名称 |
| `trial` | 区块内试次号 |
| `participant` | 匿名被试编号 |
| `session` | 会话编号 |
| `run` | 运行编号 |
| `task` | 任务名 |
| `protocol_seed` | 由被试、会话、Run 和任务派生的可复现随机种子 |
| `module_index` / `module_count` | 本次连续采集中的模块位置和模块总数 |
| `app_version` | 实验程序版本 |
| `unix_time` | 系统 Unix 时间 |
| `lsl_timestamp` | LSL 本地时钟时间戳 |

`events.jsonl` 应与 XDF 中 `BSense Experiment Markers` 的 JSON 内容逐条一致。

不同任务会增加任务特有字段：

- N-Back：`level`、`nback_order`、`order_position`、`stimulus`、`is_target`、`responded`、`correct`、`reaction_time_s`，区块评分还包含 `correct_count`、`trial_count`、`accuracy`；
- M0 问卷：`fatigue`、`sleep_quality`、`neuroactive_medication`；
- M4A：`has_intent`、`object`、`condition`；
- M4B：`round`、`position`、`object`、`target_object`、`is_target`。
- 提示音：`audio_cue`、`audio_phase`；操作员异常标签使用编码 900–902。

## 受限被试资料

被试资料保存在 `participants/sub-{participant}_ses-{session}_profile.json`，包含姓名、年龄、性别、受教育年限、惯用手和知情同意状态。姓名不会复制到 XDF 或 Marker。共享生理数据前，应把整个 `participants` 目录排除在外。

## 实时窗口

实时接口 `LiveStreamManager.window()` 返回：

- `timestamps`：样本对应的原始 LSL 时间戳；
- `samples`：`(样本数, 通道数)` 的不可变元组；
- `descriptor`：流名称、类型、通道标签、通道数和名义采样率；
- `total_samples_received`：本次连接累计接收样本数；
- `is_live`：最近 2.5 秒内是否仍收到新样本。

传给绘图的窗口可以降采样；传给模型的窗口默认不降采样。两者来自同一完整环形缓冲。

## 文件命名

```text
sub-{participant}_ses-{session}_task-{task}_run-{run}.xdf
```

同一被试不能在不同电脑上更换 participant。修改设备配置或重采时增加 Run，不覆盖已有文件。
