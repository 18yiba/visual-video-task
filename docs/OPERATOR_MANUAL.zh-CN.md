# 视频 EEG 详细操作说明

适用入口：`run_video_formal.bat`、`run_video_demo.bat`。
当前默认正式题库：`complete_questions_20260908/question_bank.json`。

## 一、下载与目录放置

使用 Windows 10/11 64 位电脑。将 GitHub 下载的 ZIP **完整解压**到可写的本地文件夹，
例如 `D:\Experiments\visual-video-task`。不要在压缩包预览中运行，不要求沿用开发电脑的盘符或用户名。
尽量避免路径中有英文单引号、感叹号等会影响 Windows 批处理解析的特殊字符。
首次安装需联网访问 uv、Python 下载源和 PyPI，并准备足够空间安装科学计算环境。

源码目录包含 `video_eeg`、`scripts`、`docs`、`tests`、`vendor` 及根目录启动文件。
无需安装 Node.js，也无需运行情绪评分程序。
GitHub 源码包不包含受试者数据、正式视频、已安装环境或缓存。

本版本已在独立源码副本完成首次联网安装和完整 Demo 验证（10 视频、3 次抽查）；
具体结果见 `clean_install_validation.json`。实际采集设备与目标电脑的物理测试仍须主试完成。

### 正式视频的放置

当前远端视频包尚在上传，完整下载状态见 [材料发布状态](MATERIALS_UPLOAD_STATUS.md)。
已有实验室母库可直接使用；新电脑可先安装并运行合成 Demo，等待材料公开后再完整下载。

