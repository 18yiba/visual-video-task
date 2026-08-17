# PsychoPy 视频 EEG 范式设计

## 实验边界

视频实验使用独立入口 `psychopy_video_experiment.py` 和独立配置 `video_config.yaml`。图片实验继续使用 `psychopy_image_b_experiment.py`、`psychopy_image_b_rating.py` 和 `config.yaml`。两套实验不共享启动界面、范式选择状态或实验配置文件，只共享 EEG 采集、事件记录和硬件后端等底层设施。

## Session 流程

每个视频 Session 依次执行实验说明、EEG 或 Marker 联通检查、`session_start`、60 秒睁眼基线、60 秒闭眼基线、正式视频 trial 循环、`session_end` 和数据导出。视频实验不包含练习评分或正式评分阶段，也不产生 `behavioral_ratings.csv`。

睁眼基线由 `eyes_open_baseline_start` 和 `eyes_open_baseline_end` 标记包围，闭眼基线由 `eyes_closed_baseline_start` 和 `eyes_closed_baseline_end` 标记包围。通用的 `baseline_start` 与 `baseline_end` 包围完整的 120 秒双基线，便于兼容已有分析代码。

## Trial 流程

单个 trial 依次执行注视点、视频播放、空屏和 ITI。默认时长分别为 1.5 秒、60 秒、1 秒和 2 秒。视频可以由素材清单中的 `duration_sec` 覆盖默认时长；本地目录扫描得到的素材使用 60 秒默认值。紧急情况下按 S 可跳过当前视频，程序记录实际呈现时长和跳过状态。

视频通过 PsychoPy `MovieStim` 逐帧绘制。`fixation_on`、`video_on`、`video_off`、`blank_on`、`iti_on` 等刺激边界使用 `Window.callOnFlip` 发送，使本地事件时间、串口 Trigger 和 LSL Marker 对齐实际屏幕翻转。

## 播放列表

素材文件采用 `视频ID_分类名.扩展名` 命名，程序按下划线后的分类进行均衡抽样。正式 trial 数必须能够被分类数整除，各分类可用视频数必须满足目标数量；不满足时实验在启动前报错，不再生成 placeholder 黑屏刺激。

播放列表使用 `random_seed + session_id` 生成，并在 Session 目录保存为 `video_playlist.json`。这种设计保证同一配置和 Session 可复现，同时允许不同 Session 获得不同顺序。

## Marker 设计

Session 开始和结束使用 101、102，完整双基线使用 110、111，睁眼基线使用 112、113，闭眼基线使用 114、115，注视点使用 130、131，视频使用 132、133，空屏使用 134、135，ITI 使用 138、139，trial 边界使用 140、141。

BrainCo BCIGo 模式下，视频入口默认发布 `video-eeg-Markers` LSL 流，BCIGo 负责将 EEG 和 Marker 写入同一个 EDF 时间轴。BrainCo EEG-LSL、SDK、Neuracle 和模拟模式下，程序同时保存本地连续 EEG 与事件时间线。

## 数据输出

视频数据默认写入 `video_records_storage`，与图片实验的 `records_storage` 分离。Session 目录包含 `video_playlist.json`、`trial_log.csv`、`events.json`、`metadata.json` 和 `eeg_segments.json`；本地 EEG 模式还包含 `continuous_eeg.npy`。`trial_log.csv` 在每个已完成 trial 后原子更新。
