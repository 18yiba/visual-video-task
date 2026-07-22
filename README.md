# Visual Video Task：PsychoPy Image_B EEG 实验

本项目用于运行一次纯行为图片评分和五次图片脑电观看。每张正式实验图片最终包含一次人工评分，以及 Session 2、3、4、5、6 中各一次有效脑电呈现事件。

行为评分中的每一道题均不限时。被试使用 F/J 调整选项并在确认后按空格进入下一题，程序继续保存每题反应时。

- BrainCo BCIGo 外部 EDF 录制 + LSL Marker（当前推荐方式）
- BrainCo EEG LSL 输入（仅在确实存在 EEG LSL Outlet 时使用）
- BrainCo 旧 SDK 直连
- Neuracle/JellyFish TCP 实时转发
- 模拟 EEG 流程测试
- 命令行联通预检、LSL 扫描、BLE/Wi-Fi 底层诊断
- 中断恢复、分段事件与行为数据导出

纯行为评分入口是：

```text
psychopy_image_b_rating.py
```

EEG重复观看入口是：

```text
psychopy_image_b_experiment.py
```

## 1. 当前验证环境

Windows PowerShell 下推荐使用已经验证过的解释器：

```powershell
$PY = 'D:\ProgramData\miniconda3\envs\psychopy_env\python.exe'
& $PY --version
```

当前实际环境：

```text
Python 3.10.20
PsychoPy 2026.2.0
pylsl 1.18.2
NumPy 2.2.6
```

进入项目目录：

```powershell
Set-Location 'D:\QW_FILE\visual-video-task'
```

检查运行环境：

```powershell
& $PY psychopy_image_b_experiment.py --doctor
```

说明：

- BCIGo 外部录制模式只需要 `pylsl`，不要求安装 `bcigo_sdk`。
- BrainCo 旧 SDK 直连模式需要 `bc_ecap_sdk`（发行包名通常为 `bc-ecap-sdk`）。
- `--doctor` 中 `bcigo_sdk` 显示缺失，不影响推荐的 BCIGo + Marker 工作流。

## 2. 采集模式总览

| 设备/模式 | `device_type` | `brainco_transport` | EEG 在哪里录制 | 项目是否生成 `continuous_eeg.npy` |
|---|---|---|---|---|
| BrainCo + BCIGo（推荐） | `brainco` | `bcigo` | BCIGo 的 EDF | 否 |
| BrainCo EEG LSL 输入 | `brainco` | `lsl` | 项目本地 | 是 |
| BrainCo SDK 直连 | `brainco` | `sdk` | 项目本地 | 是 |
| Neuracle/JellyFish | `neuracle` | 不适用 | 项目本地 | 是 |
| 模拟 EEG | 配置中的设备类型 | 不适用 | 项目本地模拟数据 | 是 |

不要把 BCIGo 模式与 EEG-LSL 输入模式混淆：当前 BCIGo 的“第三方软件”页面用于扫描并接收实验程序发布的 Marker；BCIGo 自己连接脑电帽并写 EDF，它不会在该工作流中发布 EEG LSL Outlet。

## 3. 快速启动

### 3.1 模拟 EEG 短流程

先用4个试次和窗口模式分别检查行为评分与EEG观看：

```powershell
& $PY psychopy_image_b_rating.py --max-trials 4 --windowed
& $PY psychopy_image_b_experiment.py --dummy-eeg --max-trials 4 --windowed
```

跳过启动对话框时，程序直接使用 `config.yaml` 中的被试与 session 配置：

```powershell
& $PY psychopy_image_b_experiment.py --dummy-eeg --max-trials 4 --windowed --no-dialog
```

### 3.2 使用默认配置启动

```powershell
& $PY psychopy_image_b_rating.py
& $PY psychopy_image_b_experiment.py
```

### 3.3 常用启动参数

```text
--config PATH               指定配置文件
--max-trials N              限制本次试次数；0 表示使用完整配置
--timestamp-label LABEL     指定批次标签
--windowed                  窗口模式
--no-dialog                 不显示启动配置对话框
--dummy-eeg                 强制使用模拟 EEG
--real-eeg                  强制使用真实设备路径
--device-type brainco       使用 BrainCo
--device-type neuracle      使用 Neuracle
--eeg-check-only            只检查联通，随后退出
--preflight-eeg             联通通过后等待 Enter，再进入 PsychoPy
```

查看全部参数：

