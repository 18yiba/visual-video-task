# Emotion EEG v1 集成记录 — 2026-09-12

## 审计与边界

先完成 [代码、入口、评分程序与材料审计](integration_audit.md)，再修改主项目。
Git 基于远端 master `9a5e3dd` 新建 `emotion-eeg-v1` 分支。
主框架继续使用 VideoRunner、EegSessionManager、SessionRecorder 和现有设备/播放器；
新增加 EmotionVideoRunner 与评分/队列辅助模块。未引入 Node.js、ML 数据集对象或新运行依赖。

现有独立旧项目、所有被试数据、旧题库快照、17/34 清单和旧根目录 BAT 均保留。
保存前基线在本机 `_maintenance/integration/baseline.json`，不公开被试路径或记录。
旧内容题 runner 的逻辑不变；共用 VideoRunner 的扩展由新协议标记/子类 hook 控制。
真实硬件验证不在本次软件结果中：**real hardware validation pending**。

## 材料和 Session

采用最终 `selected_videos.csv`，没有重新下载或重新抽样，没有删除源 parquet。
3,138 个情绪 MP4 全部 ffprobe/哈希通过，包含提取阶段已完成的两个 replacement。
来源 ID、chunk、最终相对路径、SHA256 位于 `emotion_source_index_v1.csv`。
不推断逐视频平台，不改写 Sad/Excitation 标签，不裁剪、不转码。

| 材料 | 数量 | 实测净小时 |
|---|---:|---:|
| 普通正式视频 | 7,949 | 50.175110 |
| Positive | 1,046 | 5.823064 |
| Neutral | 1,046 | 5.822523 |
| Negative | 1,046 | 5.821925 |
| 全部 | 11,087 | 67.642622 |

原始六类：Excitation 523、Relaxation 523、Neutral 1,046、Fear 349、Sad 349、Tension 348。
普通文件重新 ffprobe 后总时长比旧表约少 7.39 分钟，仅新表使用实测值，旧表不改。

自动比较满足平均 85–95 分钟的 43–47 组方案：45 组平均 90.19016 分钟最接近目标；
46 组 88.22951、47 组 86.35228 分钟。因此选 **45 Sessions**。
实际各组 90.13296–90.22571 分钟，标准目标内，无强制截止。
11 组各类 24 个；34 组各类 23 个。每组情绪净时间 23.28743–23.29166 分钟；
每组正中负净时长的最大差不超过 0.197 秒。普通材料每组五档长短齐全。

新清单 SHA256：`cf59e1d8550d6945d61a68b55a8c9a52479ee0dfa3f3d3295d653ba0af476a23`。
旧 34 清单：`cf72477e07bd15b929da45d58ed04cd4e5069695fd4e2fd5cc55fee9153d6488`。
旧 17 清单：`56dc9fa3bcfeb90c5e42fdccc114c633dc9284dba6e17295e4f95de7671679b9`。
Builder 固定种子 20260912，按最终文件时长分配成员；运行队列按被试/Session 和保存种子随机并持久化。

## 评分、计时与记录

情绪自然 EOF → Valence → Arousal → 短休息；两项均 1–9、键盘、不限时。
部分评分保存在 attempt 内，重启后重播视频并重答两页；只有完整两项才提交视频。
原视频后不评分；新协议 attention_tasks_per_session=0，不创建内容题记录。
评分页不含类别、原始标签或路径。九级文字量表与 SAM 的区别、引用、锚点见评分依据文档。

新协议禁用旧播放器提前 0.25 秒按计划时长完成的条件，检测提前 EOF，保持原视频内容和音轨。
显式检测已知音轨加载/播放启动错误，避免静默转为无声播放。
视频首帧、评分 onset、短休息边界通过 flip 回调；响应含键盘 RT、检测时间及样本索引。
新增 150–157 marker，原 101–142 定义保留。emotion trial_end 在两项评分后记录。
EEG 不因评分/休息重启；每个恢复记录保留自身 EEG 分段及索引语义。

净计时采用实际普通+情绪播放，含中断/重播部分；不含评分/休息/加载/保存。
完成百分比依据已完成视频计划时长单独计算。F/J 长休息、空格短休息、S 重排和 Esc 保留。
CSV 被占用时写可恢复副本，先保存权威 state；退出仍尝试导出 EEG，避免派生 CSV 失败阻断采集保存。

