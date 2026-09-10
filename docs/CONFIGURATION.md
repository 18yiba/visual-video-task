# Video EEG configuration

本目录只包含视频 EEG 配置：

```text
video_eeg/config/video_config.yaml       # formal: 34 sessions, 18 attention/session
video_eeg/config/video_demo_config.yaml  # demo-only short queue; participant rest threshold remains formal
video_eeg/config/session_manifest_34.csv    # fixed duration-balanced formal membership
video_eeg/config/formal_excluded_over_60s.csv  # non-destructive exclusion audit
video_eeg/config/eeg_bids_converter.yaml # post-acquisition converter mapping
```

正式配置的关键参数为：

```yaml
eeg_sampling_rate_hz: 1000.0
protocol:
  num_sessions: 34
  attention_tasks_per_session: 18
  attention_enabled: true
  question_bank_path: video_eeg/config/complete_questions_20260908/question_bank.json
  rest_min_net_minutes: 30
  rest_max_net_minutes: 45
  attention_timeout: null
  post_video_rest_seconds: 2.0
  session_manifest_path: video_eeg/config/session_manifest_34.csv
  formal_exclusion_report_path: video_eeg/config/formal_excluded_over_60s.csv
  duration_bucket_count: 5
```

`sfreq` 保留为现有采集器兼容字段，并与 `eeg_sampling_rate_hz` 都为 1000。设备/LSL 的实际
sampling rate 仍由硬件或采集软件决定；不匹配时实验停止并提示，不重采样。

formal 不再使用 block、`trials_per_block`、40 道 alarm test 或固定 3000 ms timeout，也不从操作员
表单读取视频数量。视频数量和归属由带版本、哈希和时长桶定义的 manifest 决定，Session 内顺序通过 state 中保存的 queue/seed 追踪。subject/session state
默认写入 `data/video_question_complete_runs/protocol_34sessions/<subject>/session_<NN>/session_state.json`。
旧 2779 题正式 Session 用 `run_video_legacy_2779.bat`，仍读取 `data/video_question_runs`。
旧算术实验输出保留在 `data/sourcedata`。抽查按视频绑定，每 Session 在有题视频中分层随机选择 18 个；
未出题的视频仍正常播放。题库不足 18 个时启动失败，不回退到算术题。题库哈希和抽查计划随 state 保存。
`run_ready_questions_formal.bat` 保留原有 2779 个有题视频子集，现也每 Session 抽查 18 次，
输出到 `data/ready_question_checks`。两个 Demo 均为 10 个有题视频、3 次抽查。

Demo 使用 dummy EEG、少量视频和内部简化的 attention 数量，输出到 `data/demo_runs`；参与者看到的
长休息阈值仍为 30–45 分钟，每视频短休息为 2 秒，不会读取或修改 formal subject progress，也不会
重写 formal manifest。
