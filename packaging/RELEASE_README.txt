BSense LSL 桌面版
==================

本发行包包含实验控制、实时 LSL 监测和内置 XDF 录制功能，不需要另行安装
Python。

启动方式
--------

Windows x64:
  解压完整 ZIP，双击 BSense-LSL.exe。请勿只复制 exe；_internal 目录是程序
  运行所需依赖。

macOS Apple Silicon:
  解压完整 ZIP，把 BSense-LSL.app 拖到“应用程序”，或直接双击运行。当前
  自动构建产物未使用 Apple Developer ID 签名和公证，首次启动时可在 Finder
  中按住 Control 点击应用并选择“打开”。正式外部分发前应完成签名与公证。

采集前检查
----------

1. 启动 BioMultiLite，连接设备并开始发布 LSL 数据流。
2. 在 BSense LSL 中打开“实时监测”，确认所需数据流正在刷新。
3. 填写被试、场次和 Run 信息，优先使用内置 XDF 录制。
4. 正式采集前先跑短流程，并检查生成的 XDF、事件日志和录制日志。

数据默认位置
------------

Windows: C:\BCI\data\bsense
macOS:   ~/Documents/BCI/data/bsense

注意
----

- Windows SmartScreen 或 macOS Gatekeeper 可能提示未签名应用。
- 本程序不会随包附带 LabRecorder；内置 XDF 录制无需 LabRecorder。
- 若使用 LabRecorder 兼容模式，请另行安装并启动 LabRecorder。
- 研究数据和被试资料不应放入程序目录或提交到 Git。
