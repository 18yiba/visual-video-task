# Video EEG 与情绪评分实验

当前新实验版本为 **Emotion EEG v2（2026年9月15日）**。保持45个固定Session、7,949段普通视频和3,138段情绪视频。
每组净视频约90.13–90.23分钟；评分、内容题和休息另计，没有90分钟强制截止。

## 当前流程

| 视频类型 | 视频自然结束后的流程 |
|---|---|
| 普通视频 | 喜好判断：F不喜欢，J喜欢 → 短休息 |
| 普通视频被抽中 | 喜好判断 → 对刚才视频的内容题（1–4或A–D）→ 紧接精神疲劳二分类（F/J）→ 短休息 |
| 情绪视频 | 效价1–7 → 唤醒1–7 → 短休息 |

每组9道内容题，约每10分钟净视频一道，只使用原普通库的完整版题库。初次队列按累计净视频10、20……90分钟目标，
在附近随机选取有题的普通视频并保存绑定；不会打断视频。休息和所有答题时间不计入这个计划。
重播或S重排会改变实际间隔，续跑保留同一计划；绝不对另一个视频补问前一段的题。

疲劳题：“请判断您此刻的精神状态。”F未感到明显的精神疲劳；J已感到明显的精神疲劳。
该题是文献启发的研究自编二分类，不是已经验证的临床量表，见[措辞与文献依据](docs/FATIGUE_BINARY_RATIONALE.zh-CN.md)。
情绪评分的中心锚点为4；效价1非常不愉快、7非常愉快；唤醒1非常平静、7非常激动。所有作答不限时。

## 新电脑从GitHub安装

1. Windows 10/11 64位，完整解压本仓库源码到可写本地目录，例如 `D:/Experiments/visual-video-task`；不要在ZIP预览里运行。
2. 双击根目录 `install_lab_env_uv.bat`，它转发到 `scripts/install_lab_env_uv.bat`，再调用同目录PS1。
   首次安装需要联网访问uv、Python和PyPI；自动准备Python3.12、项目环境及全部依赖，不需要Node.js。
   已有健康环境可复用。安装日志位于 `logs/install_*.log`。
3. 双击 `run_video_emotion_demo.bat`。自动生成4段合成练习视频，包含1次喜好、1道练习内容题、1次疲劳和6页七级情绪评分。
   Demo使用模拟EEG，不需要完整正式材料，也不能用于正式数据。
4. 准备下述两套正式材料，双击 `check_emotion_materials.bat`；全部文件、ffprobe和情绪SHA256检查通过。
5. 检查真实设备连接、BCIGo阻抗、电量、样本增长、声音及数据盘空间，完成真实设备短测。
6. 双击 `run_video_emotion_formal.bat`，填写被试编号与Session 1–45。正式默认BrainCo SDK直连、1000Hz，禁止dummy数据冒充正式采集。

离线实验室已有17/34组或九级45组：使用[硬盘快速更新说明](docs/OFFLINE_EMOTION_V2_UPDATE.zh-CN.md)，无需联网重装或先升级到34组。

## 正式材料如何取得与放置

源码ZIP不包含视频、环境或被试数据。普通母库与情绪库是两套材料：

