# Video EEG Paradigm

独立 PsychoPy 视频 EEG 范式。正式实验使用 1000 Hz BrainCo SDK 直连采集 EEG，固定 17 个
duration-balanced Session；Demo 使用模拟 EEG 和独立短流程。

## 环境配置

Windows 10/11 64 位电脑：完整解压源码，双击 `scripts/install_lab_env_uv.bat`。
安装器可自动下载项目本地 Python 3.12 和依赖，不要求预装 Python 或 Node.js。
首次安装需联网；已有健康环境直接复用。安装日志在 `logs/`。

- [详细操作说明](docs/OPERATOR_MANUAL.zh-CN.md)：安装、材料放置、Demo、正式采集、续跑、数据与排错。
- [实验说明](docs/EXPERIMENT_DESCRIPTION.zh-CN.md)：流程、抽查协议、采集与质控解释。
- [本次维护记录](docs/MAINTENANCE_LOG_20260908.md)：审计、清理、验证和发布状态。

## 快速启动

双击根目录入口：

```text
run_video_demo.bat
run_video_formal.bat
```

也可以双击 `scripts/` 目录中的同名脚本。

正式 Session 保留原 7949 个视频的 17 组分配，每组从已有题的视频中随机抽查 18 次，
问题针对刚完整播放的视频，按 1–4 或 A–D 作答。Demo 为 10 个视频、3 次抽查。
新正式数据保存在 `data/video_question_complete_runs`；历史记录保留。
旧 2779 题正式 Session 用 `run_video_legacy_2779.bat` 续跑。

**题库审计：** 当前有 7993 道题，覆盖 7946/7949 个正式视频；仍缺 `5728.mp4`、`6722.mp4`、
`6883.mp4`。原复核通过 2779 道，新增 5214 道尚未独立复核。缺题的视频仍播放，但不被抽查。
详见 [覆盖统计](video_eeg/config/complete_questions_20260908/coverage_audit.json)。

## 目录结构

```text
docs/                  # 配置、数据和实现说明
scripts/               # 启动、环境安装和维护脚本
stimuli/videos/        # 视频刺激材料
video_eeg/             # 视频 EEG 范式源码
  config/              # demo/正式 YAML 配置与固定 Session manifest
  devices/             # BrainCo、LSL、Neuracle、模拟采集后端
  experiment/          # session 运行、marker 调度和实验流程
  storage/             # 行为、事件和 EEG 文件写出
  utils/               # marker、视频库和通用工具
data/video_question_complete_runs/ # 当前视频抽查实验输出
data/sourcedata/       # 旧实验历史数据
tests/                 # 自动化测试
```

## 视频材料

请将正式和 demo 视频放入：

```text
stimuli/videos/
```

Demo 默认从该目录随机抽取 10 个合法视频，不重复播放。正式实验按照版本化的
`video_eeg/config/session_manifest.csv` 读取对应 Session 的固定视频集合；超过 60 秒的候选素材仅在
`video_eeg/config/formal_excluded_over_60s.csv` 中审计记录，不从共享母库物理删除。
也支持实验室现有的 `../video_materials/formal_v1/videos` 母库布局。
源码包不包含正式视频和受试者数据；正式采集前须从实验室复制材料。
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

