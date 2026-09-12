# Emotion EEG integration audit — 2026-09-12

## 审计前结论

1. 主实现为 `visual-video-task-master`，`run_video_formal.bat` → `scripts/run_video_formal.bat` → `video_eeg.experiment.video_runner`。当前默认完整版题库、34组配置；本地与远端 master（9a5e3dd）需逐文件比较后发布。
2. 桌面 `视频题库完整版_采脑电.bat` / `_试运行.bat` 调用独立 `visual-video-task-complete-20260908/run_complete_formal.bat` / `run_complete_demo.bat`，仍是旧完整版入口。`已出题视频_采脑电.bat` / `_试运行.bat` 调用主项目 `run_ready_questions_formal.bat` / `run_ready_questions_demo.bat`。桌面说明仍描述2779题、17组子集；不能据桌面文件名推断最新34组。
3. 当前权威旧34组是 `video_eeg/config/session_manifest_34.csv`，7949段；旧17组为 `session_manifest.csv`。新增协议不能覆盖这些清单。
4. `QuestionVideoRunner` 在自然播放结束后、短休息前调用内容题；每组18个预存抽查目标。1–4/A–D，不限时；日志包含正确答案及正误，但UI不反馈。视频提交延迟到回答完成；退出题页后会重播。
5. `EegSessionManager` 在后台线程每10ms调用 `SessionRecorder.pull`，流式写临时f32，再导出连续NPY、events与metadata。BrainCo SDK设备发现/连接、采样率检查在启动流程；评分不需要重启采集。
6. 原视频on/off及fixation/break等通过 `win.callOnFlip(manager.emit, ...)` 调度；SessionEvent含累计sample_index、相对单调时间和payload。原sample index为记录分段内索引，需配合eeg_part使用。
7. 短休息默认2秒，空格可提前结束；`_run_post_video_rest`写break_start/end。新评分必须在此休息之前执行。
8. 长休息由净视频累计达到随机30–45分钟触发，F继续、J保存退出；不是固定wall-clock截止。
9. 旧代码 `commit_completed_video` 按已完成视频计划时长累计，未完成/重播时长不累计。用户新定义要求实际已播放时长，新协议需单独记账，不能改变旧协议语义。
10. `SessionState` 保存视频固定归属、随机队列、已完成ID、attempt、休息阈值及manifest hash。现有摘要/CSV替换失败可能影响退出导出，需新协议内保护；不改写旧数据。
11. `E:/video/video_rating` 是独立jsPsych/Node实现。`src/main.js`仅valence/arousal两维、顺序固定；现有量表为1–5鼠标点击，`performance.now()`测RT，`plugins.js RatingClickPlugin`无评分超时；server.js写试次与进度。新系统复用“两页、离散选择、立即提交、单调时钟RT”的设计，不引入Node运行依赖，按要求重实现为PsychoPy 1–9键盘量表。
12. `emotion_video/selected` 实际3138个MP4；最终 `metadata/selected_videos.csv`、`final_balance_summary.csv`与提取状态均存在，三类各1046，实际17.467511小时。与计划不同的2个候选已replacement；应使用validated列表，不能重新使用最初计划的失效ID。视频路径为selected/大类/原始标签/带原ID文件名，metadata保留原始标签、SHA256、ffprobe参数。20个源Parquet仍保留，不纳入Git。

## 集成边界

以现有VideoRunner/EegSessionManager/SessionRecorder为唯一框架，新增EmotionVideoRunner、纯评分组件、Session builder和新配置；保留全部旧入口及清单。新增正式数据仅写 `data/video_emotion_eeg_runs/protocol_emotion_v1`。标签仅在manifest/event/log中；被试UI不显示标签或路径。

原播放器OpenCVVideoPlayer已有音轨提取和sounddevice播放。旧VideoRunner在计划时长减0.25秒时也视为完成；新协议应禁用这一提前结束条件，使用真正自然结束，避免评分对应未完整播放视频。保留旧实现行为以兼容已有实验。

新协议评分：valence后arousal，1–9整数，不限时，无标准答案；两题完成才提交情绪视频。部分评分作为attempt保留，恢复重播视频并重答两题。实际观看净时钟包括原视频、情绪视频及中断已观看部分，排除评分/休息/连接/保存。

公开eMotions仓库标记Apache-2.0，但这不足以逐一确认第三方短视频再分发权。本次不上传情绪视频到Git或Release，仅提交ID、相对路径、checksum和放置说明。真实硬件验证pending；用dummy EEG进行软件smoke。
