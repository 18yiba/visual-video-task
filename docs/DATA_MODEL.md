# Video EEG data model

本文件只描述 `video_eeg` 视频 EEG 范式；情绪评分 EEG 范式有自己的数据目录和 schema。

正式视频材料由 `video_eeg/config/session_manifest.csv` 固定划分为 17 个 Session。manifest v2 还保存
版本、生成时间、源/排除数量、分配算法、seed 和 rank-quantile 时长桶定义。每行包含 `video_id`、
相对视频路径、真实 `video_duration_sec`、`duration_bucket` 和 `session_id`；每个正式视频只出现一次，
且不超过 60 秒。被排除的 47 个候选素材记录在 `formal_excluded_over_60s.csv`，原始文件保留。
Session 内播放队列按保存的 seed 生成并写入 subject/session state，恢复时不会重新生成归属或重复
已完成视频。

## Subject/session 目录

```text
data/video_question_complete_runs/<subject_id>/session_01/
  session_state.json       # 唯一 checkpoint/state source-of-truth，原子写入
  trial_log.csv            # 所有 video attempts（含 aborted/skipped）
  attention_log.csv        # 所有 attention attempts（含 aborted）
  video_question_log.csv   # 视频、题干、四个选项、答案、正确性、RT、抽查/attempt ID
  question_bank_snapshot.json # 本 Session 题库快照，SHA-256 校验续跑一致性
  rest_log.csv             # rest page 行为
  <timestamp>/
    metadata.json
    events.json
    continuous_eeg.npy     # 保持现有原始 EEG 保存格式
```

一次视频只有自然 EOF 才能产生 `completed=true`。每次正式播放都有独立 `attempt_id`；S 是
`status=skipped, completed=false, abort_reason=s_skip`，Esc/异常是 aborted，均不覆盖原始 EEG
或旧 attempt。中断视频留在 `queue_video_ids`，恢复后从头重播；completed video 从 queue 永久移除。

`session_state.json` 至少保存 subject/session、manifest version/hash、completed/remaining/current
video、queue seed/order、completed net video duration、连续净观看时长、下一休息阈值、18 道
attention schedule 与 completed IDs、attempt/rest/attention logs、时间戳和退出原因。保存流程为
temporary file + flush/fsync + atomic replace。

## 时间与事件

净观看时长只累计自然完成视频的 assigned duration；fixation、loading、attention、rest、pause、
instruction 和未完成 attempt 都不计入。行为 RT/dwell 使用 monotonic clock，日志时间戳使用 wall
clock，EEG 对齐继续使用现有 marker/LSL 时间机制。

每个正式 Session 从有题视频中分层随机抽取 18 个不同视频，在该视频自然结束后立即显示四选一题。
按 1–4 或 A–D 作答，不限时；答错也算完成，正确性另记。题目与视频的绑定和抽查计划写入 state，
S 跳过后须完整重播才会提问；答题时 Esc 或崩溃，视频不提交完成，续跑从头重播再问。
state 同时保存 `attention_task_type=video_mcq`、题库 SHA-256、题干、选项和正确答案。
`attention_log.csv` 和 `video_question_log.csv` 保留每次回答或退出的记录及 `attention_id`、视频和 attempt ID。
旧算术数据保留在 `data/sourcedata`，不可直接混用旧 state。呈现时发送一次
`attention_task_on=142`；`attention_response` 仍是本地行为事件，不发送 EEG marker。

每轮连续净观看随机 30–45 个整数分钟后，在完整视频结束时出现 rest page。rest 可无限停留，只有
“继续”和“退出”；退出保存 state 并显示按 duration 计算的 Session progress。

## EEG/BIDS compatibility

视频范式声明 expected sampling rate 为 1000 Hz，写入 `sfreq`、`expected_sampling_rate_hz` 和
EEG metadata。LSL/Neuracle 读取到的实际 rate 不匹配时会报错；代码不做静默软件重采样。现有
`continuous_eeg.npy` 和 `events.json` 保留为 raw/source-of-truth，事件含 subject/session、video
stimulus、attempt status、attention/rest 字段及明确时间基准；`trial_log.csv` 同时提供
`image_onset/image_offset`、`eeg_part` 和 `stim_file/video_file` 兼容列。已按 converter 的 source contract 保持
`S###/<timestamp>_<task>/session_##/metadata.json`、`trial_log.csv`、`events*.json` 和
`continuous_eeg*.npy` 结构；转换器的实际 CLI 作为采集后的只读 post-processing 使用，aborted attempt
保留在 source events/trial log 中。当前 converter 的标准 `events.tsv` 输出保留视频 onset/duration
和 stimulus 引用；`completed/status/abort_reason`、attention/rest 等项目字段继续保存在 source
CSV/JSON 中，以免被转换器未声明的自定义列丢弃。
为使 BIDS `events.tsv` 也能区分 attempt，`trial_type` 使用 `video_completed`、`video_skipped` 或
`video_aborted`；详细 `status`、`completed`、`abort_reason` 仍原样保留在 source log。