```powershell
& $PY psychopy_image_b_experiment.py --help
```

实验运行中按 `Escape` 会中止正式流程，并尽量安全保存已产生的事件与行为数据。

## 4. BrainCo + BCIGo 推荐流程

### 4.1 数据链路

```text
脑电帽 ──> BCIGo ──> EDF（EEG + IMU + Marker 注释）
实验程序 ──LSL Marker──> BCIGo
实验程序 ──> records_storage（行为数据 + 本地事件时间线）
```

默认 Marker 身份：

```text
streamName: visual-video-task-Markers
type:       Markers
sourceId:   visual-video-task-marker
format:     int32
```

### 4.2 推荐的完整预检与启动命令

先在 BCIGo 中连接脑电帽，然后运行：

```powershell
& $PY psychopy_image_b_experiment.py `
  --preflight-eeg `
  --real-eeg `
  --device-type brainco `
  --brainco-transport bcigo `
  --brainco-lsl-timeout 60
```

操作顺序：

1. 在 BCIGo 中确认脑电帽已经连接，实时波形正常。
2. 第一轮 session 前，在 BCIGo 开始一次录制；后续 session 不要停止，持续写入同一个 EDF。
3. 运行上述命令；程序会发布 Marker Outlet。
4. 在 BCIGo 的“第三方软件”页面开启 LSL，点击“扫描”并选择 `visual-video-task-Markers`。
5. 命令行显示“BCIGo Marker 连接检查通过”后，按 Enter 进入 PsychoPy 实验。
6. 当前 session 结束时，实验程序只保存行为数据和本地事件，不会停止 BCIGo 或处理 EDF。
7. 所有 session 全部完成后，再在 BCIGo 停止录制并保存这一份 EDF。

同一 EDF 可以包含多个 session。每个 session 都会发送 `session_start` 和 `session_end` Marker；分析时按这些边界，并结合各 session 目录中的 `events.json` 和 `metadata.json` 进行分段。建议严格按 session 顺序运行，并记录 EDF 对应的被试与 session 范围。

只验证 Marker 联通、不打开实验窗口：

```powershell
& $PY psychopy_image_b_experiment.py `
  --eeg-check-only `
  --real-eeg `
  --device-type brainco `
  --brainco-transport bcigo `
  --brainco-lsl-timeout 60
```

注意：`--eeg-check-only` 退出后 Marker Outlet 会消失，BCIGo 会重新显示扫描状态；正式实验应使用 `--preflight-eeg`，这样同一个 Marker Outlet 会一直保持到实验结束。

### 4.3 BCIGo 数据位置

BCIGo 默认 EDF 目录通常是：

```text
C:\Users\<用户名>\AppData\Local\com.brainco.bcigo\*.edf
```

本项目的行为与事件目录由 `storage.records_dir` 控制，当前为：

```text
D:\QW_FILE\visual-video-task\records_storage
```

BCIGo 模式下，项目目录不会出现实时 EEG `.npy`，这是正常设计，不代表 EEG 没有录制。EEG 和硬件对齐后的 Marker 以 EDF 信号/注释形式保存在 BCIGo 文件中。实验程序不会要求每轮停止录制、复制 EDF 或自动转换 NPY。

## 5. BrainCo EEG-LSL 输入模式

这个模式只在某个程序确实发布了规则采样的 EEG LSL Outlet 时使用。当前 BCIGo “第三方软件”工作流本身不提供这个 EEG Outlet。

### 5.1 列出当前所有 LSL 流

```powershell
& $PY -c "from pylsl import resolve_streams; ss=resolve_streams(wait_time=10); print('COUNT',len(ss)); [print('name=',repr(s.name()),'type=',repr(s.type()),'source_id=',repr(s.source_id()),'channels=',s.channel_count(),'sfreq=',s.nominal_srate(),'format=',s.channel_format()) for s in ss]"
```

目标 EEG 流至少应满足：

- `type=EEG`，或与 `brainco_lsl_stream_type` 配置一致
- 至少 32 个通道
- 固定采样率
- 采样率与顶层 `sfreq` 完全一致

### 5.2 自动匹配 EEG LSL

```powershell
& $PY psychopy_image_b_experiment.py `
  --eeg-check-only `
  --real-eeg `
  --device-type brainco `
  --brainco-transport lsl `
  --brainco-lsl-timeout 30
