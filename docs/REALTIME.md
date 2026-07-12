# 实时数据与模型接入

## 当前数据链路

```text
BSense-R -> BioMultiLite -> LSL -> 实时监测
                              +-> LabRecorder -> XDF
                              +-> 后续分类模型 -> 安全控制适配器 -> 外部设备
```

BioMultiLite 负责连接头环并发布 LSL 流。实时监测和 LabRecorder 是互不依赖的 LSL 订阅者：关闭监测不影响 LabRecorder，关闭 LabRecorder 也不影响监测。当前没有厂商设备 SDK/蓝牙协议，因此不能安全地用本项目替代 BioMultiLite 直接连接 BSense-R。

## 启动顺序

1. 在 BioMultiLite 连接 BSense-R。
2. 打开 BioMultiLite 的 LSL 页面，勾选需要的数据流并点击 `Start`。
3. 打开 `windows\run_monitor.bat`，确认相应页签持续收到样本。
4. 打开 LabRecorder，点击 `Update`，确认相同数据流可见。
5. 启动实验程序；可由程序通过 RCS 自动开始/停止 LabRecorder。

无需点击 BioMultiLite 左下角的本地 `REC`。LSL 开启后，BioMultiLite 本身不会保存这批数据，正式记录由 LabRecorder 写入 XDF。

## 给分类模型读取实时窗口

`LiveStreamManager` 保留每条流最近 60 秒的完整通道数据。绘图降采样只发生在显示快照，不会改变模型窗口。

```python
from bsense_experiment.live import LiveStreamManager

manager = LiveStreamManager(buffer_seconds=60)
manager.start()

# 在模型工作线程中周期调用；不要在 Tkinter UI 线程执行模型推理。
window = manager.window("eeg", seconds=4.0)
if window is not None and window.is_live:
    timestamps = window.timestamps       # (samples,)，原始 LSL 时间戳
    samples = window.samples             # (samples, channels)
    channel_labels = window.descriptor.channel_labels

manager.stop()
```

支持的稳定类型键：`eeg`、`fnirs`、`motion`、`metric`、`heart_rate`、`general_metric`。

分类模型必须使用与训练阶段一致的通道顺序、采样率重采样、滤波、归一化和窗口长度。不要用名义采样率伪造时间轴，应依据 `timestamps` 重采样。

## 后续设备控制边界

建议把控制链路拆成三个阶段：

1. 模型输出类别和置信度；
2. 决策层完成平滑、连续窗口确认、置信度阈值、超时和信号质量拒绝；
3. 设备适配器把经过确认的离散命令发送给目标设备。

控制层应默认安全停止，并加入人工急停、命令冷却时间和允许命令白名单。当前版本只提供实时数据交换，不会向任何外部设备发送控制命令。
