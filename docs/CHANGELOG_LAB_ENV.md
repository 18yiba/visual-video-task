# 实验室电脑环境修改日志

## 2026-08-27

### 1. 文件夹迁移

项目迁移到实验室电脑：

```text
D:\Users\EDY\Desktop\visual-video-task-master
```

当前截图和报错显示，实验室电脑上存在多层同名文件夹嵌套。实际运行脚本曾位于：

```text
D:\Users\EDY\Desktop\visual-video-task-master\visual-video-task-master\visual-video-task-master
```

当前虚拟环境使用目录为：

```text
D:\Users\EDY\Desktop\visual-video-task-master\visual-video-task-master\.venv
```

### 2. 旧虚拟环境不可用

复制过去的 `.venv` / `.venv_old` 曾报错：

```text
No Python at '"D:\Python\python.exe'
```

原因：复制来的虚拟环境绑定了原电脑上的 Python 路径，不能直接跨电脑使用。

处理方式：在实验室电脑重新创建 `.venv`。

### 3. 重新创建虚拟环境

在实验室电脑重新创建过虚拟环境：

```powershell
py -3.12 -m venv .venv
```

环境检查变量：

```powershell
$PY = 'D:\Users\EDY\Desktop\visual-video-task-master\visual-video-task-master\.venv\Scripts\python.exe'
```

### 4. 安装基础运行包

安装过当前视频范式运行所需包，包括：

```text
psychopy
numpy
scipy
opencv-python
imageio-ffmpeg
sounddevice
soundfile
brainflow
bcigo-sdk
pylsl
psutil
pyserial
pyyaml
zeroconf
json-tricks
pywin32
pillow
```

### 5. 补装 PsychoPy 缺失依赖

运行中陆续发现并补装：

```text
i18next
python-bidi
pandas
pyqt6
```

对应报错包括：

```text
ModuleNotFoundError: No module named 'i18next'
ModuleNotFoundError: No module named 'bidi'
ModuleNotFoundError: No module named 'pandas'
NameError: name 'QtWidgets' is not defined
```

### 6. 修复 pyglet 字体渲染问题

启动范式时曾报错：

```text
ctypes.ArgumentError: argument 5: TypeError: expected LP_c_ubyte instance instead of c_byte_Array_3520
```

修改实验室电脑虚拟环境中的文件：

```text
D:\Users\EDY\Desktop\visual-video-task-master\visual-video-task-master\.venv\Lib\site-packages\pyglet\font\win32.py
```

先备份：

```text
win32.py.bak
```

修改内容：

```python
self._data = (ctypes.c_byte * (4 * width * height))()
```

改为：

```python
self._data = (ctypes.c_ubyte * (4 * width * height))()
```

### 7. 删除过但后来确认不能删的包

曾卸载：

```text
moviepy
matplotlib
pandas
openpyxl
pyarrow
questplus
xarray
tables
python-vlc
pyparallel
pyqt6
```

后来确认以下包不能删除，因为当前 PsychoPy 的 `gui` 模块启动依赖它们：

```text
pandas
pyqt6
```

已重新安装：

```text
pandas
pyqt6
```

### 8. 当前建议保留的关键包

当前视频范式建议保留：

```text
psychopy
numpy
scipy
pillow
pyglet
opencv-python
imageio-ffmpeg
sounddevice
soundfile
brainflow
bcigo-sdk
pylsl
psutil
pyserial
pyyaml
zeroconf
pywin32
pypiwin32
json-tricks
i18next
python-bidi
pandas
pyqt6
```

### 9. 当前可不安装或可删除的包

如果只运行当前视频范式，以下包暂时不是必要项：

```text
moviepy
matplotlib
openpyxl
pyarrow
questplus
xarray
tables
python-vlc
pyparallel
```

### 10. 当前环境测试命令

使用以下命令测试完整导入：

```powershell
$PY = 'D:\Users\EDY\Desktop\visual-video-task-master\visual-video-task-master\.venv\Scripts\python.exe'

& $PY -c "from psychopy import core, event, gui, visual; import scipy, cv2, sounddevice, soundfile, bidi, i18next; print('full environment ok')"
```