```

### 5.3 精确指定 LSL 流

存在多个 EEG 流时，使用扫描结果中的精确值：

```powershell
& $PY psychopy_image_b_experiment.py `
  --eeg-check-only `
  --real-eeg `
  --device-type brainco `
  --brainco-transport lsl `
  --brainco-lsl-name '实际streamName' `
  --brainco-lsl-source-id '实际sourceId' `
  --brainco-lsl-timeout 30
```

联通通过后，将 `--eeg-check-only` 改为 `--preflight-eeg` 启动正式实验。

对应 `config.yaml`：

```yaml
device_type: brainco
hardware_dummy_mode: false
sfreq: 250.0
device:
  brainco_transport: lsl
  brainco_lsl_stream_name: ''
  brainco_lsl_stream_type: EEG
  brainco_lsl_source_id: ''
  brainco_lsl_resolve_timeout_sec: 15.0
  brainco_lsl_ready_timeout_sec: 10.0
```

## 6. BrainCo 旧 SDK 直连模式

SDK 直连模式绕过 BCIGo，由实验程序直接连接脑电帽并在 `records_storage` 中保存 `continuous_eeg.npy`。

正式使用前应关闭 BCIGo，避免两个程序竞争同一个硬件 TCP 连接。

### 6.1 自动发现

```powershell
& $PY psychopy_image_b_experiment.py `
  --eeg-check-only `
  --real-eeg `
  --device-type brainco `
  --brainco-transport sdk `
  --brainco-scan-timeout 15 `
  --brainco-ready-timeout 30
```

### 6.2 手动 IP 和端口

```powershell
& $PY psychopy_image_b_experiment.py `
  --eeg-check-only `
  --real-eeg `
  --device-type brainco `
  --brainco-transport sdk `
  --brainco-addr '设备IP' `
  --brainco-port 设备端口 `
  --brainco-ready-timeout 30
```

自动发现使用 `_brainco-eeg._tcp.local.` mDNS 服务。端口由设备发现结果提供，不应把一次运行中看到的端口永久当作固定值。

### 6.3 BLE/Wi-Fi 底层诊断

只扫描附近的 BrainCo/Zephyr 设备，不建立 BLE 连接：

```powershell
& $PY brainco_device_doctor.py --scan-seconds 8
```

连接指定 BLE Device ID，并读取设备与 Wi-Fi 状态：

```powershell
& $PY brainco_device_doctor.py `
  --inspect `
  --device-id '扫描显示的BLE Device ID' `
  --connect-timeout 15
```

注意：

- BLE Device ID 不应自动当作设备 SN。
- `config.yaml` 中的 `brainco_device_id` 是旧 SDK parser 的逻辑 ID，也不等同于 SN。
- 不要在 BCIGo 正式录制期间运行 `--inspect`，它会建立额外的 BLE 连接。
- `brainco_device_doctor.py` 是独立诊断工具，不会启动实验或录制 EEG。

## 7. Neuracle/JellyFish 联通

Neuracle 后端通过 JellyFish/数据转发程序的 TCP 服务读取 EEG。

当前默认配置：

```yaml
device_type: neuracle
sfreq: 250.0
device:
  neuracle_host: 127.0.0.1
  neuracle_port: 8712
  trigger_serial_port: auto
  trigger_serial_timeout_sec: 1.5
```

`trigger_serial_port: auto` 会枚举 Windows 当前可见的 COM 口，并通过 Neuracle 协议读取设备名称和设备信息。若实验电脑连接了多个串口设备，可以把该值改为 `COM3`，也可以在检查命令中临时传入 `--trigger-serial-port COM3`。波特率固定为 115200。

### 7.1 单独检查 TriggerBox

TriggerBox 接入并在 Windows 设备管理器中出现 COM 口后，先运行：

```powershell
& $PY psychopy_image_b_experiment.py --triggerbox-check-only
```

检查会读取设备名称和固件信息，然后发送测试事件码 254，并要求 TriggerBox 返回成功响应。该命令不连接 JellyFish，因此可把串口问题和 EEG 转发问题分开检查。存在多个 COM 口时运行：

```powershell
& $PY psychopy_image_b_experiment.py `
  --triggerbox-check-only `
  --trigger-serial-port COM3
```

如果显示“未检测到任何COM口”，说明问题发生在 Windows 识别层，需要检查 TriggerBox 供电、USB 数据线和 USB 串口驱动；此时修改程序内的端口号不能建立连接。如果显示“未找到可响应Neuracle协议的TriggerBox”，说明 COM 口存在，但所选端口不是 TriggerBox、端口被其他程序占用，或设备没有按 Neuracle TriggerBox 协议响应。

