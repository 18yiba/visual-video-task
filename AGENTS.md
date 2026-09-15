# Current repository organization (2026-09-15)

- Public experiment entry: run_experiment.bat; choose legacy17 or emotion-v2 and Demo/Formal. Historical modes remain available in the advanced selection.
- Unified launcher sends new subjects to data/sourcedata/<protocol>; existing subjects stay in their original configured/known data root. Never move, merge or overwrite participant progress to tidy folders.
- Read README.md, docs/maintenance/CHANGELOG.md and docs/operations/EEG_AND_RECOVERY.md before changes.
- Release with scripts/maintenance/build_release.py and scripts/repository_layout.json; old local entry files are retained for desktop compatibility but excluded from publication.
- Scripts under maintenance and validation are not daily operator steps. Preserve fixed manifests, question banks, device settings, EEG files and installed runtime environments.

## Historical protocol invariants

# Video EEG maintenance

- Read `docs/maintenance/CHANGELOG.md` and `README.md` before changing deployment behavior.
- Preserve all recordings, Session state, question snapshots and fixed Session membership.
- Keep the formal and demo double-click entry points and the Windows installer usable from a fresh source download.
- Legacy content-question protocol: 34 Sessions, 18 video-bound checks each, about 88.76 net video minutes per Session. Its Demo: ten clips, three checks, dummy EEG. Current new experiments use Emotion EEG v2; retain the following legacy descriptions for compatibility.
- Preserve question review/source metadata; generated questions are not automatically independently reviewed.
- Do not silently change the question bank for an ongoing Session. Keep legacy config/entry points for old data.
- Publish only with the source allowlist in `scripts/maintenance/build_release.py`; exclude data, stimuli, credentials, venv and caches.
- Run relevant tests and a dummy-EEG smoke check for timeline/recording changes. Report hardware and clean-install limits honestly.
- Keep an explicit Markdown record of changes, audit findings, validation results and outstanding publishing blockers.

- Source distribution may include only these empty placeholders under otherwise excluded trees:
  `stimuli/videos/.gitkeep`, `data/sourcedata/.gitkeep`.
- The user explicitly authorized the complete video corpus in the versioned GitHub Release.
  Keep videos out of the Git source tree; never include local participant data in either distribution.
- Keep root installer a forwarding wrapper. Safe-exit screens must not re-raise held Escape before/after export.
- Keep material manifest checksums and download documentation aligned with the published immutable corpus version.

- User authorized splitting each of the 17 legacy Sessions into two duration-diverse halves.
  Current fixed membership: `session_manifest_34.csv`; legacy `session_manifest.csv` stays byte-identical.
- New formal recordings use `data/video_question_complete_runs/protocol_34sessions`.
  `run_video_legacy_17.bat` retains the old complete-bank recordings and original 17-Session manifest.
- Every Session contains all five duration buckets. Randomize playback independently, persist order on resume;
  do not impose a hard 90-minute cutoff or mix time spent in questions/rest with net video duration.

## Emotion EEG v1 (2026-09-12)

- New experiments use run_video_emotion_formal.bat / run_video_emotion_demo.bat. Legacy entries retain their original behavior.
- session_manifest_emotion_v1.csv: 45 Sessions, all 7949 ordinary + 3138 emotion videos exactly once, per-Session positive=neutral=negative.
- Emotion trials require natural EOF, then integer 1-9 Valence and Arousal, then rest. Commit only after both answers.
- Keep partial attempts and replay the video plus both ratings on resume; never migrate legacy state automatically.
- New output: data/video_emotion_eeg_runs/protocol_emotion_v1. Actual playback (including partial replays) drives the rest clock; ratings/rest do not.
- Maintain fixed membership and saved subject/session queue. Do not regenerate the manifest during a running study.
- No eMotions binaries or local emotion_library.local.json in source publication. Third-party video redistribution is not presumed from the dataset card license.
- See docs/versions/emotion-v1.md and docs/versions/emotion-v1.md before changes.

## Emotion EEG v2 2026年9月15日

- 最新默认为emotion-v2：原45组成员不变，七级效价/唤醒，普通视频后F/J喜好。
- 每组9道普通视频内容题，绑定约10分钟净视频目标；题后下一页必须是F/J精神疲劳。
- 普通视频与全部行为一起提交；中止保留部分attempt且完整重播重答，不重新抽题。
- 新数据protocol_emotion_v2；旧九级保留legacy_v1入口与配置，不迁移旧状态。
- 疲劳自评是文献启发的研究自编二分类，不宣称已验证量表。
- 离线包新目录_video_eeg_emotion_v2_update，优先复用本机已有情绪材料，不覆盖旧包和旧data。
- 维护记录见docs/versions/emotion-v2.md。
- 本地EEG新增采集看门狗：5秒无样本、启动10秒。保留每秒健康日志与即时错误；不能将断流推断为确定的电池/关机原因，也不宣称质量阈值监测。维护见docs/maintenance/CHANGELOG.md。
