# visual-video-task maintenance instructions

## First principles

- Evidence before interpretation: video completion, corresponding EEG file presence, EEG validity, and behavior-rating completion are separate facts. Never infer signal quality or missing answers from video counts, session summaries, event markers, or another status field. Report observations and uncertainty separately.
- Preserve the source of truth: native EEG, events, metadata, protocol snapshots/hashes, behavior logs, and `session_state.json` govern recovery. BIDS/EEGQC are derived copies; they never replace or overwrite source records. Preserve historical identifiers and formats.
- Fail closed on ambiguity: distinguish wrong entry, stale path, missing file, and acquisition failure. Stop with the conflicting paths when state roots disagree. Never hide a missing file with an old project copy or silently rewrite completion state.
- Minimize side effects: progress inspection is read-only; do not copy/split EEG, add persistent caches, migrate records, or clean unknown files to improve a status screen or save space. Reuse in-memory metadata within a refresh, recheck eligibility before each rating, and preserve backups and old environments.
- Make changes auditable and deliverable: before UI/entry changes, state what changes, why, and the data impact. Update linked docs, release lists, and tests together. Report exact outputs, restart/reinstall needs, source-versus-installer differences, compatibility, and unverified hardware assumptions.

## Study and protocol contracts

- Public protocol selection contains exactly v1 (17 fixed Sessions) and v2 (45 fixed Sessions, EEG plus ratings), each retaining Demo/Formal. v3 is a separate device workflow; do not add it as a third public v1/v2 selector option.
- Preserve Session membership, question-bank/material hashes, protocol IDs, source/review status, participant recordings, and snapshots. Public version names or project identity must never rewrite persisted IDs, paths, or answers.
- v1 keeps 18 video-bound checks. v2 keeps 9 attention checks at roughly ten net-minute intervals, followed immediately by its five-point fatigue item; ordinary-video F/J liking and seven-point valence/arousal remain as specified. Incomplete trials replay and resubmit under the original contract.
- Fatigue is a study-specific, literature-inspired item, not a validated scale. Wording: `当前您的疲劳程度是？`; endpoints are `1 几乎不疲劳` and `5 非常疲劳，完全无法继续观看`. Preserve the five option texts and revision history. Existing binary/seven-point Sessions retain their original contract; never convert prior answers.
- v3 behavior rating starts from the current acquisition device console’s “开始行为评分” button and retains device, range, subject, and Session. Do not re-add a standalone rating BAT or silently switch devices. Progress stays three columns: Session, acquisition videos, behavior ratings. Keep already-published installer shortcuts compatible; do not remove them without an explicit request.
- “All videos” includes its emotional videos: Sessions 1 and 8 each represent 177 ordinary + 69 emotional = 246 videos. “Emotional-only” is its own acquisition contract and directory, not a filtered aggregate. Never merge progress across device, range, or contract. Viewing all videos does not prove EEG validity or completed ratings.

## Records, migration, and recovery

- New v1/v2 subjects use `data/sourcedata/v1` or `v2`. Resume existing `complete`, `protocol_emotion_v2`, `sourcedata/legacy17`, and `emotion-v2` subjects in place. Conflicting roots stop with an explanation; do not create a replacement subject to bypass a conflict.
- Migration reads only the current subject/Session acquisition directories, supports old absolute paths, and uses `resolve_project_path` for resources. Do not move or copy records unless explicitly authorized. Preserve original data and verify backups/hashes before any authorized migration.
- Preserve `session_state.json`, original EEG segments, events, metadata, protocol hashes, and question-bank snapshots. A BIDS export is an independent post-save copy. Historical Neuracle NPY remains readable and untouched; new Neuracle recordings are EDF with forwarded channel order and TRG row. Unknown units/reference/filter metadata remain unknown.
- Trigger reconstruction requires a separate audit of video identity, attempt, start/end, segments, and sample coverage. Never rebuild triggers or mark a video complete from assumptions. Distinguish file presence from signal quality and real hardware health.
- Status evaluation must not duplicate or split EEG or create disk caches. One refresh/batch may share temporary metadata/file-check indexes in memory; recheck each rating before launch. This reduces repeated reads, not stored data volume.
- Preserve existing Windows EXE 1.0.1 migration behavior: verified local config snapshots and data copies under `Desktop/video/data/sourcedata`; original records remain untouched. Never infer that unused historical code, environments, metadata, or unknown files are disposable.
- Specific authorized v2 exception (2026-09-19): exclude `original:vid_6076` (20), `original:vid_2693` (24), and `original:vid_6241` (33). Preserve immutable base manifest/hash and v1/shared media; effective manifest has 11,084 rows. Back up state first, preserve attempts/completions/answers, audit necessary unanswered-question rebindings, and retain completed Sessions as history. This is the only stated exception to membership preservation.

## Source architecture and acquisition-task template