程序当前按 64 个 EEG 通道读取。JellyFish 转发的通道数必须不少于 64，采样率必须与 `sfreq` 一致。

### 7.2 检查 JellyFish 端口

本机 JellyFish：

```powershell
Test-NetConnection -ComputerName 127.0.0.1 -Port 8712
```

远程转发电脑：

```powershell
Test-NetConnection -ComputerName 'JellyFish电脑IP' -Port 8712
```

`TcpTestSucceeded` 应为 `True`。

### 7.3 同时检查 EEG 与 TriggerBox

```powershell
& $PY psychopy_image_b_experiment.py `
  --eeg-check-only `
  --real-eeg `
  --device-type neuracle
```

预检会先完成 TriggerBox 协议握手和测试事件码 254 回读，再调用 `connect(JellyFish所在电脑IP, 端口)` 连接 JellyFish、等待流元数据，并读取约 1 秒 EEG。默认端口为 8712；IP 和端口分别来自 `device.neuracle_host` 与 `device.neuracle_port`。

### 7.4 联通后进入正式实验

```powershell
& $PY psychopy_image_b_experiment.py `
  --preflight-eeg `
  --real-eeg `
  --device-type neuracle
```

### 7.5 修改远程地址

PsychoPy 入口目前没有独立的 `--neuracle-host`/`--neuracle-port` 参数。远程连接请先复制完整配置，再修改其中的 Neuracle 地址：

```powershell
Copy-Item .\config.yaml .\config.neuracle.yaml
```

至少确认以下字段；不要只用这段局部 YAML 覆盖整个文件，因为配置加载器要求顶层存在 `subject_id`、`device_type` 和 `sfreq`：

```yaml
device_type: neuracle
hardware_dummy_mode: false
sfreq: 250.0
device:
  neuracle_host: 192.168.1.20
  neuracle_port: 8712
```

然后运行：

```powershell
& $PY psychopy_image_b_experiment.py `
  --config .\config.neuracle.yaml `
  --preflight-eeg `
  --real-eeg `
  --device-type neuracle
```

如果提示 `Could not connect to JellyFish/Neuracle forwarder`：

1. 确认 JellyFish 已开始数据转发，而不只是打开软件。
2. 确认 IP、端口和 Windows 防火墙规则。
3. 确认采样率、设备型号和通道配置正确。
4. 重新执行 `Test-NetConnection` 和 `--eeg-check-only`。

## 8. LSL Marker 调试

### 8.1 发布 Marker 并等待 BCIGo

最直接的调试命令：

```powershell
& $PY psychopy_image_b_experiment.py `
  --eeg-check-only `
  --real-eeg `
  --device-type brainco `
  --brainco-transport bcigo `
  --brainco-lsl-timeout 60
```

命令运行期间，在 BCIGo 点击扫描。连接成功意味着 BCIGo 已作为 LSL consumer 打开 Marker Outlet。

### 8.2 从另一个终端确认 Marker 流可见

保持预检命令运行，在第二个 PowerShell 中执行：

```powershell
& $PY -c "from pylsl import resolve_byprop; ss=resolve_byprop('source_id','visual-video-task-marker',minimum=1,timeout=5); [print(s.name(),s.type(),s.source_id(),s.channel_count(),s.channel_format()) for s in ss]"
```

正常应看到类似：

```text
visual-video-task-Markers Markers visual-video-task-marker 1 int32
```

### 8.3 LSL 找不到流

依次检查：

1. 发布端程序是否仍在运行；程序退出后 LSL Outlet 会消失。
2. Windows 防火墙是否允许 Python、BCIGo 和专用网络通信。
3. 发布端与接收端是否在同一台电脑/同一可组播网络。
4. `streamName`、`type`、`sourceId` 是否完全一致。
5. 是否同时存在多个相同流；必要时使用 `sourceId` 精确匹配。

## 9. 配置文件说明

程序默认读取项目根目录的 `config.yaml`。常用字段：

experiment_config_locked: true 表示 rating 与 repetition 的实验身份由同一配置锁定。两种入口必须使用相同的被试编号、experiment_protocol 和 image_set_label；被试图片清单还会核对图片库、图片数、Block 大小和随机种子。Session 编号不要求相同：rating 固定为 Session 1，repetition 使用 Session 2 至 Session 6。

```yaml
subject_id: S001
experiment_protocol: formal500
session_id: 1
image_set_label: image_b_formal500_v2
experiment_config_locked: true
task_mode: image_b
device_type: brainco
hardware_dummy_mode: false
sfreq: 250.0
buffer_sec: 80.0

