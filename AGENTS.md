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

## Windows 1.0.4 BIDS export

- Native recording/behavior/state remain the recovery contract. BIDS is an independent post-save copy; never substitute it for session_state or overwrite source records.
- Exporter src/video_eeg/utils/bids_export.py (formerly video_eeg/utils/bids_export.py) uses the lab-confirmed BrainCo 31 EEG + first counter row, uV, IO profile; do not reuse device assumptions for another device. Preserve protocol/part identity, behavior fields and missing-EEG timing flags.
- New local Neuracle recordings are EDF, retaining the forwarded channel order and TRG row; mark unverified units/reference/filter metadata as unknown. Historical Neuracle NPY remains readable and untouched.
- Offline official validator must be bundled with Deno; validate all TSV rows, without network. Passing BIDS structure validation does not certify signal quality or real hardware.
- README and docs/operations/BIDS_EXPORT.md describe automatic export, manual retry, old records and source/BIDS directory boundaries.

## Template source layout

- Runtime implementation and protocol resources live in src/video_eeg, including src/video_eeg/config. Root video_eeg.py is a compatibility package shim for existing source imports; do not recreate a root video_eeg/ directory. Keep configuration resource bytes unchanged. Persisted video_eeg/config/... references remain valid through resolve_project_path; new source/documentation paths use src/video_eeg/config/.
- main.py uses config/config.toml for launcher defaults only. Require the template's [experiment], [device] and [storage] metadata sections, but do not use them to change runtime routing. Reject unknown TOML fields. Keep local overrides out of Git and source releases; retain v3 and device-specific independent entries. RUNME.bat is a required compatibility alias that only forwards to run_experiment.bat.
- docs/README.md, docs/deploy.md, docs/data-format.md and data/README.md explain deployment and data boundaries. data/README.md is source documentation, not an output placeholder.
- The project is source-only: keep `pyproject.toml` at `package = false`; do not build/install this project, create console aliases, or restore editable-install instructions. `uv.lock` locks tooling and candidate dependency groups; do not sync the existing lab environment until the runtime set passes dependency and real-window acceptance.
- `metadata.toml` identifies this project as `EMOVID-20261008` for assets and archive prefixes only. Never rewrite persisted protocol identifiers, snapshots, or subject data paths to match it.
- Shared `.dvc/config` is anonymous read-only and contains no credentials. Upload profiles belong in ignored `.dvc/config.local`; DVC assets stay separate from participant data and are not automatically fetched during trials.
- Before reusing an existing environment or packaging Windows site-packages, check for obsolete project distributions, console entry points, and project-specific editable `.pth`/`.egg-link` files. The installer may preserve and replace an obsolete environment through its existing backup flow; the bundle builder must fail rather than copy project aliases.
- Source release allowlist and template-required files are maintained together in `scripts/maintenance/build_release.py` and `scripts/repository_layout.json`; verify the source package independently and never include private local DVC settings.
- Keep Windows installer source files outside this repository in the sibling `visual-video-package/` directory; the source release must not include installer definitions or launcher source. `scripts/build_windows_release.py` writes artifacts to its `artifacts/` subdirectory by default and must fail clearly if the external sources are missing.
- Do not commit third-party vendor installer binaries. Virtual Serial Ports Emulator (VSPE) is downloaded from Eterlogic at setup time and must pass the pinned MSI SHA256 and publisher-signature checks before launch; check-only mode must remain offline.


## 进度、迁移与入口维护原则（2026-11-01）

- 单一操作入口：v3评分从原采集设备控制台的“开始行为评分”按钮进入，沿用设备、视频范围、被试、Session；不要重新增加独立评分BAT或默认切换到另一设备。进度表保持Session、采集视频、行为评分三列。已发布安装器兼容实现不因删除BAT而擅自删除。
- 区分事实与推断：观看完成、对应EEG文件可确认、行为评分完成是三个不同事实。全部视频已完成包含其情绪视频观看完成（Session 1、8：177普通＋69情绪＝246），不能据此虚构EEG有效性或评分答案；“仅情绪视频”是独立采集合同和目录，不是全部记录的筛选视图，不自动跨设备或范围合并状态。
- 原始记录是依据：保持session_state、原始EEG、事件、metadata及协议哈希。迁移只读解析当前被试/Session内原采集子目录，兼容旧绝对路径；资源引用使用resolve_project_path。不能用旧项目残留副本掩盖新目录缺失文件。区分选错入口、路径失效、文件缺失和真实采集异常，禁止笼统宣称“采集故障”或要求重采。trigger重建仅在核对视频身份、尝试、起止、分段与样本覆盖后另行审计，不能直接改完成标记。
- 最小存储与工作量：状态评估不复制或切分EEG，不建立磁盘缓存；一次刷新/批次共用临时metadata和文件检查索引，每段评分前重新检查。说明这是减少重复读取，不是减少已有数据体积；性能声明区分读取次数测试与实机耗时。迁移备份、BIDS、历史环境未经明确授权不得清理，不能以节省空间为由删除记录。
- 变更必须可交付、可解释：实施前说明入口/UI增删、理由和数据影响；交付时列明实际改动、目标目录/文件、需否重启/重装、源码与安装版区别、兼容范围和未解决问题。联动修改提供一致更新包并备份源码，避免只替换单文件。同步README、操作手册、发行清单与测试；验证迁移旧路径、设备/范围隔离、246/69计数、评分资格、真实窗口模拟采集与续跑，明确模拟不等于真实硬件验收。用户要求原分支时不新建分支；使用本AGENTS.md，不新建重复agent.md。