## 验证

- 全部 11,087 个视频可读取；情绪 3,138 个 SHA256 与最终清单完全相同，5–60 秒，无完全重复。
- 自动测试：81 passed。包括旧协议回归、唯一归属、每组时长/数量平衡、标签、marker、正式/Demo 入口分派与新电脑路径、
  键值边界、持久化部分评分、出口写盘失败时 EEG 仍导出。
- 真实 PsychoPy 窗口 + dummy EEG：4 个练习 trial、3 个情绪 trial、6 个评分；
  视频/Valence/Arousal 各阶段 Esc，随后重播恢复；S 跳过后重播；短休息和 F 长休息页均执行。
  已核对 marker 顺序、sample_index、连续 EEG NPY、评分 CSV 和净时钟。8 个场景通过。
- 另用正式 eMotions 三类各一个真实片段验证原视频和音频加载/输出启动、六页评分、EEG 保存，通过。
  软件能确认音频流启动，不等同于人工听音或硬件声学延迟校准。
- 评分截图已在本机人工式视觉检查：中文、九级数值和端点清楚，没有刺激标签。
- 初始 pytest 默认临时目录受 Windows ACL 阻止；改用独立可写测试目录后通过。
  此错误不是协议代码测试失败。未修改系统 ACL 或删除原临时文件。
- 发布源码副本：79 passed、2 skipped（两项依赖本机完整普通库的测试已在主工作区通过）；
  无正式材料的独立源码副本自动生成练习片段，真实窗口下 8 场景 dummy EEG smoke 再次通过。
- 本次未重新从零联网安装全部依赖；源码副本验证复用了现有健康 Python 环境。

## Hard assertions

| 要求 | 结果 |
|---|---|
| 全部 3,138 情绪视频恰好一次，全局各类 1,046 | PASS |
| 每个 Session 正中负数量相等 | PASS |
| 原 7,949 正式视频恰好一次 | PASS |
| 各 Session 净视频 85–95 分钟 | PASS |
| 自然完成情绪片段恰好 Valence + Arousal，各 1–9 | PASS |
| 评分页不暴露标签 | PASS |
| EEG 持续、marker/索引、长短休息、实际净计时 | PASS（软件/dummy） |
| 视频及两页退出恢复，S 重播 | PASS |
| 旧 17/34 清单和数据不覆盖 | PASS：332 个基线文件共 3,378,373,740 字节哈希不变 |
| 源码不包含被试数据或视频二进制 | PASS：仅复制源码白名单中的本次改动 |
| 自动测试与 dummy smoke | PASS |
| 真实 EEG 硬件/物理音视频时延 | PENDING |

## 发布记录

分支：`emotion-eeg-v1`。仅同步 `scripts/build_release.py` 白名单内的本次修改。
保护基线 332 个文件均通过逐字节 SHA256 核验。

- 实现提交：`fbed956`（评分/连续 EEG/恢复）、`737a44c`（45 组清单）、
  `c302cf3`（测试和材料核验）、`e2a53b6`（文档及 Windows 入口）。
- PR：[Integrate valence-arousal emotion trials into the video EEG protocol #3](https://github.com/18yiba/visual-video-task/pull/3)。
- 远端合并前基线：`9a5e3dd2a1bbe26986126cc67946cddee1f05413`。
- 源码发布白名单：35 个本次改动文件；没有新增 data、stimuli 视频、环境或本机路径配置。
- Git 直连超时后使用本机已配置代理完成 fetch/push，未修改全局代理设置、未 force push。
- PR 状态：MERGED，2026-09-12 08:42:19 UTC。
- PR 合并 SHA：`d7411b641404c1f86ec68d95c75485e09695789e`。
- 合并后核验的 master HEAD：`d7411b641404c1f86ec68d95c75485e09695789e`。
  后续发布记录提交仅补充本文，不改变已验证的协议代码；最新 HEAD 可用 `git rev-parse origin/master` 查询。
- GitHub 发布成功：PASS。发布前后的旧数据保护基线一致，视频和被试数据均未进入本次提交。