如果输出：

```text
full environment ok
```

说明当前 Python 环境基本可用于双击运行范式。

### 11. 维护规则

之后每次实验室电脑执行新的安装、卸载、环境修复、代码补丁或启动器调整，都继续追加到本文件，保留命令、报错和处理结果。

### 12. 追加 uv 批量部署方案

新增用于多台实验室电脑批量配置环境的文件：

```text
lab_uv_env.toml
install_lab_env_uv.bat
scripts\patch_pyglet_win32.py
```

设计目标：

- 保留实验室电脑跑通前所需的完整环境包，不再精简删除。
- 用 `uv` 自动创建 `.venv`。
- 用 `uv` 安装 `lab_uv_env.toml` 中记录的运行依赖。
- PsychoPy 使用 `--no-deps` 单独安装，避免 `pywinhook` / 旧版依赖导致安装失败。
- 自动修复 `pyglet\font\win32.py` 中的 `ctypes.c_byte` 字体渲染问题。

新电脑最简安装流程：

```powershell
Set-Location 'D:\Users\EDY\Desktop\visual-video-task-master\visual-video-task-master'
.\install_lab_env_uv.bat
```

如果电脑还没有 `uv`，先安装：

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

安装完成后测试命令由脚本自动执行：

```powershell
from psychopy import core, event, gui, visual
import scipy, cv2, sounddevice, soundfile, bidi, i18next
```

输出 `full environment ok` 表示环境可用。

### 13. 修正 uv 一键部署脚本

`install_lab_env_uv.bat` 已改为更适合批量电脑部署的流程：

```text
1. 自动检测 uv。
2. 如果没有 uv，自动安装 uv。
3. 自动调用 uv 安装 Python 3.12。
4. 自动创建 .venv。
5. 单独用 --no-deps 安装 psychopy==2026.2.2。
6. 从 lab_uv_env.toml 读取 runtime 依赖并安装。
7. 自动执行 scripts\patch_pyglet_win32.py 修复 pyglet 字体后端。
8. 自动运行完整导入测试。
```

因为 `uv pip install -r ... --extra runtime` 官方识别的是 `pyproject.toml` 项目文件格式，脚本会临时把 `lab_uv_env.toml` 复制到：

```text
.uv_lab_env\pyproject.toml
```

再执行安装。这样保留 `lab_uv_env.toml` 作为实验室环境清单，同时不修改项目原本的 `pyproject.toml`。

### 14. 修复 lab_uv_env.toml 编码

复查时发现 `lab_uv_env.toml` 需要按标准 UTF-8 无 BOM 保存，避免 TOML 解析器把文件开头识别成非法字符。已重新写入编码，并用 Python 3.12 验证：

```powershell
py -3.12 -c "import tomllib, pathlib; p=pathlib.Path(r'C:\Users\Princess Sophia\Desktop\visual-video-task-master\visual-video-task-master\lab_uv_env.toml'); tomllib.loads(p.read_text(encoding='utf-8')); print('toml ok')"
```

验证结果：

```text
toml ok
```

### 15. 增强 install_lab_env_uv.bat 的坏环境处理

`install_lab_env_uv.bat` 现在会检查：

```text
.venv\Scripts\python.exe
```

如果文件存在但无法运行，例如再次出现：

```text
No Python at 'D:\Python\python.exe'
```

脚本不会删除旧环境，而是把 `.venv` 改名备份为 `.venv_broken` 或 `.venv_broken_随机数`，再重新创建新的 `.venv`。

### 16. 切换为 BCIGo 外部 EEG 录制 + LSL Marker

视频范式正式实验现在固定使用：

```text
BCIGo：连接脑电设备并录制 EDF
视频程序：通过 LSL 发送 Marker
Python：不通过 bcigo_sdk 读取 EEG
```

已修改：

- `video_config.yaml` 保持 `brainco_transport: bcigo`。
- 保持 `lsl_marker_enabled: true`。
- 新增 `bcigo_marker_start_timeout_sec: 5.0`。
- `run_video_formal.bat` 强制传入：

