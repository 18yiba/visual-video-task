# 博睿康全程头动与躯体录像（未发布源码）

部署前先按[README名称检查](../../README.md)在实际实验电脑枚举 DirectShow 视频设备。设备管理器的 `Facial_CAMERA` 不等于当前代码要求的 `facialcamera`；只修改设备实例 FriendlyName 不保证采集接口名称同步。当前源码未实现系统级硬件改名或同名机身自动绑定，真实双机验收尚未通过。

在原博睿康 v3 控制台勾选“全程头动 / 躯体录像（可选）”后开始 EEG 采集。默认关闭；仅博睿康可见，行为评分阶段禁用。该选项与面部录像独立：全程动作摄像头的 DirectShow FriendlyName 必须精确为 `Action_CAMERA`，面部摄像头为 `facialcamera`，两者不可互相替代。设备缺失、同名重复、占用或录像规格不支持时停止。

## 录制范围与 trigger

EEG 数据流就绪后启动动作录像；正式录像首次确认画面帧时发送 `ACTION_RECORDING_ONSET = 165`，随后满足至少0.5秒预录，再发送 Session 开始码101并进入实验内容。预检不发165，每次采集启动仅发一次；面部录像仍逐段发送164。165包含文件名、首帧软件观察时间和媒体PTS，通过现有博睿康同步盒与TRG回传路径发送、核验，不使用另一个打标通道。

一份动作录像连续覆盖本次采集中的注视、普通视频、情绪视频、题目及休息。正常结束或主动退出时，录像持续到 EEG 结束与保存流程之后，再至少后录0.5秒；全文件解码验证录像时长不短于该记录区间，且首尾覆盖通过。录制不包含进入实验前的控制台、设备检测和独立行为评分。它按每次实际启动保存，不把多次中断续跑拼成一份。

分辨率1920×1080，30 fps，H.264 MP4，无音频；复用设备报告的1080p MJPEG/NV12/YUYV422模式选择，仅有1440p/30 fps时缩放输出，不补帧、不降至5 fps。截图中的 FriendlyName 不能证明该设备支持这些模式，仍须实际打开编码验收。

## 文件、失败与恢复

| 当前 Session 内文件 | 用途 |
|---|---|
| `experiment_action.mp4`、`experiment_action_02.mp4`… | 每次启动的连续动作录像，重启递增，旧片段不覆盖 |
| 同名 `.timestamps.csv` | 逐帧软件到达时间、媒体PTS、`relative_experiment_onset_sec` |
| `action_recording_log.jsonl` | 输入规格、起止、覆盖结果、错误与 `experiment_completed` |

日志中的 `video_on` 表示101之前、预录完成后的实验区间起点；`video_off` 表示EEG结束保存流程后的区间终点，不是某段材料视频。`passed` 只证明本次录像覆盖校验通过；主动退出仍可有 `passed`，但 `experiment_completed=false`，不表示完整Session或EEG信号质量通过。EEG metadata记录选项是否启用，录像最终结果以独立录像日志为准。

实验中检查摄像头进程与帧更新；断流会停止当前运行。EEG始终独立尝试保存，即使录像关闭或解码校验失败。保留录像片段、逐帧文件、日志、原EEG与session_state；修复后用原被试和Session续跑，不因录像失败静默重写已完成视频或行为答案。没有通过录像校验时不宣称全程覆盖。

## 更新与验收

正常保存退出并备份整个被试目录后更新分支源码，重启原 `run_neuracle_v3.bat`；无需重装依赖。当前已发布v0.3.8源码压缩包与EXE尚未包含此功能，未重建安装包。只替换旧版 `facial_recording.py` 不足以启用新入口和165码，应更新整套源码，保留本机配置与数据。

软件测试和合成摄像头仅验证流程。正式使用前需分别确认两台摄像头的DirectShow名称、30 fps实际编码、双摄像头长时带宽/磁盘负载、165在Collect及本地EDF TRG中的回传、拔线保存与续跑。帧时间与165均为软件观察/发送时间，不代表曝光时刻；同步误差须现场光学测量。影像与日志属于原始记录，备份整个Session，不进入源码包，不自动加入BIDS/EEGQC副本。

## 本次开发验证

2026-11-10上传前复核：`python -m pytest tests -q --basetemp .local-test-tmp-push-20261110-normal`在现有`.venv`中得到444项通过、5项跳过、12个子测试通过；首次沙箱运行26项失败涉及临时目录权限及离线校验器访问，正常权限完整重跑通过。`uv lock --check --offline --python .venv/Scripts/python.exe`通过，未安装或同步依赖；环境别名检查通过。`main.py --validate`、`python -m src --validate`、`python -m src.project_metadata`通过，独立259文件源码包的两个入口通过。下述Qt与PsychoPy模拟命令均在本轮重跑通过；真实硬件仍未验收。此记录随本次功能提交保存，不把旧提交或历史测试结果当作本轮通过证据。

最终回归命令为 `.venv/Scripts/python.exe -m pytest tests -q`：444项通过、5项跳过、12个子测试通过，包含严格metadata/TOML、源码包可迁移及两个源码入口。沙箱内7项离线BIDS测试曾被Windows文件权限拒绝，在正常文件权限下重跑及最终全套均通过；未修改校验器或关闭校验。

`.venv/Scripts/python.exe scripts/validation/smoke_v3_frontend.py`（`VIDEO_EEG_BACKEND=neuracle`）通过真实Qt入口显示、默认关闭、勾选参数及评分阶段禁用检查。`.venv/Scripts/python.exe scripts/validation/smoke_emotion_v3.py --emotion-only --facial-synthetic --action-synthetic`用于真实PsychoPy窗口、模拟EEG与两路合成摄像头，验证165先于101且每次启动一次、录像前后覆盖、主动退出后递增续录、旧文件哈希不变及评分不改采集记录；这不是硬件验收。
