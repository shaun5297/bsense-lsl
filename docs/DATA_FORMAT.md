# 数据与 Marker 格式

## XDF

内置录制器将 7 条 BioMultiLite 流和 1 条实验 Marker 流写进同一个标准 XDF。分析必须使用每条流的 `time_stamps`，不能按名义采样率重建时间轴。LabRecorder 兼容模式产生相同的数据组织。

每个模块开始时会要求六类数值流、BioMultiLite Marker 和实验 Marker 均存在，并为每一类只选择一条预期流。重复的 BioMultiLite 数值流或 Marker 会阻止开始，其他无关 LSL 流不会写入 XDF。模块开始后才出现的新流不会加入当前 XDF，应处理连接问题并使用新的 Run 重新采集。

项目现有联调记录中曾观察到：

- EEG 标称与实际采样率约 250 Hz；
- FNIRS/Heart Rate 约 25 Hz；
- Motion 约 12.5 Hz；
- General Metric 约 4 Hz；
- Metric 元数据标称 250 Hz，但实际约 25 Hz。

这些数值不是数据格式契约。如果当前设备配置的 EEG 实测为 25 Hz，就必须记录并按该 Run 的时间戳处理，不能沿用上述 250 Hz 观察值。当前设备的原始 EEG LSL 时间戳还观察到少量相邻倒退，主要出现在同一数据块内部。XDF 会保留这些原始时间戳；使用 `pyxdf.load_xdf()` 默认时间戳处理可得到去抖后的单调时间轴。任何离线分析都应检查时间戳间隔并显式记录读取参数，不能按名义采样率人工重建时间轴。

内置录制器会在模块启动后立即获取各流的 LSL 时钟偏移；临时失败时按 1 秒间隔重试，成功后恢复为 5 秒间隔。`_recorder.jsonl` 的每条 `stream_closed` 记录包含 `observed_srate`、`clock_offset_count`、`clock_offset_failures` 和 `timestamp_inversions`。偏移失败不会改写或丢弃原始样本，但 `clock_offset_count=0` 的文件必须在进入正式分析前单独验证同步。

BioMultiLite 的 fNIRS 流保存的是设备发布的 735/850 nm 原始光学通道，而不是程序预先计算的 HbO/HbR。只有在记录源-检测器几何、差分路径长度因子、转换方法和滤波参数后，分析数据才能命名为 HbO/HbR。因此不能在没有转换步骤时把原始数组声明为 `[HbO/HbR, 8ch, time]`。

## JSON Marker

示例：

