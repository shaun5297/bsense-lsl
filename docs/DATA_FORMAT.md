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
{"code":201,"event":"head_left","block":"head_left","trial":1,"participant":"pilot01","session":"01","run":"001","task":"deviceqc","app_version":"0.1.1","unix_time":1783840000.0,"lsl_timestamp":416000.123456}
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
| `app_version` | 实验程序版本 |
| `unix_time` | 系统 Unix 时间 |
| `lsl_timestamp` | LSL 本地时钟时间戳 |

`events.jsonl` 应与 XDF 中 `BSense Experiment Markers` 的 JSON 内容逐条一致。

## 文件命名

```text
sub-{participant}_ses-{session}_task-{task}_run-{run}.xdf
```

同一被试不能在不同电脑上更换 participant。修改设备配置或重采时增加 Run，不覆盖已有文件。