```text
--real-eeg --device-type brainco --brainco-transport bcigo
```

- 正式实验默认启动前执行 LSL Marker 预检。
- 预检阶段要求 BCIGo 已经选中 Marker 流。
- Session 真正开始前再次确认 Marker 消费者仍然存在。
- 如果 Marker 流断开，程序不会开始播放视频。
- 结果 metadata 会记录：

```text
bcigo_external_edf_with_lsl_markers
```

正式实验使用的 Marker 流：

```text
name: video-eeg-Markers
type: Markers
source_id: video-eeg-marker
```

验证结果：

```text
py_compile: passed
unittest: 9 tests passed
```

实验员仍需在 BCIGo 中手动开始 EDF 录制；Python 程序只能确认 Marker 流已被订阅，不能确认 BCIGo 是否已经点击开始录制 EDF。

### 17. 恢复为 BrainCo SDK 直连模式（2026-08-31）

应实验方案调整，视频范式从“BCIGo 外部 EDF + LSL Marker”恢复为原来的“BrainCo SDK 直连 + 本地连续 EEG 记录”模式。

已修改：

- `video_config.yaml`：`brainco_transport: sdk`
- `video_config.yaml`：`lsl_marker_enabled: false`
- `video_demo_config.yaml`：`brainco_transport: sdk`
- `video_demo_config.yaml`：`lsl_marker_enabled: false`
- `run_video_formal.bat`：强制使用 `--real-eeg --device-type brainco --brainco-transport sdk`
- 移除正式实验默认的 LSL Marker 预检逻辑
- 移除 Session 开始前的外部 Marker 消费者检查
- metadata 恢复记录 SDK 模式下的本地连续 EEG 方式

LSL Marker 相关代码仍保留作为备用功能，但当前配置和启动器不会调用 LSL Marker。

验证结果：

```text
py_compile: passed
unittest: 9 tests passed
```

### 18. 重组项目目录结构（2026-08-31）

按 THINGS-EEG2-Extended 风格整理项目结构：

```text
docs/
scripts/
stimuli/videos/
video_eeg/
  config/
  devices/
  experiment/
  storage/
  utils/
data/sourcedata/
tests/
```

已完成：

- 移除同名嵌套项目目录。
- 将视频主程序移动到 `video_eeg/experiment/video_runner.py`。
- 将设备采集代码移动到 `video_eeg/devices/`。
- 将 session 数据写出代码移动到 `video_eeg/storage/`。
- 将 marker 和视频库工具移动到 `video_eeg/utils/`。
- 将配置文件移动到 `video_eeg/config/`。
- 将数据目录整理到 `data/sourcedata/`。
- 将启动、安装和维护脚本整理到 `scripts/`。
- 根目录保留 `run_video_demo.bat` 和 `run_video_formal.bat` 两个双击入口。
- 新增 `docs/CONFIGURATION.md`、`docs/DATA_MODEL.md`、`docs/IMPLEMENTATION.md`、`docs/EXPERIMENT_FLOW.md`。

验证结果：

```text
py_compile: passed
unittest: 9 tests passed
```

### 19. 修复目录重组后的 Demo 启动提示与本机 GUI 环境（2026-08-31）

目录重组后，视频库标准位置为：

```text
stimuli/videos/
```

本机运行 Demo 报错：

```text
RuntimeError: 没有可播放的合法视频，请将 5-60 秒视频放入 ...\stimuli\videos
```

检查结果：项目目录内没有实际实验视频文件，`stimuli/videos/` 为空。因此这不是代码写死到当前电脑路径的问题，而是视频库尚未放入新的标准目录。

已修改：

- `video_eeg/experiment/video_runner.py`：视频库为空时改为清晰提示并返回错误码，不再输出长 traceback。
- `stimuli/videos/README.md`：新增视频材料放置说明。
- `README.md` 和 `docs/CONFIGURATION.md`：补充视频库为空时的说明。
- 本机 `.venv` 补装 `PyQt6`，恢复 PsychoPy 图形化被试信息窗口。

