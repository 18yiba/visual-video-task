# 视频随机抽查审计与使用说明（2026-09-08）

## 审计范围与发现

本文件记录当天较早的 2779 题改造。当前完整版接入、清理与发布状态见
[维护记录](MAINTENANCE_LOG_20260908.md)，当前使用方法见 [详细操作说明](OPERATOR_MANUAL.zh-CN.md)。

当前部署目录为 `D:\Users\EDY\Desktop\video`。用户提到的 `video\_materials` 和
`D:\Users\EDY\Desktop\已出题视频` 当前不存在，因此未能读取那里的三个入口文件。
实际视频母库为 `video_materials/formal_v1/videos`，实验代码为 `visual-video-task-master`。
本次核对了素材清单、Session 计划、视频播放、答题、断点和日志路径；未对每段视频的题意正确性逐个人工审核。

修改前普通入口生成 0–100 加减法题；已出题入口则每个视频后都问一道题，并关闭了 18 次 attention。
已出题入口已具备四选一显示、行为记录和题库快照，本次复用该流程实现固定次数的抽查。

正式 manifest 共 7949 个视频，分为 17 个 Session。原有 47 个超 60 秒视频的排除规则不变。
本地题库 `video_eeg/config/ready_questions_20260908/question_bank.json` 有 2779 道题，
所有对应视频文件均存在；按原 Session 的可出题数量依次为：

`166, 162, 162, 164, 164, 162, 162, 163, 164, 163, 165, 164, 163, 164, 164, 164, 163`。

## 运行方式

- `run_video_formal.bat`：原 7949 视频正式库，每 Session 抽查 18 次，真实 BrainCo EEG。
- `run_video_demo.bat`：10 个有题视频、3 次抽查，模拟 EEG。
- `run_ready_questions_formal.bat`：保留原 2779 个有题视频子集的 Session 分组，每 Session 18 次抽查。
- `run_ready_questions_demo.bat`：10 个有题视频、3 次抽查，模拟 EEG。

抽查视频从随机播放队列中分层随机抽取：将有题视频按播放顺序分成 18 段，每段选一个，
避免重复且覆盖整个 Session。实际观看时长作为计划字段保存。没有题的视频继续正常播放。
题库覆盖不足时启动报错，不生成替代算术题。

题目只在对应视频自然结束后、短暂休息前显示。按 1–4 或 A–D 作答，不限时，不显示答案反馈。
作答后无论对错都算完成一次抽查，正确性另记。S 跳过的视频保留题目绑定，完整重播后再问。
答题中按 Esc 退出或进程崩溃，未提交的视频续跑时从头重播再提问；题目和队列不会重新抽签。
全部视频和 18 次抽查都完成才标记 Session 完成，不会在末尾集中补问先前视频。

## 数据与兼容

普通正式入口写入 `data/video_question_runs/<subject>/session_<NN>/`；
有题子集正式入口写入 `data/ready_question_checks/<subject>/session_<NN>/`。
Demo 进度继续位于 `data/demo_runs/<subject>/run_<seed>/session_<NN>/`。
历史 `data/sourcedata`、`data/ready_question_runs` 及其采集记录保留。

- `session_state.json`：抽查 ID、视频绑定、题干、选项、正确答案、协议类型、题库哈希和完成状态。
- `attention_log.csv`：抽查计划、实际触发净观看时长、答题或中断记录。
- `video_question_log.csv`：题干、四个选项、正确答案、按键、作答、正确性、反应时、时间戳、视频/attempt/attention ID。
- `question_bank_snapshot.json`：该 Session 的题库快照。续跑校验 SHA-256，禁止静默换题。
- `trial_log.csv`、时间戳目录内的 EEG 与事件文件继续使用原记录流程。

回答事件在 CSV 写盘前发送；`attention_task_on` 和 `attention_response` 携带
`task_type=video_mcq`、`attention_id`、视频和 attempt ID。原 EEG marker 映射保持不变。
state 是恢复依据；旧算术协议或不同题库、不同抽查次数的 state 会被拒绝混用。

## 验证

使用项目 `.venv/Scripts/python.exe -m pytest tests -q` 验证协议与记录。
测试覆盖 17 个正式 Session 各 18 个唯一抽查绑定、不同种子变化、保存恢复、跳过重播、
未抽中不提问、题库不足报错、答题 Esc 不提交视频及 CSV 答案/反应时记录。

`scripts/smoke_ready_questions.py` 使用真实 PsychoPy 窗口播放 `0001.mp4`，自动回答一次抽查，
验证视频提交、题目显示、CSV、模拟 EEG 和事件输出。截图在 `data/video_question_smoke/question_screen.png`。
该验证使用模拟 EEG，没有连接真实脑电设备。