正式视频现通过 [统一材料发布页](https://github.com/18yiba/visual-video-task/releases/tag/materials-v1-20260910)
分包提供。首次安装环境后，双击根目录 `download_materials.bat`，自动下载并校验至 `stimuli/videos`。
共 84 个视频 ZIP、7996 段、约 44.2 GB；下载脚本逐包解压，建议为材料预留至少 50 GB。
源码 ZIP 不包含真实视频；发布页的 Source code ZIP 也不是视频包。
手动下载、离线复制、校验及版本注意事项见 [视频库下载说明](MATERIALS_DOWNLOAD.zh-CN.md)。
文件名须保留，例如 `0001.mp4`。支持两种布局：

```text
方式 A：沿用实验室部署包
video/
  video_materials/formal_v1/videos/0001.mp4 ...
  visual-video-task-master/run_video_formal.bat

方式 B：单独下载 GitHub 源码
visual-video-task/
  stimuli/videos/0001.mp4 ...
  run_video_formal.bat
```

正式分组位于 `video_eeg/config/session_manifest_34.csv`，不要自行重命名视频、修改归属或更换清单。
也可在配置中设置 `protocol.video_library_dir` 为实际母库路径。
程序会检查目标 Session 文件是否存在；缺失时停止，不会静默跳过。

若尚未拿到正式视频，安装器会生成十段合成练习视频，Demo 可以先验证显示、键盘、答题和模拟记录。
这些练习素材不用于正式采集。完整正式实验必须另外下载或复制真实视频母库。

## 二、首次安装环境

1. 双击根目录 `install_lab_env_uv.bat`；它只转发至 `scripts\install_lab_env_uv.bat`，两者调用同一安装器。
   使用下划线连成的实际文件名，不是 `install\_lab\_env\_uv.bat` 多层路径。
2. 安装器优先检查项目内 `.venv`。健康环境直接复用，不重装。
3. 新电脑无环境时，安装器下载项目本地 uv 和 Python 3.12，然后创建 `.venv`。
4. 自动安装固定的 PsychoPy 及运行依赖、BrainCo SDK 和随源码提供的 BIDS 转换器。
5. 执行依赖检查并生成合成练习素材。看到 `Environment ready` 后关闭窗口。

新电脑不需要预先安装系统 Python。已有实验室便携 `runtime/python312` 时仍可复用。
安装日志在 `logs/install_日期时间.log`。不健康或复制后路径失效的 `.venv` 会改名备份后重建；
安装器不会删除 `data`、视频或题库。

网络中断时按日志检查连接后再次双击。必要时使用主试终端重建环境：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_lab_env_uv.ps1 -ForceRepair
```

命令须在项目目录执行。运行前先退出所有实验窗口，不要在采集期间重装环境。

## 三、安装后检查

打开项目目录的 PowerShell，执行：

```powershell
.\.venv\Scripts\python.exe scripts\check_video_eeg_env.py
.\.venv\Scripts\python.exe scripts\audit_question_bank.py --require-materials
```

第一条检查 Python/显示/采集相关依赖；第二条检查正式视频、题库及 34 个 Session 的抽查计划。
自动下载已逐视频检查 SHA-256；手动复制后另运行
`.\.venv\Scripts\python.exe scripts\download_materials.py --verify-only`，完整核验文件内容。
当前题库缺三题的事实会显示在报告中，不代表软件故障。若要求每段视频都有题，可另外加
`--require-full-coverage`，该检查在当前快照下会返回失败。

## 四、先运行 Demo

1. 双击 `run_video_demo.bat`。
2. 确认被试编号和窗口设置。Demo 使用模拟 EEG，不需要连接真实采集设备。
3. 阅读第一页的完整实验流程，空格继续，按界面提示完成模拟连接检查。
4. 观看随机十段视频，期间三次四选一抽查。
5. 验证题目中文、选项、按键和视频显示；视频后短休息可按空格提前结束。
6. 可用 S 检查跳过后重播，用 Esc 检查保存退出。退出时等待数据保存页面后再关闭。

有真实母库时 Demo 从题库视频中抽取；无母库时自动使用安装器生成的合成练习素材。
Demo 不读取正式 Session 进度。Demo 每次默认新随机种子，若要测试同一 Demo 的断点，可执行：

```powershell
.\.venv\Scripts\python.exe -m video_eeg.experiment.video_runner --demo --subject-id DEMO_RESUME --seed 42
```

再次用同一命令、同一被试及种子启动即可核对恢复行为。不要为了续跑随意改变题库或视频池。

## 五、正式采集前准备

1. 按设备规范完成佩戴和电极接触检查，确认设备电量/供电、网络或连接条件。
2. 核对正式母库、目标 Session、题库版本和保存磁盘空间。
3. 关闭可能同时占用采集设备的其他程序。
4. 默认正式后端是 BrainCo SDK、期望 1000 Hz；不要把 Demo 的模拟信号当成真实采集。
5. 向被试说明保持头部和身体尽量静止、认真观看、按提示答题及休息方式。

本软件的连接成功不替代真实信号质量检查。正式实验前应在设备界面或实验室质控流程中确认信号。

## 六、正式启动与填写

双击 `run_video_formal.bat`。填写并核对：

| 项目 | 操作 |
| --- | --- |
| 被试编号 | 使用实验约定的匿名编号，例如 S001；同一人的续跑保持完全一致 |
| Session | 选择 1–34；默认建议最近未完成的 Session，仍需主试核对 |
| 显示方式 | 正式建议全屏；调试可使用窗口 |
| 脑电连接 | 按设备检查页面提示确认数据流；失败时先排查设备，不绕过为模拟采集 |

被试看到第一页总体说明后按空格，随后连接检查，通过后进入记录和视频流程。
明确指定被试及 Session 的终端启动示例：

```powershell
.\.venv\Scripts\python.exe -m video_eeg.experiment.video_runner --subject-id S001 --session 1 --real-eeg --device-type brainco --brainco-transport sdk
```

## 七、实验过程中的操作

| 页面 | 操作与结果 |
| --- | --- |
| 视频 | 认真观看至结束；S 中断本次播放并安排之后重播 |
| 抽查题 | 根据刚才的视频按 1–4 或 A–D；不限时，答错也完成这次抽查 |
| 短休息 | 默认 2 秒，空格提前继续 |
| 长休息 | 净观看达到随机 30–45 分钟后提示；F 继续、J 退出并保存 |
| 退出 | Esc 中止并保存；等待保存完成提示 |

每正式 Session 有 18 个不同抽查目标，不会每个视频都提问。
题页的“答题不限时”适用于抽查，不代表可以在采集中随意关闭程序。

## 八、中断后如何续跑

正常退出后，用**同一版本入口、同一被试编号、同一 Session**重新启动。
程序读取队列、题库哈希和完成状态；已完成视频不重播，未提交完成的视频继续执行。
抽查页退出时，先重播对应视频再问，避免脱离刚才画面作答。

当前 34 组版本把新正式记录放到 `data/video_question_complete_runs/protocol_34sessions`。
旧 2779 题正式 Session 请用 `run_video_legacy_2779.bat` 继续，仍读取 `data/video_question_runs`。
`run_ready_questions_formal.bat` 保留旧有题子集及 `data/ready_question_checks`。
独立 `visual-video-task-complete-20260908` 的桌面入口仍使用自己的记录，不迁移或覆盖。

看到“题库/协议/Session 不一致”时，不要删除断点文件以强行开始。先核对版本和入口；
需要启用新版本时采用新的实验记录目录或新 Session 方案，保留原记录。

## 九、数据保存在哪里

下列路径均相对当前项目文件夹：

```text
data/video_question_complete_runs/protocol_34sessions/S001/session_01/
  session_state.json
  session_summary.json
  trial_log.csv
  attention_log.csv
  video_question_log.csv
  rest_log.csv                  # 有休息事件时写入
  question_bank_snapshot.json
  日期_时间/
    metadata.json
    events.json
    continuous_eeg.npy
    eeg_segments.json
    video_playlist.json
```

续跑/记录分段时可能出现带 part 后缀的文件；应保留完整目录，不只复制一个 `.npy`。
Demo 的行为进度位于 `data/demo_runs/<subject>/run_<seed>/session_<NN>/`，
模拟 EEG 仍按该 Demo 配置的 `storage.records_dir` 写入带时间戳的目录。

| 文件 | 用途 |
| --- | --- |
| session_state.json | 恢复依据：队列、完成视频/抽查、题库哈希及计划 |
| trial_log.csv | 每次视频 attempt、是否自然结束、中断原因、EEG 相对时间 |
| video_question_log.csv | 题目、四选项、答案、按键、正确性、反应时、来源及复核状态 |
| attention_log.csv | 抽查计划、实际触发、作答或退出记录 |
| question_bank_snapshot.json | 当前 Session 使用的完整题库快照 |
| events.json | 事件时间、采样索引及视频/attempt/attention 关联信息 |
| continuous_eeg.npy | 连续信号；分析前核对采样率、通道与单位 |
| metadata.json | 采集设备、参数、版本与退出信息等 |

反应时为单调时钟测量的秒数；答题退出没有有效回答时相应字段为空。
同一题可能因退出/重播产生多个 attempt，统计时要区分中断与有效回答。

## 十、结束后的核对与备份

确认保存页面给出路径，检查 `session_summary.json` 中退出原因、完成视频和抽查数量。
只有全部视频和 18 次抽查完成才算正式 Session 完成；有文件输出不等于实验完整结束。
备份整个被试 Session 目录、实验配置、Session manifest 与题库版本到实验室规定位置。
原始数据留存；任何切段、BIDS 转换或质控应另存输出。

参考 oi-eegqc 的数据契约，分析前确认采样率、通道名称、物理单位、事件和片段边界。
不要把抽查正确率代替脑电质量评级。本程序目前不自动执行 oi-eegqc。

## 十一、常见问题

| 现象 | 处理 |
| --- | --- |
| 双击后提示 Python 环境缺失 | 先双击安装器；完整解压后运行，不使用旧电脑复制来的失效 .venv |
| 下载超时或安装失败 | 查看 logs 下安装日志，恢复联网后重试；不要删除 data |
| 缺正式视频 | 双击 download_materials.bat，或按材料下载说明解压全部 84 包并校验；合成 Demo 不能代替正式视频 |
| SDK 连接失败 | 核对供电、佩戴、连接条件和设备占用；查看设备检查输出 |
| 采样率不匹配 | 核实设备及配置，按预定实验参数设置；程序不静默改采样率 |
| 题库哈希不一致 | 恢复原题库和原入口，或新开记录；不要混用正在进行的 Session |
| 有视频没有题 | 当前已知三段不抽查；用审计脚本检查新版覆盖，不凭目录名判断 |
| 中文或画面异常 | 在目标电脑用窗口 Demo 验证字体与显示；先排除环境/显卡问题 |
| 按 Esc 后出现第二个 ExperimentAbort | 更新源码到本次修复版；保存提示阶段不再重复处理 Esc，保存完成后按空格退出 |
| 程序异常退出 | 保留所有文件与 crash_report，核对断点再恢复，勿覆盖原始 EEG |

## 十二、代码发布与部署边界

源码包由 `scripts/build_release.py` 按白名单构建，排除受试者数据、视频、密码、环境及缓存。
题库、固定分组、安装器、测试、文档及 BIDS 转换器源代码随包提供。
跨电脑可移植性依赖首次联网安装，以及正式材料和真实设备准备完成。
模拟测试不能保证另一台电脑的设备驱动、电极接触或物理时序；首次正式采集前须在目标电脑试跑。

## 仓库目录占位与本地记录

GitHub 已提供 `stimuli/videos/.gitkeep`、`data/video_question_complete_runs/.gitkeep`、
`data/sourcedata/.gitkeep` 三个空占位文件。它们只保留目录，不是视频或实验记录。
本地已有数据不上传。当前正式采集在本机的 `data/video_question_complete_runs/protocol_34sessions` 生成记录；
`data/sourcedata` 仅供历史数据兼容。保存提示页按空格关闭，重复 Esc 不再抛出退出异常。

## 当前 34 组与旧 17 组

7949 段正式视频总净时长约 50.30 小时。新分组每组 88.35–88.94 分钟，平均 88.76 分钟，
每组 233–235 段，五档视频各至少 46 段；全库正式视频范围约 5.107–59.976 秒。
每个原 Session 按五档时长均衡拆为两半，原 n 对应新 2n−1 和 2n。各组内部随机播放；
播放顺序和 18 个抽查目标在开始时保存，续跑不重新抽签。没有 90 分钟强制停止。
注视点、视频间隔、答题及休息不计入净观看，实际占用时间会更长。

当前权威分组为 `video_eeg/config/session_manifest_34.csv`。
旧 `session_manifest.csv` 保留原 17 组，不能用新文件覆盖旧文件。
旧完整版 17 组请用 `run_video_legacy_17.bat`，其数据仍在 `data/video_question_complete_runs/<subject>`。
新默认入口用 `data/video_question_complete_runs/protocol_34sessions/<subject>`，避免同编号读到旧状态。
不自动迁移已开始的旧 Session，不把旧完成进度强行当作新分组的完成进度。

`video_eeg/config/video_question_labels.csv` 是 7996 段视频的完整标签对照表；
包含 SHA-256、题干、选项、答案、复核状态、`session_34` 和 `legacy_session_17`。
Release 的 `material_metadata.zip` 也包含此表。题目经 `video_file` 文件名关联，未嵌入 MP4 画面或字幕。
原题库可能保留历史 `session_id`，当前分组以 34 组清单和标签表的 `session_34` 列为准。
详见 [34 组与标签审计](SESSION_34_AND_LABEL_AUDIT.zh-CN.md)。
