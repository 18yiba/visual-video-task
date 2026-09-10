# Video EEG Paradigm

独立 PsychoPy 视频 EEG 范式。正式实验使用 1000 Hz BrainCo SDK 直连采集 EEG，固定 34 个
duration-balanced Session；Demo 使用模拟 EEG 和独立短流程。

## 环境配置

Windows 10/11 64 位电脑：完整解压源码，双击根目录 `install_lab_env_uv.bat`（转发至 `scripts/install_lab_env_uv.bat`）。
安装器可自动下载项目本地 Python 3.12 和依赖，不要求预装 Python 或 Node.js。
首次安装需联网；已有健康环境直接复用。安装日志在 `logs/`。

- [详细操作说明](docs/OPERATOR_MANUAL.zh-CN.md)：安装、材料放置、Demo、正式采集、续跑、数据与排错。
- [实验说明](docs/EXPERIMENT_DESCRIPTION.zh-CN.md)：流程、抽查协议、采集与质控解释。
- [本次维护记录](docs/MAINTENANCE_LOG_20260908.md)：审计、清理、验证和发布状态。

## 快速启动

完整视频附件已公开，见 [材料发布状态](docs/MATERIALS_UPLOAD_STATUS.md)。

首次使用：**安装环境 → 下载视频 → Demo → 正式采集**。
环境就绪后双击 `download_materials.bat`，自动获取并校验约 44.2 GB 的完整视频库。
[统一视频下载页](https://github.com/18yiba/visual-video-task/releases/tag/materials-v1-20260910)
· [下载、放置与校验说明](docs/MATERIALS_DOWNLOAD.zh-CN.md)。
未下载真实视频时也可以先用合成 Demo 检查环境。

双击根目录入口：

```text
run_video_demo.bat
run_video_formal.bat
```

也可以双击 `scripts/` 目录中的同名脚本。

正式 Session 保留原 7949 个视频，改为 34 组，每组从已有题的视频中随机抽查 18 次，
问题针对刚完整播放的视频，按 1–4 或 A–D 作答。Demo 为 10 个视频、3 次抽查。
新正式数据保存在 `data/video_question_complete_runs/protocol_34sessions`；历史记录保留。
每组视频净时长 88.35–88.94 分钟（平均 88.76 分钟），每组均有五档长短视频。
原第 n 组拆为新第 2n−1、2n 组；每组内部随机播放，续跑保持原顺序。没有 90 分钟强制结束计时。
注视点、答题和休息额外计时，实际实验总时长会更长。
[34 组时长与分桶统计](video_eeg/config/session_34_summary.csv) · [分组与标签审计](docs/SESSION_34_AND_LABEL_AUDIT.zh-CN.md)。
旧完整版 17 组用 `run_video_legacy_17.bat` 续跑，仍读取原 `data/video_question_complete_runs/<subject>`。
旧 2779 题正式 Session 用 `run_video_legacy_2779.bat` 续跑。

**题库审计：** 当前有 7993 道题，覆盖 7946/7949 个正式视频；仍缺 `5728.mp4`、`6722.mp4`、
`6883.mp4`。原复核通过 2779 道，新增 5214 道尚未独立复核。缺题的视频仍播放，但不被抽查。
详见 [覆盖统计](video_eeg/config/complete_questions_20260908/coverage_audit.json)。

## 目录结构

```text
docs/                  # 配置、数据和实现说明
scripts/               # 启动、环境安装和维护脚本
stimuli/videos/        # 视频下载到这里；源码仅含空 .gitkeep
video_eeg/             # 视频 EEG 范式源码
  config/              # demo/正式 YAML 配置与固定 Session manifest
  devices/             # BrainCo、LSL、Neuracle、模拟采集后端
  experiment/          # session 运行、marker 调度和实验流程
  storage/             # 行为、事件和 EEG 文件写出
  utils/               # marker、视频库和通用工具
data/video_question_complete_runs/ # 仓库仅含空 .gitkeep，本地记录不上传
  protocol_34sessions/ # 新 34 组正式输出，运行时自动生成
data/sourcedata/       # 旧数据兼容目录；仓库仅含空 .gitkeep
tests/                 # 自动化测试
```

## 视频材料

请将正式和 demo 视频放入：

```text
stimuli/videos/
```

Demo 默认从该目录随机抽取 10 个合法视频，不重复播放。正式实验按照版本化的
`video_eeg/config/session_manifest_34.csv` 读取对应 Session 的固定视频集合；超过 60 秒的候选素材仅在
`video_eeg/config/formal_excluded_over_60s.csv` 中审计记录，不从共享母库物理删除。
也支持实验室现有的 `../video_materials/formal_v1/videos` 母库布局。
源码包不包含正式视频和受试者数据。完整母库放在同一仓库的版本化 Release 中：84 个独立视频 ZIP、
配套题库快照及 SHA-256 清单。推荐双击 `download_materials.bat` 自动处理；
手动下载须把全部视频包解压到 `stimuli`，最终得到 `stimuli/videos/0001.mp4`，不要多套一层目录。
详情见 [材料下载说明](docs/MATERIALS_DOWNLOAD.zh-CN.md)。
无真实母库时 Demo 自动使用安装器生成的十段合成练习视频，仍验证三次答题和模拟 EEG。
正式入口缺材料时停止，不以练习片代替。

## 当前采集模式

正式实验：

```text
BrainCo SDK 直连 + 本地连续 EEG 记录
```

配置文件：

```text
video_eeg/config/video_config.yaml
video_eeg/config/video_demo_config.yaml
```

更多说明见 `docs/`。

## 开发验证与发布

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe scripts\audit_question_bank.py --require-materials
.\.venv\Scripts\python.exe scripts\build_release.py ..\release-source --zip ..\visual-video-task-source.zip
```

打包脚本采用源文件白名单，不包含实验数据、正式视频、密码、缓存或环境。
数据质量说明参考 [oi-eegqc](https://github.com/Omni-Intel/oi-eegqc)，本程序未自动集成其评分。

