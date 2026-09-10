# Video EEG maintenance

- Read `docs/MAINTENANCE_LOG_20260908.md` and `docs/OPERATOR_MANUAL.zh-CN.md` before changing deployment behavior.
- Preserve all recordings, Session state, question snapshots and fixed Session membership.
- Keep the formal and demo double-click entry points and the Windows installer usable from a fresh source download.
- Formal protocol: 34 Sessions, 18 video-bound checks each, about 88.76 net video minutes per Session. Demo: ten clips, three checks, dummy EEG.
- Preserve question review/source metadata; generated questions are not automatically independently reviewed.
- Do not silently change the question bank for an ongoing Session. Keep legacy config/entry points for old data.
- Publish only with the source allowlist in `scripts/build_release.py`; exclude data, stimuli, credentials, venv and caches.
- Run relevant tests and a dummy-EEG smoke check for timeline/recording changes. Report hardware and clean-install limits honestly.
- Keep an explicit Markdown record of changes, audit findings, validation results and outstanding publishing blockers.

- Source distribution may include only these empty placeholders under otherwise excluded trees:
  `stimuli/videos/.gitkeep`, `data/video_question_complete_runs/.gitkeep`, `data/sourcedata/.gitkeep`.
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