protocol:
  formal_image_library_dir: image_library/formal
  images_per_subject: 500
  block_size: 100
  random_seed: 17
  attention_probability: 0.05
  image_fixation_min_sec: 0.5
  image_fixation_max_sec: 0.8
  image_present_min_sec: 1.0
  image_present_max_sec: 1.5
  image_blank_sec: 0.5
  image_repeat_blank_min_sec: 0.1
  image_repeat_blank_max_sec: 0.1

device:
  brainco_transport: bcigo
  bcigo_marker_wait_timeout_sec: 60.0
  lsl_marker_enabled: true
  lsl_marker_stream_name: visual-video-task-Markers
  lsl_marker_stream_type: Markers
  lsl_marker_source_id: visual-video-task-marker
  neuracle_host: 127.0.0.1
  neuracle_port: 8712
  trigger_serial_port: auto
  trigger_serial_timeout_sec: 1.5

storage:
  records_dir: records_storage
  ratings_dir: ratings_storage
```

命令行参数只覆盖当前运行，不会自动改写 `config.yaml`。

## 10. 数据输出

### 10.1 本地 EEG 模式

BrainCo SDK、EEG-LSL、Neuracle 和模拟 EEG 会在 session 目录保存：

```text
continuous_eeg.npy
events.json
metadata.json
behavioral_ratings.csv
trial_log.csv
image_playlist.json
eeg_segments.json
```

中断恢复或同一 session 分段运行时可能出现：

```text
continuous_eeg_part_002.npy
events_part_002.json
metadata_part_002.json
```

`continuous_eeg.npy` 为通道优先数组：

```text
(n_channels, n_samples), float32
```

### 10.2 行为评分中断恢复

评分程序每完成一张图片就原子更新 `behavioral_ratings.csv` 和 `trial_log.csv`。旧版本强制退出后可能只留下 `.behavioral_ratings.checkpoint.csv` 或 `.behavioral_rating.checkpoint.csv`；两种名称都支持恢复。

恢复前先备份整个 session 目录，不要单独移动 checkpoint、`.resume_manifest.json` 或被试图片清单。使用相同项目配置和相同被试编号重新运行 `psychopy_image_b_rating.py`，程序会显示已完成的 trial 和下一 trial，并在继续前把旧 checkpoint 恢复为正式 CSV。完成剩余图片后，最终文件会包含恢复前后的全部评分。

检查 checkpoint 行数时可运行：

```powershell
(Import-Csv -LiteralPath '完整路径\.behavioral_rating.checkpoint.csv').Count
```

### 10.3 BCIGo 外部录制模式

项目 session 目录保存：

```text
events.json
metadata.json
behavioral_ratings.csv
trial_log.csv
image_playlist.json
eeg_segments.json
```

不会生成空的伪 `continuous_eeg.npy`。`metadata.json` 中会标记：

```json
{
  "eeg_recording_mode": "bcigo_external_edf",
  "local_eeg_recorded": false,
  "eeg_file": null
}
```

真正 EEG 位于 BCIGo EDF，Marker 码作为 EDF annotations 与 EEG 共用 BCIGo 时间轴。分析前应把对应 EDF 与项目 session 目录配对归档。

允许多个 session 共用同一个 EDF：第一轮前开始录制，全部 session 完成后停止。项目通过每轮的 `session_start`/`session_end` Marker 保留分段边界。

## 11. 通用 CLI 工具

除 PsychoPy 入口外，项目还提供 Click CLI：

这组工具不是正式 `image_b` 实验的必需项。当前已验证的 PsychoPy 环境未安装 `click`；如需使用，先检查：

```powershell
& $PY -c "import click, rich, pandas, streamlit; print('optional CLI dependencies: OK')"
```

缺少时安装可选界面依赖：

```powershell
& $PY -m pip install click rich pandas streamlit
```

然后运行：

```powershell
& $PY cli.py --help
```

常用命令：

```powershell
# 启动 Streamlit 界面
& $PY cli.py gui

# 列出硬件后端
& $PY cli.py list-devices

