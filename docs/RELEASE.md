# 发行构建

项目使用 PyInstaller 分别在目标操作系统原生构建：

- Windows 10/11 x64：`BSense-LSL-<version>-windows-x64.zip`
- macOS 15+ Apple Silicon：`BSense-LSL-<version>-macos-arm64.zip`

ZIP 内是目录型独立应用，包含 Python、pylsl、Tk、离线提示音和物体图片。
最终用户无需安装 Python。主程序内已包含实时监测入口，不再单独复制第二套运行时。

## 本地构建

macOS Apple Silicon：

```bash
bash "macos/setup.sh"
bash "macos/build_release.sh"
```

Windows x64：

```bat
windows\setup.bat
windows\build_release.bat
```

输出位于 `release/`：

```text
BSense-LSL-0.8.0-<platform>-<arch>.zip
BSense-LSL-0.8.0-<platform>-<arch>.zip.sha256
```

构建脚本会依次执行以下校验：

1. 检查 PNG、WAV、发行说明和第三方声明是否齐全；
2. 校验构建主机和 Python 位数符合目标平台；
3. 使用 PyInstaller 生成目录型 GUI 应用；
4. 校验 PE x64 或 Mach-O ARM64 架构；
5. 从冻结后的程序运行 `--self-test`；
6. 创建 ZIP 并生成 SHA-256。

Windows 构建不能从 macOS 交叉生成，反之亦然。PyInstaller 的 Python 解释器、
启动器和本地依赖都与构建操作系统及架构绑定。

## GitHub Actions

`.github/workflows/release.yml` 支持两种方式：

- 在 Actions 页面手动运行：只构建并保留两个平台的 workflow artifacts；
- 推送与 `pyproject.toml` 版本一致的 `v<version>` 标签：构建两个平台并创建
  GitHub Release。

例如当前版本只接受标签 `v0.8.0`。版本不一致时构建会停止，避免发布名称和程序
内版本不一致。

发布前建议先在 Actions 页面手动运行一次，下载两个 ZIP，在真实设备上完成下方
验收；确认后再创建并推送标签。提交、推送和打标签均不属于构建脚本的行为。

## 人工验收

每个平台至少执行：

1. 在全新用户目录解压并启动；
2. 确认首页版本、中文字体、物体图片和提示音正常；
3. 打开实时监测，确认可发现同机和局域网 BioMultiLite 流；
4. 运行短流程并生成 XDF、`events.jsonl`、`recorder.jsonl`；
5. 使用独立读取器打开 XDF，确认预期 8 条流和实验 Marker；
6. 中止一次正在运行的模块，确认已有数据仍能保存；
7. 执行一次两批或三批预设，确认每个模块独立生成文件。

## 签名边界

当前自动构建没有配置 Windows Authenticode 或 Apple Developer ID：

- Windows 首次下载可能显示 SmartScreen 提示；
- macOS 首次下载可能显示 Gatekeeper 提示；
- 面向团队内部测试可以分发未签名包；
- 面向外部用户的正式版本应在工作流中增加 Windows 代码签名，以及 macOS
  Developer ID 签名、公证和 stapling。

证书、密码和公证凭据只能存放在 GitHub Actions Secrets 或专用签名环境，不能
写入仓库。

## 版本与许可证

- `pyproject.toml` 与 `src/bsense_experiment/__init__.py` 的版本必须一致；
- 用户可见变更应记录在 `CHANGELOG.md`；
- 当前仓库没有项目级 `LICENSE`。这不阻止内部二进制测试，但公开源码或对外发布
  前必须由项目负责人确定专有分发条款或选择合适的开源许可证。
