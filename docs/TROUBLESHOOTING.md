# 故障排查

## 只有 events.jsonl，没有 XDF

`events.jsonl` 只证明实验程序运行过。程序会等待目标 XDF 创建，未创建时不会开始任务。

检查同名 `_recorder.jsonl`：

- 内置模式是否有 `stream_opened` 和 `recording_started`；
- 是否有 `recording_error`；
- LabRecorder RCS 兼容模式是否有 `rcs_connected`、`rcs_command` 和 `xdf_created`；
- 目标路径是否可写。

如果启动前检查失败且尚未创建 XDF/events，可以修复流配置后沿用同一 Run 重试；`_recorder.jsonl` 会保留最近一次启动诊断。如果已经创建 XDF 或 events，则再次采集必须增加 Run 编号。若内置录制报告某个流的接收线程错误，应保留该文件和诊断日志用于排查，但不要将该 Run 标记为成功数据。

## 无法连接 RCS（仅兼容模式）

1. LabRecorder 是否正在运行；
2. `Enable RCS` 是否勾选；
3. 端口是否为 `22345`；
4. 是否有其他程序占用端口；
5. 防火墙是否允许本机 TCP。

macOS 还应确认启动的是 `LabRecorder.app` 而不是仅下载了 `App-LabRecorder` 源码。可执行 `bash "macos/open_labrecorder.sh"`，或在实验程序中点击“打开 LabRecorder（兼容模式）”。

## 内置录制器或 LabRecorder 看不到流

1. BioMultiLite LSL 是否已点击 `Start`；
2. 先用“自动扫描 LSL 数据流”确认实验机能发现远端流；兼容模式再在 LabRecorder 点击 `Update`；
3. 关闭 VPN、代理和不必要的虚拟网卡；
4. 确认程序启动后能看到 `BSense Experiment Markers`；
5. 默认模式重启顺序：BioMultiLite -> LSL Start -> 实验程序；兼容模式最后执行 LabRecorder Update。

macOS 双机模式额外检查：

- Windows 与 Mac 是否处于同一局域网和同一网段；
- 是否已允许终端/Python 的 macOS“本地网络”权限；兼容模式还需允许 LabRecorder；
- 两端是否关闭 VPN、代理和非必要虚拟网卡；
- 防火墙或路由器是否阻止 LSL 发现流量；
- BioMultiLite 必须继续在 Windows 运行；macOS 上的 `bsense-lsl` 不直接连接 BSense-R 蓝牙。

## 实时监测看不到流

1. BioMultiLite 必须已连接头环；
2. 在 BioMultiLite 的 LSL 页面勾选目标流并点击 `Start`；
3. 点击实时监测窗口的“重新扫描”；
4. 确认 BioMultiLite 设备机与运行本项目的实验机网络可互通；
5. 关闭 VPN、代理和不必要的虚拟网卡后重试；
6. 记录流的 Name、Type 和 Channel count，以便检查厂商版本差异。

若状态栏提示厂商流没有 `source_id`，说明发布端重启后不能自动恢复旧连接。这不是当前样本丢失；如果 BioMultiLite 或其 LSL 发布被重启，请点击“重新扫描”。

## 六类数值流同时被误报重复

Windows 或 macOS 存在多个活动网卡（例如有线、Wi-Fi、VPN 或虚拟网卡）时，同一个 LSL outlet 可能经不同网络路径被解析多次，部分 liblsl/发布端组合甚至会为这些视图返回不同 UID。修复后的内置录制器依次依据 `source_id`、outlet 的 `created_at + hostname + 名称/类型/通道元数据`、UID 合并同一发布实例，并在 `_recorder.jsonl` 中记录：

- `discovered_count`：解析器返回的原始数量；
- `unique_discovered_count`：按同一发布实例指纹去重后的数量；
- `resolver_duplicate_count`：被安全忽略的重复网络视图数量。

`stream_discovery` 会在严格选择之前保存每条候选流的名称、类型、主机、`source_id`、UID、`created_at`、通道数和采样率，因此即使启动失败也能审计。创建时间或元数据不同的同类流仍会被视为两台设备或两组真实发布流并阻止录制，不能只按名称强行合并。若更新后仍提示重复，请提供对应 `_recorder.jsonl` 并关闭多余的 BioMultiLite/LSL 发布实例，而不是禁用这项安全检查。

厂商流未提供 `source_id` 时，程序会关闭 pylsl 无法生效的自动恢复选项，因此不再反复输出“can't be recovered automatically”警告。发布端一旦重启，仍需返回首页重新扫描并使用新的 Run 开始采集。

## 采样率显示与元数据不一致

实时窗口优先显示依据时间戳计算的实测值。当前已知 Metric 元数据为 250 Hz、实测约 25 Hz，这是厂商发布信息与实际节奏不一致，不是监测窗口主动降采样。离线分析应依据时间戳重采样，并保存实际读取和预处理参数。

## EEG 出现恒定通道

- 确认 BioMultiLite EEG 通道数与实际电极数一致；
- 当前验证配置为 2 通道；
- 4 通道模式下未连接通道可能表现为恒定占位值；
- 检查通道接触和物理位置。

## EEG 50 Hz 干扰强

- 检查参考/地电极接触；
- 远离电源适配器、插线板和高功率设备；
- 采集时固定线缆和头环；
- BioMultiLite Filters 只影响显示，XDF 仍是原始数据；
- 离线分析和实时推理必须使用一致的陷波配置。

## XDF 文件已存在

程序不会覆盖已有 XDF 或日志。增加 Run 编号，例如从 `001` 改为 `002`。
