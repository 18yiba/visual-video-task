# visual-video-task maintenance

- Public versions only: v1 (17 Sessions) and v2 (45 Sessions, EEG plus emotion ratings). The launcher must expose exactly these two options, retaining Demo/Formal.
- Preserve fixed Session membership, question bank hashes, material files, all subject recordings and session_state.json. Public version naming must not rewrite persisted protocol identifiers or snapshots.
- New subjects use data/sourcedata/v1 or v2. Existing complete, protocol_emotion_v2 and prior sourcedata/legacy17 or emotion-v2 subjects must resume in place. Conflicting roots must stop with an explanation.
- Read README.md, docs/maintenance/CHANGELOG.md and docs/operations/EEG_AND_RECOVERY.md before edits. Version manuals are docs/versions/v1.md and v2.md.
- Source release uses scripts/maintenance/build_release.py and scripts/repository_layout.json. Never publish recordings, environments, cache, credentials or video binaries in Git. Public material releases are separate.
- Only empty stimuli/videos/.gitkeep and data/sourcedata/.gitkeep are source placeholders.
- Installer must work on a fresh Windows source download. Preserve runtime/python312 and installed environments on this development machine.
- v1 retains 18 video-bound checks; v2 retains 9 checks about every ten net minutes, immediately followed by 1-5 fatigue, ordinary-video F/J liking, and seven-point valence/arousal. Partial trials replay and resubmit as before.
- Fatigue is a literature-inspired study-specific five-point item, not a validated scale. Preserve source/review status on questions.
- Test affected paths, source-only distribution, and real-window dummy EEG after launcher changes. Clearly distinguish hardware tests from simulation.
- Retired public versions are excluded by the release allowlist; do not recursively delete local historical code, materials or recordings. Verify Windows deletion targets and avoid junction traversal.

- Fatigue wording: 当前您的疲劳程度是？; endpoints 1 几乎不疲劳 and 5 非常疲劳，完全无法继续观看. Five option texts and scale revision are saved. Existing binary or seven-point fatigue Sessions retain their original contract until completion; new Sessions use five points. Never convert old answers.

- Windows EXE 1.0.1 uses verified local config snapshots and data copies under Desktop/video/data/sourcedata; original records remain untouched. Desktop migration may resume these copied states locally, preserving protocol hashes. Never infer that unused legacy code, environments, metadata, or unknown files are disposable.

- 2026-09-19 explicit authorization: v2 excludes original:vid_6076 (20), original:vid_2693 (24), original:vid_6241 (33). Preserve immutable base manifest/hash and v1/shared media; effective manifest has 11,084 rows. Backup state before exclusion, preserve attempts/completions/answers and audit necessary unanswered-question rebindings. Completed Sessions remain historical. This is the specific exception to membership preservation above.
