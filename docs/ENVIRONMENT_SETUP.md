# Environment Setup

本文档用于在实验室电脑上首次配置视频 EEG 范式运行环境。

> 2026-09-08 更新：当前安装步骤以 [详细操作说明](OPERATOR_MANUAL.zh-CN.md) 第二、三节为准。
> 安装器已支持从 GitHub 源码下载项目本地 Python，不再强制要求预附带 runtime 或 Node.js。
> 下文保留为旧实验室部署包的历史记录。

## 重要原则

每台电脑只需要配置一次环境。环境配置成功后，以后每次实验都不用重新配置，直接双击启动文件即可。

推荐流程是先把 U 盘/移动硬盘里的整个项目文件夹复制到电脑本地硬盘，再运行实验。不要直接从 U 盘运行正式实验，因为视频读取可能更慢，也更容易卡顿。

复制目标必须是 **NTFS** 文件系统。项目会用 Windows directory junction 让 rating 与视频 EEG 共用同一份视频母库；exFAT/U 盘不能创建该链接。一键安装会明确报告这个前提失败，不会把它误报为 Python 或 PsychoPy 安装失败。

## 第一次部署到一台实验室电脑

1. 插上 U 盘或移动硬盘，等待 Windows 识别完成。

2. 将整个项目文件夹复制到实验室电脑本地，例如：

```text
<video_root>\visual-video-task-master
```

如果实验室电脑用户名或桌面路径不同，也可以放到其他本地路径。程序本身使用项目相对路径，不依赖某一台电脑的专属路径。

3. 进入复制后的项目文件夹，确认能看到这些文件：

```text
run_video_demo.bat
run_video_formal.bat
一键安装.vbs
video_eeg\
stimuli\videos\
```

4. 双击运行：

```text
<video_root>\一键安装.vbs
```

这个脚本会自动完成：

```text
检查包内 uv 和 Python 3.12
创建或修复 .venv
安装 PsychoPy 及其完整视频 EEG 运行依赖
修补 Windows 下 pyglet 的非致命 warning
检查 PsychoPy、SDK、视频/音频相关包是否可导入
```

5. 如果最后显示：

```text
所有 [OK] 检查通过
Lab environment is ready.
```

说明这台电脑环境配置完成。

## 之后每次启动实验

环境配置成功后，以后不需要再运行 `install_lab_env_uv.bat`。

Demo 启动：

```text
双击 run_video_demo.bat
```

正式实验启动：

```text
双击 run_video_formal.bat
```

## 正式实验前设备检查

正式实验启动后，先填写被试信息和 session 信息。确认后，程序会在真正开始 EEG 采集前显示强脑 SDK 检测画面。

连接成功时会显示设备名、通道数、采样率和检查样本数。看到成功提示后，点击“开始实验”或按空格键进入正式实验。

连接失败时，正式实验不会开始。请检查设备电源、电量、SDK/蓝牙/网络连接、设备是否被其他软件占用，然后点击“重试”或按 R 重新检测。需要退出时点击“退出”或按 Esc。

## 手动命令方式

如果双击总安装入口失败，也可以打开 PowerShell 手动执行。以下命令使用当前复制目录，不依赖固定盘符或用户名。

```powershell
Set-Location '<video_root>\visual-video-task-master'
```

如果电脑没有 uv，先运行：

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

关闭 PowerShell，重新打开，再运行：

```powershell
Set-Location '<video_root>\visual-video-task-master'
..\tools\uv.exe --version
..\runtime\python312\python.exe -m venv .venv
..\tools\uv.exe pip install --python .venv\Scripts\python.exe --no-deps psychopy==2026.2.2
..\tools\uv.exe pip install --python .venv\Scripts\python.exe -r lab_uv_env.toml --extra runtime
.\.venv\Scripts\python.exe scripts\patch_pyglet_win32.py
.\.venv\Scripts\python.exe scripts\check_video_eeg_env.py
```

看到所有 `[OK]` 且 `video_eeg core` 通过后，环境配置完成。

## 常见问题

### 每次实验前都要重新配环境吗？

不用。每台电脑第一次配置一次即可。之后每次实验直接双击 `run_video_formal.bat`。

### 可以直接从 U 盘运行吗？

不推荐。正式实验请复制到电脑本地硬盘运行，避免视频读取慢或播放卡顿。

### 如果提示找不到 Python 或 .venv 怎么办？

先运行一次：

```text
scripts\install_lab_env_uv.bat
```

如果仍失败，把报错窗口中的完整文字保存下来，用于排查。

### 视频应该放在哪里？

统一放在项目内：

```text
stimuli\videos\
```

不要把视频放到项目外部路径。这样复制到多台电脑时路径最稳定。
