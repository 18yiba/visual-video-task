# Video EEG experiment flow

正式启动时填写 subject ID 和 Session 01–34；默认建议该 subject 最近一个未完成 Session，也可
用 `--session 1..17` 显式选择。若已有 state，队列从保存的断点继续。

```text
instructions / EEG preflight
  -> start EEG resources
  -> fixed Session queue, randomized once and persisted
  -> fixation -> complete video attempt
       -> if S: record skipped attempt, video requeued, progress unchanged
       -> if Esc: record aborted attempt, preserve current video at queue head, safe shutdown
       -> if EOF and selected: ask one MCQ about this video (no timeout)
            -> if Esc/crash: retain video for replay, log unanswered/interrupted attempt
            -> if answered: mark attention complete (correctness logged separately)
       -> commit video and attention together, add real duration to net watch time, checkpoint
  -> automatic short post-video rest (2 s, if enabled)
  -> at video boundary: due rest page (30–45 net minutes)
       -> 继续: dwell logged, continuous net clock reset, new threshold
       -> 退出: progress page, checkpoint, safe shutdown
  -> all videos + 18 valid attention responses -> Session completed
```

Attention 只在视频边界出现，不会打断视频；rest 也不会在视频中间出现。Esc 在 instructions、
fixation、video、attention 和 rest 页面有效。正常完整观看才会从 remaining 移除。

Demo 仍可用 `run_video_demo.bat` 快速验证视频、按钮、S、Esc、checkpoint/resume 状态机；它使用
独立 demo records、较小的内部视频队列和与正式流程一致的 30–45 分钟长休息阈值。自动化 smoke
fixture 可在测试代码中显式使用秒级阈值，不会进入真人 Demo 配置。
