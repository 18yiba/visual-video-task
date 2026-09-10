# 34 组与视频问题标签审计（2026-09-10）

## 用户确认的时长口径

每个 Session 的**视频净时长**接近 90 分钟即可，不强制到点结束。
每组都应有各种长短视频，组内随机播放。注视点、间隔、答题、休息不计入净视频时间。

## 新分组

- 正式视频仍为 7949 段，净时长总计 50.2984 小时，没有增删或重命名视频。
- 当前分为 34 个 Session，每组 233–235 段，净视频 88.3501–88.9355 分钟，平均 88.7619 分钟。
- 每个旧 Session 分成两半：旧 n → 新 2n−1、2n；跨旧组的视频集合保持原边界。
- 采用原全库的五档时长标签，按每档数量及累计时长平衡分配，两半均包含五档，每档至少 46 段。
- 五档约为 5.107–12.725、12.725–15.117、15.117–20.061、20.061–33.598、33.598–59.976 秒。
  边界同值的视频按稳定排名归档，详细定义保存在清单中。
- 默认组内顺序随机，每个新 Session 从有题视频中分层随机选 18 个不同目标。
  队列和问题绑定随 state 保存，续跑不重新洗牌，S 中断后按原协议重播。

权威清单：`video_eeg/config/session_manifest_34.csv`。
逐组统计：[session_34_summary.csv](../video_eeg/config/session_34_summary.csv)。
机器可读审计：[session_34_audit.json](../video_eeg/config/session_34_audit.json)。
重现算法：`scripts/build_34_session_manifest.py`；已有不同清单时拒绝覆盖。

## 旧进度兼容

旧 `session_manifest.csv` 的 SHA-256 保持
`56dc9fa3bcfeb90c5e42fdccc114c633dc9284dba6e17295e4f95de7671679b9`。
旧完整版 17 组配置保存为 `video_legacy_17_config.yaml`，入口 `run_video_legacy_17.bat`，
数据仍为 `data/video_question_complete_runs/<subject>/session_<NN>`。
新默认正式数据为 `data/video_question_complete_runs/protocol_34sessions/<subject>/session_<NN>`。
没有改写任何既有 state、题库快照、原始 EEG 或完成状态。新旧方案不能混用同一 Session 进度。

## video_materials 中的 label 核对

本机实际目录是 `video_materials/formal_v1/videos`，共 7996 段视频。
用户文字中的 `video/video/_materials` 嵌套目录不存在。
母库 `manifest.json` 只有 `id`、`file`、`size_bytes`；旁边的 SESSION、VIDEO_POOL 表提供时长和旧分组，
没有 alarm test 题目及正确答案。

当前题目位于程序 `video_eeg/config/complete_questions_20260908/question_bank.json`，
以 `video_file` 匹配原始视频文件名。工作主项目与旧完整版副本的题库 SHA-256 相同：
`6ed36faaccdb4b4d3982c1304ae1252967dd50e2543353c2707fc4231ed2466a`。
这不是已将题目烧录在视频画面、字幕或 MP4 标签里的另一套视频。

新增 [video_question_labels.csv](../video_eeg/config/video_question_labels.csv) 将信息统一到每段视频一行：
文件名、SHA-256、大小、是否进入正式组、时长档、当前 34 组 ID、旧 17 组 ID、
是否有题、题干、四选项、答案、来源与复核状态。Release 元数据包附带同一表。
题库内历史 `session_id` 仅为来源信息，新分组以 34 组清单为准；无需修改题库以重分组。

共 7993 道题，三段缺题 `5728.mp4`、`6722.mp4`、`6883.mp4`；三段仍播放但不被抽查。
47 段超过 60 秒的母库视频保留在下载包和标签表中，不进入正式 Session。
2779 道原题已复核，5214 道新增题尚未独立复核，不能称为全部题目已人工核验。

## 验证与同步

34 组测试核对视频无遗漏重复、原组两半并集不变、各组时长与五档覆盖、18 次视频绑定抽查、
不同随机种子的播放差异、续跑保存稳定性以及新旧记录目录分离。
实际材料检查覆盖 7949 个正式文件，34 组均有足够题目。
当前本机自动化测试 59 项通过。通过正式入口加载 Session 34 的真实 PsychoPy 窗口验证，
测试工具仅将采集后端替换为模拟 EEG：234 视频队列、18 个唯一抽查目标、安全退出与连续信号保存均通过。
生产正式入口仍禁止直接用 `--dummy-eeg` 开始正式实验；本测试不连接真实设备。
本次分组、安装/退出修复、下载器、标签表、空目录占位及文档一起纳入 GitHub 源码发布；
视频通过独立 Release 分发，所有本地实验数据继续排除。
