# 故障排查

## 只有 events.jsonl，没有 XDF

`events.jsonl` 只证明实验程序运行过。v0.1.1 会等待目标 XDF 创建，未创建时不会开始任务。

检查同名 `_recorder.jsonl`：

- 是否有 `rcs_connected`；
- 每条 `rcs_command` 是否返回 `OK`；
- 是否有 `xdf_created`；
- 目标路径是否可写。

## 无法连接 RCS

1. LabRecorder 是否正在运行；
2. `Enable RCS` 是否勾选；
3. 端口是否为 `22345`；
4. 是否有其他程序占用端口；
5. 防火墙是否允许本机 TCP。

## LabRecorder 看不到流

1. BioMultiLite LSL 是否已点击 `Start`；
2. LabRecorder 点击 `Update`；
3. 关闭 VPN、代理和不必要的虚拟网卡；
4. 确认程序启动后能看到 `BSense Experiment Markers`；
5. 重启顺序：BioMultiLite -> LSL Start -> 实验程序 -> LabRecorder Update。

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