验证结果：

```text
from psychopy import gui; import PyQt6: passed
py_compile: passed
unittest: 9 tests passed
```

注意：`pyglet\gl\wgl.py` 的 `SyntaxWarning: invalid escape sequence '\c'` 来自 pyglet 第三方包文档字符串，不影响当前视频范式启动。

### 20. 硬盘版 Demo 启动优化与正式实验 SDK 检测画面（2026-08-31）

目标目录：`E:\visual-video-task-master`。本次修改保持路径可移植，代码仍使用项目相对路径 `stimuli/videos/`、`data/sourcedata/`，没有写入本机或硬盘专属路径。

已修改：

- `video_eeg/utils/video_library.py`：Demo 随机选片改为先随机打乱候选视频，再只探测到足够 10 个合法视频为止；避免启动时对整个大型视频库逐个 ffmpeg/ffpyplayer 探测。
- `video_eeg/experiment/video_runner.py`：Demo 使用快速合法视频播放列表；正式实验在真正开始 EEG 采集前增加强脑 SDK 连接检测画面。
- `video_eeg/experiment/video_runner.py`：强脑 SDK 检测成功时显示设备名、通道数、采样率、读取到的样本数，并提示点击“开始实验”或按空格键进入正式实验；检测失败时显示错误信息，可点击“重试”/按 R 重试，或点击“退出”/按 Esc 退出。
- `scripts/run_video_demo.bat` 和 `scripts/run_video_formal.bat`：启动时设置 `PYTHONUTF8`、屏蔽第三方库 `SyntaxWarning`，并降低 Qt 非致命日志噪音，减少双击启动窗口里无关 warning 干扰。
- `tests/test_psychopy_video_experiment.py`：新增快速 Demo 选片回归测试，确认只探测到足够合法视频即停止，并保证 10 个视频不重复。

硬盘视频库实测：

```text
stimuli/videos/ 内约 3224 个视频
快速 Demo 选片：探测 23 个候选视频，约 4.7 秒选出 10 个合法且不重复视频
```

验证结果：

```text
py_compile: passed
unittest: 10 tests passed
```

### 21. 正式实验启动提速：取消全库时长预检（2026-08-31）

目标目录：`E:\visual-video-task-master`。本次修改仍保持可移植，程序使用项目相对路径，不绑定 U 盘盘符或某台电脑用户目录。

已修改：

- `video_eeg/config/video_config.yaml`：正式实验默认 `playlist_mode: shuffle`，视频顺序随机且不重复。
- `video_eeg/utils/video_library.py`：新增快速候选播放列表函数，正式实验启动前不再逐个探测全部视频时长。
- `video_eeg/experiment/video_runner.py`：正式实验在 `shuffle` 模式下直接随机生成候选播放列表；`本轮视频数=0` 表示播放库内全部视频，填写具体数字则随机抽取对应数量。
- `tests/test_psychopy_video_experiment.py`：新增测试，确认正式实验快速播放列表不会调用时长探测，且视频不重复。

影响说明：

- 启动速度明显加快，避免 3000+ 视频库在实验开始前长时间 ffmpeg/ffpyplayer 预扫描。
- 试次表仍记录实际播放时长和是否自然结束；预先字段 `video_duration_status` 对快速候选列表会是 `duration_unknown`。
- 如果某个视频文件本身损坏，仍会在播放该视频时被程序捕获并跳过，不会在启动前提前筛出。

验证结果：

```text
py_compile: passed
unittest: 11 tests passed
正式实验快速列表实测：10 个视频约 3.06 秒完成
```

### 22. 新增实验室环境配置 README（2026-08-31）

已新增：

- `docs/ENVIRONMENT_SETUP.md`：写明 U 盘复制到实验室电脑后的首次环境配置流程、uv 自动安装方式、手动 PowerShell 命令、正式实验启动方式和常见问题。
- `README.md`：新增环境配置入口，说明每台电脑只需首次配置一次，之后直接双击启动实验。