- Runtime implementation and protocol resources live in `src/video_eeg/`, including `src/video_eeg/config/`. Root `video_eeg.py` is the compatibility shim; never recreate a root `video_eeg/` directory. Keep protocol resource bytes unchanged. Resolve persisted `video_eeg/config/...` references through `resolve_project_path`; new paths use `src/video_eeg/config/`.
- `main.py`, `python -m src`, `RUNME.bat`, and device BATs route to the existing CLI. `RUNME.bat` is required by the current template and only forwards to `run_experiment.bat`; it contains no second launch implementation. Preserve the three device-specific v3 entries. Do not add an independent rating BAT.
- `config/config.toml` has strict, known fields and nonempty `[experiment]`, `[device]`, `[storage]` sections required by the template. These are identity/deployment metadata only; runtime routing reads `[launcher]`. `EMOVID-20261008` identifies assets/archive prefixes only and never replaces protocol IDs or participant paths. Keep local overrides out of Git and source releases.
- Keep the project source-only: `pyproject.toml` uses `package = false`; do not build/install this project, generate console aliases, or restore editable-install instructions. `uv.lock` covers tooling/candidate dependency groups. Do not sync the existing lab environment until dependency and real-window acceptance passes. Preserve `runtime/python312` and installed development environments.
- The template-required files and source-release allowlist are maintained together in `scripts/repository_layout.json` and `scripts/maintenance/build_release.py`. Verify a relocatable source package independently. Never include participant records, video binaries, environments, caches, credentials, or `.dvc/config.local`; publish public material releases separately.
- `docs/README.md`, `docs/deploy.md`, `docs/data-format.md`, and `data/README.md` explain deployment and data boundaries. `data/README.md` is documentation, not an output placeholder.
- Shared `.dvc/config` is anonymous read-only. Upload profiles belong in ignored `.dvc/config.local`; DVC materials are separate from participant records and are not fetched automatically during trials. Only empty `stimuli/videos/.gitkeep` and `data/sourcedata/.gitkeep` are source placeholders.
- Before reusing an environment or packaging site-packages, check for obsolete project distributions, console entry points, and project-specific `.pth`/`.egg-link`. The installer may preserve and replace an obsolete environment using its backup flow; the bundle builder must stop rather than copy project aliases.

## Device, BIDS, and Windows packaging

- Native recording/recovery remains primary. The BrainCo BIDS profile is lab-confirmed for 31 EEG channels plus the first counter row, µV, and IO; do not apply these assumptions to another device. Preserve protocol/part identity, behavior fields, and missing-EEG timing flags.
- Bundle the official offline BIDS validator with Deno and validate all TSV rows without network access. Structural validation does not certify signal quality or hardware. README and `docs/operations/BIDS_EXPORT.md` must explain automatic export, manual retry, historical records, and source/BIDS boundaries.
- Keep Windows installer definitions, launcher source, and installer assets outside this repository in sibling `visual-video-package/`. The source release excludes those definitions/assets. The installer must work from a fresh Windows source download. `scripts/build_windows_release.py` writes to that directory’s `artifacts/` by default and fails clearly if external sources are missing. Never overwrite an existing release artifact; use a new version directory and record the source commit and hashes.
- Do not commit vendor installer binaries. VSPE is downloaded from Eterlogic during setup and must pass the pinned MSI SHA256 and publisher-signature checks before launch. Check-only mode remains offline.

## Required edit and validation workflow

- Before code edits, read `README.md`, `docs/maintenance/CHANGELOG.md`, and `docs/operations/EEG_AND_RECOVERY.md`; use `docs/versions/v1.md` and `v2.md` for protocol details.
- Test affected paths, strict metadata/TOML validation, source-only release, and both source entries. After launcher changes, test the real PsychoPy window with dummy EEG and clearly label simulation; it is not real hardware acceptance. Hardware acceptance remains an explicit separate result.
- For migration/status changes, verify legacy paths, device/range isolation, 246/69 counts, rating eligibility, and interrupted-session resume. Distinguish file-read-count tests from measured on-device time.
- Retired public versions stay excluded by the release allowlist, but do not recursively delete their local code, materials, or recordings. Verify Windows deletion targets and never traverse junctions. Preserve unknown files and backups unless their removal is explicitly authorized.
- When the user requests the existing branch, keep it; do not create another branch. Use this `AGENTS.md`; do not create a duplicate `agent.md`.

## 上传与合并分支：以证据决定是否放行

- 先确认操作对象与授权：核对当前分支、HEAD、远程仓库完整名称、PR来源和目标分支；沿用本会话已确认的授权，不反复询问。上传分支、合并PR、发布安装包是不同动作，上传授权不代表允许合并或发布。只在目标不明确、权限不足或自动审批明确要求时请求必要确认，并说明具体阻碍。
- 上传只包含可交付变更：逐项审查暂存差异和新增文件，明确列出要提交的文件；排除被试数据、凭据、本地配置、环境、缓存、测试产物及无关审计文档，保留本机未知文件。README、操作说明、变更记录和发行清单须与实现一致，明确源码与安装包差异、升级方式和未验证事项；推送后核对远程分支SHA与本地提交一致。
- 验证针对实际改动：按受影响路径运行测试，检查严格metadata/TOML、锁文件与依赖一致性、两个源码入口及可迁移源码包；依赖验证使用隔离环境，不同步正在使用的实验环境。入口改动还须验证真实PsychoPy窗口配合模拟EEG；文档改动检查准确性、链接与发布边界，不为凑数重复全套测试。记录验证命令、结果及对应提交；软件测试、模拟采集和真实硬件验收分别报告。
- CI状态必须追溯到日志：按当前PR头提交及实际测试的合并提交核对push/pull_request各运行、操作系统、步骤、结果和重跑次数。失败、取消、跳过、排队均不算通过；区分代码/锁文件错误与下载504等基础设施故障。先读首个失败步骤，再修复代码或重跑失败/连带取消任务，并跟进最终结果；不靠空提交、关闭检查或忽略失败来制造绿灯，旧提交成功不能证明新提交通过。
- 合并前重新核对：只有获得合并授权，且当前提交所需检查通过、审查要求满足、冲突及未解决问题已处理，才执行合并；“No conflicts”只说明Git可合并，不代表程序正确。基线或头提交变化后重新确认相关验证与CI；基础设施故障未恢复时说明阻碍，不宣称可安全合并。合并后核对目标分支及合并SHA，报告PR/提交链接与剩余限制；合并不等于发布EXE，不自动删除分支或覆盖已有发行产物。
