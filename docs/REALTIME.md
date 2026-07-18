# 实时数据与模型接入

## 当前数据链路

```text
BSense-R -> BioMultiLite -> LSL -> 实时监测
                              +-> bsense-lsl 内置录制器 -> XDF
                              +-> 后续分类模型 -> 安全控制适配器 -> 外部设备
```

BioMultiLite 负责连接头环并发布 LSL 流。实时监测和内置录制器是互不依赖的 LSL 订阅者，默认均由 `bsense-lsl` 管理。当前没有厂商设备 SDK/蓝牙协议，因此不能安全地用本项目替代 BioMultiLite 直接连接 BSense-R。

## 启动顺序

1. 在 BioMultiLite 连接 BSense-R。
2. 打开 BioMultiLite 的 LSL 页面，勾选需要的数据流并点击 `Start`。
3. 在 Windows 打开 `windows\run_monitor.bat`，或在 macOS 运行 `bash "macos/run_monitor.sh"`，确认相应页签持续收到样本。
4. 在实验程序“录制检查”页点击“自动扫描 LSL 数据流”，确认六类数值流齐全。
5. 保持默认“内置 XDF 录制”，开始短流程。
6. 程序校验并锁定预期的 8 条 LSL 流、创建 XDF，并在模块结束时写入流尾；无关流会被排除，重复设备流会阻止录制。

无需点击 BioMultiLite 左下角的本地 `REC`。LSL 开启后，BioMultiLite 本身不会保存这批数据，正式记录由 `bsense-lsl` 写入 XDF。

## 给分类模型读取实时窗口

`LiveStreamManager` 保留每条流最近 60 秒的完整通道数据。绘图降采样只发生在显示快照，不会改变模型窗口。

```python
from bsense_experiment.live import LiveStreamManager

manager = LiveStreamManager(buffer_seconds=60)
manager.start()

# 在模型工作线程中周期调用；不要在 Tkinter UI 线程执行模型推理。
window = manager.window("eeg", seconds=4.0)
if window is not None and window.is_live:
    timestamps = window.timestamps       # (samples,)，时钟校正、去抖且单调
    samples = window.samples             # (samples, channels)
    channel_labels = window.descriptor.channel_labels
    observed_srate = window.observed_srate

manager.stop()
```

支持的稳定类型键：`eeg`、`fnirs`、`motion`、`metric`、`heart_rate`、`general_metric`。

实时入口使用 pylsl 的时钟校正、去抖和单调化处理，避免厂商 EEG 块内时间戳倒退影响绘图和在线窗口；XDF 录制器独立订阅并保留原始时间戳。实时界面参考 BioMultiLite 的分组方式：EEG 显示去直流波形、频谱和频带功率，fNIRS 按源-检测器路径叠加两种波长，Motion 分离加速度与陀螺仪，低维指标显示当前值和趋势。稳健纵轴会忽略少量离群点并缓慢收缩，避免每次刷新时纵轴跳动。上述信号显示处理只存在于 `monitor.py` 的显示快照中，不修改实时样本值，也不修改 XDF。

状态栏同时显示名义与实测采样率。EEG 频谱优先使用至少 2 秒时间戳得到的实测采样率，并把横轴限制为 `min(45 Hz, Nyquist)`；频带上界超过 Nyquist 时界面显示部分可见标记，整个频带超出时显示 `N/A`。因此 25 Hz EEG 不能被误读为具有完整 Beta/Gamma 频带。当前设备的 Metric 元数据为 250 Hz、实测约 25 Hz，模型也应依据时间戳重采样。厂商流目前没有 `source_id`，发布端崩溃或重启后 pylsl 无法自动恢复原连接；实时窗口会提示此限制，此时应点击“重新扫描”。

分类模型必须使用与训练阶段一致的通道顺序、采样率重采样、滤波、归一化和窗口长度。不要用名义采样率伪造时间轴，应依据 `timestamps` 重采样。

## 后续设备控制边界

建议把控制链路拆成三个阶段：

1. 模型输出类别和置信度；
2. 决策层完成平滑、连续窗口确认、置信度阈值、超时和信号质量拒绝；
3. 设备适配器把经过确认的离散命令发送给目标设备。

控制层应默认安全停止，并加入人工急停、命令冷却时间和允许命令白名单。当前版本只提供实时数据交换，不会向任何外部设备发送控制命令。
