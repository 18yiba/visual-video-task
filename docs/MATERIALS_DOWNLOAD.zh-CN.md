# 正式视频库下载与核验

完整视频附件已公开，见 [材料发布状态](MATERIALS_UPLOAD_STATUS.md)。

## 统一下载位置

全部材料位于同一仓库的 [materials-v1-20260910 发布页](https://github.com/18yiba/visual-video-task/releases/tag/materials-v1-20260910)。
代码与题库从 [仓库首页](https://github.com/18yiba/visual-video-task) 的 Code → Download ZIP 获取并完整解压。
发布页自动附带的 Source code ZIP 是代码，**不是视频库**。

材料版本包括：

- `videos-001-of-084.zip` 至 `videos-084-of-084.zip`：84 个独立 ZIP，合计 7996 段原始视频，约 44.2 GB。
- `material_metadata.zip`：对应的完整题库、固定 Session 清单、排除清单和覆盖报告的备份。
- `materials_manifest.json`：每个包和每段视频的文件名、字节数、SHA-256；代码也随附同一清单。

包编号只是下载分包，不代表 Session。每个包均可单独解压，不需要拼接或改扩展名。
GitHub 对单个 Release 附件有 2 GiB 上限，因此本库按约 512 MiB 分包；
参见 [GitHub 官方 Release 说明](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)。

## 推荐：双击自动下载

1. 完整解压代码到本地可写目录，例如 `D:\Experiments\visual-video-task`。
2. 双击根目录 `install_lab_env_uv.bat`，等待 `Environment ready`。
3. 双击根目录 `download_materials.bat`。无需 GitHub 登录或另装 Python。
4. 等待显示 `Verified 7996 videos`，再运行 `run_video_demo.bat` 检查显示、答题与记录。
5. 按操作说明完成设备检查后运行 `run_video_formal.bat`。

下载器默认写入当前项目的 `stimuli/videos/`，逐包下载、校验、解压并删除已使用的临时 ZIP。
网络中断后重新双击即可：已校验的视频不会重下，未完成的下载支持续传；服务器不支持续传时自动重下当前包。
下载缓存位于 `.materials_download/`，运行失败会保留以便重试。
请至少预留约 50 GB 给视频及临时包，另给 Python 环境和后续 EEG 记录预留空间。
下载期间不要运行正式实验；应完成全部校验后再采集。网速决定总耗时。

如果已有实验室母库 `../video_materials/formal_v1/videos`，无需重复下载，执行：

```powershell
.\.venv\Scripts\python.exe scripts\download_materials.py --verify-only --destination ..\video_materials\formal_v1
.\.venv\Scripts\python.exe scripts\audit_question_bank.py --require-materials
```

## 手动或离线部署

1. 在发布页 Assets 中展开全部附件，下载全部 84 个 `videos-*.zip` 及清单；不要只下载第一包。
2. 将所有视频 ZIP 解压到项目的 `stimuli` 文件夹。每个包自带 `videos/` 这一层。
3. 最终路径必须是 `项目\stimuli\videos\0001.mp4`，不能多一层 `videos\videos` 或按包名分文件夹。
4. `material_metadata.zip` 可解压到独立材料备份目录。源代码已经带题库及分组清单，**无需用备份覆盖代码配置**。
5. 在项目目录执行完整校验：

```powershell
.\.venv\Scripts\python.exe scripts\download_materials.py --verify-only
.\.venv\Scripts\python.exe scripts\audit_question_bank.py --require-materials
```

离线电脑可接收已核验的视频文件夹；Python 依赖首次安装仍需按环境说明准备联网条件。
若保留所有压缩包再解压，视频与 ZIP 两份合计约 88.4 GB，需额外预留环境和记录空间。
完整复制文件，不要转码、重命名、去掉编号前导零或重新分组。

## 程序如何找到视频和题目

新电脑使用 `stimuli/videos`。兼容实验室既有的 `../video_materials/formal_v1/videos`，该母库存在时默认优先使用它。
不要同时放两套内容不同的母库。若自定义位置，在 `video_eeg/config/video_config.yaml` 的
`protocol.video_library_dir` 填写实际视频目录；Demo 配置也需作对应修改。
`--destination` 只决定下载位置，参数应为 `videos` 的父目录，不会自动修改实验配置。

正式清单为 `video_eeg/config/session_manifest_34.csv`，包含 7949 段，固定分配为 34 个 Session。
47 段超过 60 秒的视频随母库保留，但不进入正式流程。
题库为 `video_eeg/config/complete_questions_20260908/question_bank.json`，按文件名精确绑定视频。
每个 Session 从有题的视频中抽 18 个目标，在对应视频自然结束后立即提问；不是每段都提问。

当前快照是 **7993 道题**，覆盖正式视频 **7946/7949**。
`5728.mp4`、`6722.mp4`、`6883.mp4` 暂无题，仍播放但不抽查。
2779 道原题复核通过，新增 5214 道标记为 `generated_unreviewed`，不能据此宣称已逐题人工复核。
各 Session 均有足够题目生成 18 次抽查。`--require-full-coverage` 在此版本会失败，这是已知覆盖缺口。

下载校验器同时核对代码中的题库与分组哈希，避免混用版本。
正在进行的 Session 已保存题库哈希和快照，不要中途更换题库、清单或删除断点。
若同名本地视频与发布清单不一致，工具停止并保留原文件，请先核对来源再由主试另存处理。

## 空目录与数据

仓库中的 `stimuli/videos/`、`data/video_question_complete_runs/`、`data/sourcedata/`
各含一个空 `.gitkeep`，仅用于让 ZIP 和 Git 保留目录结构。
不会附带开发电脑的被试记录。下载视频不写 `data`；运行后记录只在本机生成。
当前正式输出写入 `data/video_question_complete_runs/protocol_34sessions`，`data/sourcedata` 为旧数据兼容目录。

完整安装、键盘操作、续跑及备份见 [详细操作说明](OPERATOR_MANUAL.zh-CN.md)。

## 当前 34 组与旧 17 组

7949 段正式视频总净时长约 50.30 小时。新分组每组 88.35–88.94 分钟，平均 88.76 分钟，
每组 233–235 段，五档视频各至少 46 段；全库正式视频范围约 5.107–59.976 秒。
每个原 Session 按五档时长均衡拆为两半，原 n 对应新 2n−1 和 2n。各组内部随机播放；
播放顺序和 18 个抽查目标在开始时保存，续跑不重新抽签。没有 90 分钟强制停止。
注视点、视频间隔、答题及休息不计入净观看，实际占用时间会更长。

当前权威分组为 `video_eeg/config/session_manifest_34.csv`。
旧 `session_manifest.csv` 保留原 17 组，不能用新文件覆盖旧文件。
旧完整版 17 组请用 `run_video_legacy_17.bat`，其数据仍在 `data/video_question_complete_runs/<subject>`。
新默认入口用 `data/video_question_complete_runs/protocol_34sessions/<subject>`，避免同编号读到旧状态。
不自动迁移已开始的旧 Session，不把旧完成进度强行当作新分组的完成进度。

`video_eeg/config/video_question_labels.csv` 是 7996 段视频的完整标签对照表；
包含 SHA-256、题干、选项、答案、复核状态、`session_34` 和 `legacy_session_17`。
Release 的 `material_metadata.zip` 也包含此表。题目经 `video_file` 文件名关联，未嵌入 MP4 画面或字幕。
原题库可能保留历史 `session_id`，当前分组以 34 组清单和标签表的 `session_34` 列为准。
详见 [34 组与标签审计](SESSION_34_AND_LABEL_AUDIT.zh-CN.md)。