- 普通库：双击 `download_materials.bat`，从[版本化材料Release](https://github.com/18yiba/visual-video-task/releases/tag/materials-v1-20260910)下载到 `stimuli/videos`。
  84个分包，7,996段母库文件，约44.2 GB；固定清单使用其中7,949段。也可复用项目旁 `video_materials/formal_v1/videos`。
- 情绪库：复制本实验最终核验的 `emotion_video/selected`，3,138段、约9.87 GB，并保留最终metadata用于追踪。
  该库不在普通Release中。唯一原始来源为[官方Conna/eMotions](https://huggingface.co/datasets/Conna/eMotions)的parquet `video_data`。
  本仓库的 `emotion_source_index_v1.csv` 保留最终ID、chunk、SHA256及相对路径；没有现成实验室副本时须从官方材料恢复这些最终文件并校验。
  不使用最初抽样计划代替最终清单，不重新抽样或自行补充第三方视频。

```text
实验目录/
  visual-video-task/
    run_video_emotion_formal.bat
    run_video_emotion_demo.bat
    check_emotion_materials.bat
    stimuli/videos/                 # 普通库可以放这里
    video_eeg/config/
  video_materials/formal_v1/
    videos/                         # 普通库另一种位置，二选一
    emotion_video/
      selected/
        positive/excitation/*.mp4
        positive/relaxation/*.mp4
        neutral/neutral/*.mp4
        negative/fear/*.mp4
        negative/sad/*.mp4
        negative/tension/*.mp4
      metadata/selected_videos.csv
```

其他硬盘路径：在项目根目录创建 `emotion_library.local.json`，例如 `{"emotion_root":"F:/Materials/emotion_video"}`。
字段指向包含selected的目录，不是selected本身。环境变量 `VIDEO_EEG_EMOTION_ROOT` 优先于该文件，再次优先于YAML默认路径。
本机路径文件不上传GitHub。不要改名、裁剪、转码或重分组材料。运行日志 `logs/emotion_material_audit.json` 应无失败文件。
文件数量检查只能快速定位材料，不能替代完整SHA256与ffprobe审计。

## 完整默认配置

正式配置 `video_eeg/config/video_emotion_config.yaml` 全文如下。程序入口默认读取它；实验室离线包会读取旧机设备参数并绑定该机已有普通库。
任何正式采集前的修改均应登记版本；已有Session的题库、成员、评分量尺和抽查策略不能随意改变。

```yaml
subject_id: S001
session_id: 1
device_type: brainco
hardware_dummy_mode: false
sfreq: 1000.0
eeg_sampling_rate_hz: 1000.0
buffer_sec: 180.0
protocol:
  fixation_sec: 1.5
  default_video_sec: 60.0
  formal_max_video_duration_sec: 60.0
  post_video_rest_seconds: 2.0
  num_sessions: 45
  attention_tasks_per_session: 9
  attention_enabled: true
  rest_min_net_minutes: 30
  rest_max_net_minutes: 45
  attention_timeout: null
  session_manifest_path: video_eeg/config/session_manifest_emotion_v1.csv
  formal_exclusion_report_path: video_eeg/config/formal_excluded_over_60s.csv
  duration_bucket_count: 5
  video_library_dir: ../video_materials/formal_v1/videos
  video_library_mode: local
  playlist_mode: shuffle
  random_seed: 20260912
  kind: emotion-v2
  trials_per_session: 0
  session_manifest: video_eeg/config/session_manifest_emotion_v1.csv
  emotion_library_dir: ../video_materials/formal_v1/emotion_video
  alarm_interval_net_sec: 600
  rating_scale_max: 7
  question_bank_path: video_eeg/config/complete_questions_20260908/question_bank.json
device:
  neuracle_host: 127.0.0.1
  neuracle_port: 8712
  neuracle_eeg_channels: 64
  neuracle_include_trigger_channel: true
  brainco_addr: ''
  brainco_port: 0
  brainco_auto_discover: true
  brainco_scan_timeout_sec: 6.0
  brainco_ready_timeout_sec: 20.0
  brainco_start_retries: 2
  brainco_gain: 6
  brainco_signal_source: NORMAL
  brainco_device_id: bcigo
  brainco_transport: sdk
  bcigo_marker_wait_timeout_sec: 60.0
  brainco_lsl_stream_name: ''
  brainco_lsl_stream_type: EEG
  brainco_lsl_source_id: ''
  brainco_lsl_resolve_timeout_sec: 15.0
  brainco_lsl_ready_timeout_sec: 10.0
  lsl_marker_enabled: false
  lsl_marker_stream_name: video-eeg-Markers
  lsl_marker_stream_type: Markers
  lsl_marker_source_id: video-eeg-marker
  trigger_serial_port: ''
  trigger_serial_timeout_sec: 1.5
storage:
  records_dir: data/video_emotion_eeg_runs/protocol_emotion_v2
demo_mode: false
```

### 参数解释和覆盖顺序

| 配置 | 用途与注意事项 |
|---|---|
| subject_id、session_id | 启动默认值；对话框/命令行选定本次编号和固定组 |
| device_type、hardware_dummy_mode | 后端与模拟开关；正式必须真实，Demo强制模拟 |
| sfreq、eeg_sampling_rate_hz、buffer_sec | 默认采样率1000Hz和缓冲180秒；按实际设备核对 |
| fixation_sec、post_video_rest_seconds | 注视1.5秒、短休息2秒；短休息可空格提前结束 |
| default_video_sec、formal_max_video_duration_sec | 默认时长回退和正式旧库排除参数；正式仍按固定清单、自然结束播放，不截断材料 |
| num_sessions、trials_per_session | 正式45组，trials_per_session=0不截取该组；Demo4段 |
| attention_enabled、attention_tasks_per_session | V2必须开启；正式9次，Demo1次 |
| alarm_interval_net_sec | 正式600秒目标间隔；Demo10秒便于快速覆盖；计划只初始化一次 |
| attention_timeout | null，不限时；V2页面不设自动作答超时 |
| rating_scale_max | V2固定7，修改为9会拒绝；九级使用明确的V1兼容入口 |
| kind | emotion-v2，决定流程和恢复协议类型 |
| session_manifest、session_manifest_path | 复用V1的45组成员清单，文件名v1表示材料分组版本，并不表示评分仍为九级 |
| formal_exclusion_report_path、duration_bucket_count | 旧母库时长排除记录和五档长度分层 |
| video_library_dir、video_library_mode | 普通库根目录和本地读取；项目stimuli/videos是便携回退位置 |
| emotion_library_dir | 包含selected的情绪库目录；允许本机JSON和环境变量覆盖 |
| playlist_mode、random_seed | 组内随机；首次顺序与实际种子存入状态，正式默认另产生并保存被试运行种子；续跑不重抽 |
| question_bank_path | 完整版原视频题库，保存SHA256与快照；不混用2779题版本 |
| rest_min_net_minutes、rest_max_net_minutes | 实际视频累计约30–45分钟，在视频与作答结束边界提示长休息 |
| device.brainco_transport | sdk直连；也支持框架已有lsl或bcigo外部录制方式，须按设备实际配置 |
| brainco_addr、brainco_port、brainco_auto_discover | SDK设备定位与自动发现；空地址、0端口使用发现流程 |
| brainco_scan_timeout_sec、brainco_ready_timeout_sec、brainco_start_retries | SDK扫描、就绪超时与启动重试 |
| brainco_gain、brainco_signal_source、brainco_device_id | SDK增益、信号源及设备标识，按实际硬件核对 |
| bcigo_marker_wait_timeout_sec | 外部BCIGo模式等待marker就绪超时 |
| brainco_lsl_stream_name/type/source_id | LSL筛选条件；空值表示不按该字段限定 |
| brainco_lsl_resolve_timeout_sec、brainco_lsl_ready_timeout_sec | LSL发现与就绪超时 |
| neuracle_host/port/eeg_channels/include_trigger_channel | Neuracle网络后端参数；使用该后端时按现场填写 |
| lsl_marker_enabled、lsl_marker_stream_name/type/source_id | 是否额外发送LSL事件及其流标识 |
| trigger_serial_port、trigger_serial_timeout_sec | 可选串口触发器；空端口表示不启用该串口后端 |
| storage.records_dir | V2独立数据根目录，不得指向V1、旧17/34组状态 |
| demo_mode | 正式false，Demo true；Demo记录另行保存 |

页面文字、F/J映射及七级量尺属于固定协议，定义于 `video_eeg/experiment/emotion_v2_runner.py`，不是现场自由修改的设备参数。
F/J在喜好与疲劳页表示左/右选项，在长休息页表示继续/保存退出；以当前页面说明为准。
数字键可用主键盘；七级评分也接受小键盘num_1至num_7，8/9不作答；内容题使用1–4或A–D。

默认formal BAT显式指定BrainCo SDK。其他后端或诊断可在项目目录的PowerShell调用：

```powershell
.\.venv\Scripts\python.exe -m video_eeg.experiment.emotion_runner --help
.\.venv\Scripts\python.exe -m video_eeg.experiment.emotion_runner --config video_eeg/config/video_emotion_config.yaml --real-eeg --device-type neuracle
.\.venv\Scripts\python.exe scripts/check_video_eeg_env.py
```

自定义正式YAML可通过 `VIDEO_EEG_EMOTION_CONFIG` 指定config目录中的文件名；常规双击不需设置变量。
参数层次为YAML→入口和命令行覆盖→启动对话框的编号与Session；情绪库另按上述本机路径优先级解析。
依赖清单为 `lab_uv_env.toml`、`requirements-psychopy.txt` 和 `pyproject.toml`；安装器负责部署及依赖检查，不依赖开发电脑盘符。

## 休息恢复和数据

短休息2秒可空格提前继续；长休息F继续、J保存退出。Esc安全退出。S暂跳并重排，未完成内容会重播。
普通视频连同喜好及可能的内容题/疲劳一起提交；情绪视频连同两项评分一起提交。作答中止保留部分attempt，下次完整重播并重答。
EEG在视频、作答、休息间连续记录。休息时钟计入实际观看及重播，完成进度另按已提交视频计算。

数据根目录 `data/video_emotion_eeg_runs/protocol_emotion_v2/<subject>/session_XX`。
`session_state.json`为权威恢复状态；`trial_log.csv`为观看尝试；`emotion_rating_log.csv`含量尺上下限与版本；
`video_liking_log.csv`记录喜好；`video_question_log.csv`记录内容题及正确性；`fatigue_log.csv`记录疲劳；
`ordinary_behavior_log.csv`将同一普通视频尝试的所有行为放在一行。分析选择completed=True的最终attempt，空值不等于0。
详细事件码、时间字段及EEG分段说明见[完整V2协议](docs/EMOTION_EEG_V2_PROTOCOL.zh-CN.md)。

不要用Excel占用正在写出的CSV，不要手动修改状态或题库快照。CSV占用时程序尝试另存.recovered时间戳文件；
磁盘写入失败、断电和设备异常仍需主试处理。程序没有按疲劳选择、阻抗变红或答题正确率自动停机的阈值；静默断流也不保证自动停止。
实时监视设备，结束核对连续EEG、事件与行为文件；错误保存完整报错、时间及日志。

## 历史协议与数据兼容

| 版本 | 入口及用途 |
|---|---|
| V2七级45组 | run_video_emotion_formal.bat / run_video_emotion_demo.bat，新实验 |
| V1九级45组 | run_video_emotion_legacy_v1.bat，继续既有protocol_emotion_v1数据 |
| 旧34组内容题 | run_video_legacy_34.bat或run_video_formal.bat，原Demo也保留 |
| 旧17组完整版 | run_video_legacy_17.bat |
| 旧2779题 | run_video_legacy_2779.bat或原部署入口 |

材料不重新抽样，旧数据不迁移。九级和七级原始评分不能直接混用。历史Word说明保留日期，当前V2以本README与V2文档为准。

## 文档与目录

- [V2被试与主试完整实验说明](docs/EMOTION_EEG_V2_PROTOCOL.zh-CN.md)
- [硬盘最快离线更新操作](docs/OFFLINE_EMOTION_V2_UPDATE.zh-CN.md)
- [疲劳自评的文献与限制](docs/FATIGUE_BINARY_RATIONALE.zh-CN.md)
- [2026年9月15日维护与验证日志](docs/EMOTION_V2_MAINTENANCE_20260915.md)
- [历史34组汇报说明](docs/reports/视频EEG_34组_被试与主试说明.docx)
- [历史V1九级45组说明](docs/reports/视频EEG_45组融合情绪评分_被试与主试说明.docx)

```text
video_eeg/config/       # 新旧协议YAML、固定清单、来源索引与题库
video_eeg/experiment/   # 连续EEG视频框架、V1/V2行为页面
video_eeg/devices/      # BrainCo、Neuracle、LSL与模拟采集
video_eeg/storage/      # 连续EEG和事件存储
video_eeg/utils/        # marker、恢复状态、材料定位和随机顺序
scripts/               # 安装、启动、审计、离线打包部署和模拟测试
docs/                  # 参数、被试与主试说明、文献、维护记录
vendor/                # 发布所需本地依赖源码
stimuli/videos/        # 普通刺激材料；Git仅保留空占位
data/                  # 运行后生成的数据；不上传本地被试文件
tests/                 # 自动化验证
```

## 开发与验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts/smoke_emotion_v2.py
.\.venv\Scripts\python.exe scripts/build_release.py release/source_v2
.\.venv\Scripts\python.exe scripts/build_offline_emotion_update.py release/offline_v2
```

真实BrainCo、物理触发和声音时延及每台实验机仍需现场短测。模拟EEG通过不等于真实硬件通过。
发布只使用白名单，不上传环境、数据、缓存、账号配置或视频本体；第三方情绪视频不再次发布到本仓库Release。
