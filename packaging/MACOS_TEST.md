# 天堂支点：Apple Silicon 本机测试

本材料是当前开发版的源码快照，不是已构建的 Mac 应用。在你的 M 系列 Mac 本机构建，生成一个独立的 `.app` 窗口；不需要 GitHub、CI 或 Apple 开发者账户，也不改 Windows 的实际对局。

## 1. 准备构建环境

需要原生 arm64 的 Python 3.11、Node.js 24、pnpm 11，不要在 Rosetta 终端中构建。已有这些工具可跳过安装。有 Homebrew 时可以运行：

```bash
brew install python@3.11 node@24
export PATH="$(brew --prefix node@24)/bin:$PATH"
npm install -g pnpm@11
```

构建时需要联网下载依赖，应用运行时的地图、预测、规划与 OCR 使用本地数据。macOS 版本要求以安装成功的 Python、Node 和 PyObjC 为准；首轮建议在当前系统上本机构建并测试，不声称兼容全部旧版 macOS。

## 2. 构建

解压源码 ZIP，在终端进入 `CelestialFulcrum-source` 文件夹，依次执行：

```bash
python3.11 -m venv .venv-build
source .venv-build/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-desktop-macos.txt
python -m pip check
python scripts/build_macos.py
```

脚本先检查 Python/Node 的 arm64 架构，再构建页面、打包 Python、headless OpenCV、离线 OCR、游戏数据和全部图标。会执行本地自检，成功后生成：

- `dist/CelestialFulcrum.app`：双击启动的独立应用。
- `dist/CelestialFulcrum-<提交号>-dirty-mac-arm64.zip`：可以复制到另一台兼容的 Apple Silicon Mac。
- `work/macos-self-test.json`：服务、图片、模板、OCR 等自检报告。

`dirty` 表示包含未提交的开发改动，不是构建错误。`source-info.json` 记录本次源码内容的校验值。重复构建可以使用 `python scripts/build_macos.py --skip-install`。

## 3. 启动与测试

双击 `.app`，或在终端执行：

```bash
open dist/CelestialFulcrum.app
```

该测试包只有本地 ad-hoc 签名，没有公证。如果你自己构建的文件仍被系统拦截，在“系统设置 → 隐私与安全性”中检查并允许这份你信任的应用，不需要关闭全局安全设置。

应用使用 macOS 自带 WebKit；用户运行这个完整 `.app` 时不需要另外安装 Python、Node 或 OpenCV。不要只取出 `Contents/MacOS` 里的执行文件。新构建的存档、上传图片及日志位于 `~/Library/Application Support/CFARA`（`/Users/<用户名>/Library/Application Support/CFARA`），不写进应用包。旧版 `BlackFlow`、`Fulcrum` 存档目录不自动回退读取或迁移，请从旧版导出并手动导入；`--data-dir`、`CFARA_APP_DATA` 和旧显式环境变量仍可指定存储位置。

首轮请检查新建/恢复对局、图片上传、识图预览与合并、节点概率和分数、路线规划、数据编辑、关闭再打开。**Mac 暂不支持 Windows 的进程/窗口截图功能，请用图片上传或拖入截图。** macOS 原生窗口和实际截图回归仍需在你的 Mac 上验证，Windows 上的测试不能替代这一步。

窗口单独自检（会创建隐藏窗口并自动关闭）：

```bash
dist/CelestialFulcrum.app/Contents/MacOS/CelestialFulcrum \
  --window-test --data-dir work/macos-window-test --report work/macos-window-test.json
```

构建失败时保留终端最后一段输出；新构建启动失败查看 `~/Library/Application Support/CFARA/logs/desktop.log`。本材料不含你的实际对局、上传图片、开发环境或正在编辑的根目录 README。公开发布前还需处理数据授权、正式签名和公证，本轮不做。

参考：[PyWebView macOS 安装要求](https://pywebview.flowrl.com/guide/installation)、[PyInstaller 各平台分别构建和 arm64 参数](https://pyinstaller.org/en/stable/usage.html)。