```json
{"code":301,"event":"mi_left","block":"run_1","trial":1,"condition":"mi_left","participant":"pilot01","session":"01","run":"001","task":"m1_mi","protocol_seed":123456789,"module_index":2,"module_count":4,"module_sequence":["m0_baseline","m1_mi","m4a_intent","m4b_target"],"acquisition_batch":"two_part_a","short_protocol":false,"older_adult_timing":false,"app_version":"0.8.0","unix_time":1783840000.0,"lsl_timestamp":416000.123456}
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
| `module_sequence` | 本次开始时选择的有序模块任务名列表 |
| `acquisition_batch` | 采集批次预设标识：`two_part_a/b`、`three_part_1/2/3` 或 `custom` |
| `short_protocol` | 是否使用仅供联调的短流程 |
| `older_adult_timing` | 是否启用 M1 老年被试节奏 |
| `app_version` | 实验程序版本 |
| `unix_time` | 系统 Unix 时间 |
| `lsl_timestamp` | LSL 本地时钟时间戳 |

`events.jsonl` 应与 XDF 中 `BSense Experiment Markers` 的 JSON 内容逐条一致。

不同任务会增加任务特有字段：

- M0：`baseline_settle_start/end` 明确标记自然呼吸稳定段；问卷包含 `fatigue`、`sleep_quality`、`neuroactive_medication`；
- M1：`run_in_task`、`trial_in_run`、`condition`、`paradigm`；引导练习包含 `exclude_from_analysis=true`；Run 级评分包含 `left_imagery_success`、`right_imagery_success`、`idle_stability`、`imagery_effort`、`visible_movement` 和 `rating_scope=run`；动作候选 `mi_motion_warning` 还包含 `acceleration_span`、`gyroscope_span`、`quality_status=requires_offline_review` 和 `invalidates_trial=false`；
- N-Back：`level`、`nback_order`、`order_position`、`stimulus`、`is_target`、`responded`、`correct`、`reaction_time_s`、`feedback_shown`，区块评分还包含 `correct_count`、`trial_count`、`accuracy`；
- M2：`nback_pre_rest_start/end` 和 `nback_precheck_start/nback_precheck` 记录前置恢复与开始状态；`nback_task_end`、`block_rest`、`block_rest_end` 定义任务/恢复边界；
- M3A：`action`、`artifact_expectation`、`quality_status`，其中预期伪迹不等于已确认污染；
- M3B：`segment`、`position_in_block`、`elapsed_minutes`、`sequence_reset`、`kss_score`、`mental_fatigue_score`，并有任务后恢复边界；
- M4A：`has_intent`、`object`、`condition`、`paradigm=externally_cued_intent` 以及模块级主观评分；
- M4B：`round`、`position`、`object`、`target_object`、`is_target`、`eeg_analysis_scope`、`fnirs_analysis_scope`；
- M5：`kss_score`、`mi_difficulty`、`easiest_task`、`hardest_task`、`device_comfort` 和三类不适布尔值；
- 提示音：`audio_cue`、`audio_phase`、`audio_text`、`audio_voice`；操作员异常标签使用编码 900–902，自动 M1 动作复核候选使用编码 903。

## 派生训练数据

XDF 和 JSON Marker 是权威原始数据。训练表应由可版本化的离线脚本派生，而不是让采集程序把未经验证的质量结论写成标签。建议每行保存一个分析窗口及以下字段：

```text
subject_id, session, run, module, block, trial
window_start_lsl, window_end_lsl
label, label_name
eeg_observed_srate, fnirs_observed_srate
eeg_channel_labels, fnirs_channel_labels
preprocessing_version, quality_rule_version
rt_ms, correct, kss_score, subjective_effort
```

信号数组单独保存，并在元数据中记录实际形状。不得假设 EEG 固定为 `2 × 100` 或 fNIRS 固定为 `2 × 8 × 40`：窗口长度、实测采样率、原始波长/派生血红蛋白表示都可能不同。`reaction_time_s` 可在导出时无损换算为 `rt_ms`。

`eeg_quality`、`fnirs_quality` 和 `motion_artifact` 只有在质量规则已冻结并经过验证后才能生成。M3A 的 `motion_expected` 适合作为伪迹检测候选窗口，不应直接复制为两个模态的污染真值。

## 受限被试资料

被试资料保存在 `participants/sub-{participant}_ses-{session}_profile.json`，包含姓名、年龄、性别、受教育年限、惯用手和知情同意状态。姓名不会复制到 XDF 或 Marker。macOS/Linux 自动使用目录 `0700`、文件 `0600`；Windows 依赖数据目录 ACL。共享生理数据前，应把整个 `participants` 目录排除在外。

## 实时窗口

实时接口 `LiveStreamManager.window()` 返回：

- `timestamps`：经 LSL 时钟校正、去抖和单调化的实时时间戳；
- `samples`：`(样本数, 通道数)` 的不可变元组；
- `descriptor`：流名称、类型、通道标签、通道数和名义采样率；
- `total_samples_received`：本次连接累计接收样本数；
- `is_live`：最近 2.5 秒内是否仍收到新样本；
- `duration` / `observed_srate`：窗口实际跨度和依据时间戳计算的实测采样率。

传给绘图的窗口可以降采样；传给模型的窗口默认不降采样。两者来自同一完整环形缓冲。

## 文件命名

```text
sub-{participant}_ses-{session}_task-{task}_run-{run}.xdf
```

同一被试不能在不同电脑上更换 participant。修改设备配置或重采时增加 Run，不覆盖已有文件。
