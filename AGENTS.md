# Video EEG maintenance

- Read `docs/MAINTENANCE_LOG_20260908.md` and `docs/OPERATOR_MANUAL.zh-CN.md` before changing deployment behavior.
- Preserve all recordings, Session state, question snapshots and fixed Session membership.
- Keep the formal and demo double-click entry points and the Windows installer usable from a fresh source download.
- Formal protocol: 17 Sessions, 18 video-bound checks each. Demo: ten clips, three checks, dummy EEG.
- Preserve question review/source metadata; generated questions are not automatically independently reviewed.
- Do not silently change the question bank for an ongoing Session. Keep legacy config/entry points for old data.
- Publish only with the source allowlist in `scripts/build_release.py`; exclude data, stimuli, credentials, venv and caches.
- Run relevant tests and a dummy-EEG smoke check for timeline/recording changes. Report hardware and clean-install limits honestly.
- Keep an explicit Markdown record of changes, audit findings, validation results and outstanding publishing blockers.