# 列出 Trigger 码
& $PY cli.py list-triggers

# 对本地 EEG 输入模式读取数据窗口；不适用于 bcigo 外部录制模式
& $PY cli.py probe-device --device neuracle --duration 5

# 运行短协议/导出检查
& $PY cli.py dry-run --trials 2
```

如果执行过项目安装，也可以用脚本入口：

```powershell
video-eeg --help
```

当前 `image_b` 正式采集优先使用 `psychopy_image_b_experiment.py`；Streamlit 界面主要保留给旧视频流程和配置操作。

## 12. 常见问题

### BCIGo 已录制，但 `records_storage` 没有 EEG

这是 `brainco_transport: bcigo` 的正常行为。到 BCIGo 的 EDF 保存目录查找 `.edf`；项目目录只保存行为数据和事件时间线。

### 是否需要每轮 session 都重新开始 BCIGo 录制

不需要。第一轮前开始一次录制，连续完成所有 session，最后再停止即可。实验程序不会发出停止录制指令，也不会在 session 结束时等待或复制 EDF。

### BCIGo 能看到 Marker，但实验提示没有 EEG LSL

说明使用了错误的 `--brainco-transport lsl`。当前 BCIGo 工作流应使用：

```text
--brainco-transport bcigo
```

### BrainCo SDK 找不到设备

先关闭 BCIGo，再依次检查：

```powershell
& $PY brainco_device_doctor.py --scan-seconds 8
& $PY psychopy_image_b_experiment.py --eeg-check-only --real-eeg --device-type brainco --brainco-transport sdk --brainco-scan-timeout 15 --brainco-ready-timeout 30
```

### Neuracle 连接被拒绝

先运行：

```powershell
Test-NetConnection -ComputerName 127.0.0.1 -Port 8712
```

如果失败，问题在 JellyFish 未转发、地址/端口或防火墙，而不是 PsychoPy 图片流程。

### PowerShell 显示 `profile.ps1 cannot be loaded`

这是本机 PowerShell 执行策略产生的启动噪声，通常与 EEG 连接失败无关。应继续查看命令后面的真实异常信息。

## 13. 正式实验前检查表

- 使用 `D:\ProgramData\miniconda3\envs\psychopy_env\python.exe`。
- 先完成模拟 EEG 短流程。
- 核对 `subject_id`、`session_id`、图片集合和试次数。
- 使用真实设备时先运行 `--eeg-check-only` 或 `--preflight-eeg`。
- BCIGo 模式确认 Marker 已连接；第一轮前开始一次 EDF 录制，后续 session 保持连续录制。
- Neuracle 模式确认 JellyFish 正在转发且端口可达。
- 检查采样率和通道数是否匹配。
- 全部 session 结束后停止 BCIGo，并核对各 session 行为/事件目录与连续 EDF 是否存在。

## 运行时内存与稳定性保护

rating 与 repetition 共用同一个稳定性实现。图片和评分控件在窗口创建后复用，程序不再为每个评分刷新帧或每张图片持续创建新的 PsychoPy 刺激对象；窗口关闭前会主动释放图片纹理。repetition 的连续 EEG 数据直接写入临时文件，内存中不保存整段 EEG，临时文件按固定周期刷新以避免高频磁盘同步造成界面阻塞。

程序每完成 5 张图片会在当前 session 目录原子更新 `memory_usage.csv`，记录进程 RSS、相对启动时的增长量、系统剩余可用内存、事件数和完成行数。若内存压力连续两次超过配置阈值，或检测到结果行数、事件数异常增长，程序会在本张图片的 `behavioral_ratings.csv` 与 `trial_log.csv` 已经保存后安全退出，随后可按原被试编码从断点继续。

稳定性阈值位于 `config.yaml` 的 `protocol` 节点，包括 `memory_check_every_trials`、`memory_max_rss_mb`、`memory_max_growth_mb`、`memory_min_available_mb` 和 `memory_max_events`。正式实验电脑的 `psychopy_env` 必须包含 `psutil`；项目依赖已声明 `psutil>=5.9`。

逐张 CSV 保存使用临时文件与原子替换，并针对 Windows 杀毒软件或索引器造成的短暂文件锁自动重试。实验运行期间不要使用 Excel、WPS 或其他会独占文件的程序打开当前 session 的 `behavioral_ratings.csv`、`trial_log.csv` 或 `memory_usage.csv`；需要查看时应复制文件后打开副本。