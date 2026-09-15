# Emotion EEG V1：45组九级评分版本

仅供已有V1被试续跑和旧数据解释。统一入口勾选历史版本并选择“兼容：45组九级评分”。此版本保持1–9评分，不改成V2，也不自动迁移状态。下面按协议、评分依据、集成验证合并原文；原文“新实验”指2026年9月12日当时版本，不代表当前默认。


---

## 合并记录 1：EMOTION_EEG_PROTOCOL.zh-CN

> 2026年9月15日：本文保留V1及更早协议的历史说明。当前V2七级、喜好、抽查和疲劳流程见 [V2说明](emotion-v2.md)，最新硬盘部署见 [V2离线更新](../operations/OFFLINE_UPDATE.md)。

# Emotion EEG v1：主试操作与协议说明

新实验使用 `run_video_emotion_formal.bat`；先运行 `run_video_emotion_demo.bat` 检查。
现有 17/34 组被试继续用原入口；不得把旧进度迁入新协议。

## 1. 安装、材料和启动

Windows 10/11 64 位，完整解压源码后，双击根目录 `install_lab_env_uv.bat`，
或 `scripts/install_lab_env_uv.bat`。两者是同一个安装流程；不需要 Node.js。
健康的本地 `.venv` 可以继续使用。本次没有增加新的 Python 依赖。

Demo 首次启动自动生成四段合成练习素材：一个普通 trial、三个 emotion trial，
三类各一个、六次评分。练习类别仅用于测试流程，不是人工情绪标注，也不是正式刺激。
Demo 使用 dummy EEG，数据写入 `data/video_emotion_eeg_runs/demo`，不依赖完整视频库。

正式实验需要两套材料，源码 ZIP 不含视频：

1. 普通库：仍使用原 7,949 个正式视频。可通过 `download_materials.bat` 获取已发布的普通母库。
   下载包含额外不参与正式实验的视频，固定清单决定使用哪 7,949 个。
   标准布局为项目内 `stimuli/videos/0001.mp4...`；也支持项目旁 `../video_materials/formal_v1/videos`。
2. 情绪库：使用本次**最终验证后的** 3,138 个 eMotions 视频。最简单的离线部署是用硬盘复制现成的
   `emotion_video/selected` 和 `emotion_video/metadata/selected_videos.csv`，保留内部目录与文件名。
   不要复制最初抽样计划代替最终清单；最终集合中已有两个替换视频。

推荐目录：

```text
实验目录/
  visual-video-task/
    run_video_emotion_formal.bat
    run_video_emotion_demo.bat
    check_emotion_materials.bat
    stimuli/videos/                     # 原普通库，另一种外部布局也支持
    video_eeg/config/session_manifest_emotion_v1.csv
  video_materials/formal_v1/emotion_video/
    selected/
      positive/excitation/*.mp4
      positive/relaxation/*.mp4
      neutral/neutral/*.mp4
      negative/fear/*.mp4
      negative/sad/*.mp4
      negative/tension/*.mp4
    metadata/selected_videos.csv
```

若情绪库在另一块硬盘，在**项目根目录**新建 `emotion_library.local.json`，内容例如：

```json
{"emotion_root": "F:/Materials/emotion_video"}
```

这个路径指向包含 `selected` 的 `emotion_video` 文件夹；不要再把 `selected` 写进该字段。
此文件不进入 Git 或发布包。也可设置环境变量 `VIDEO_EEG_EMOTION_ROOT`，优先级高于该文件。
默认相对路径是 `../video_materials/formal_v1/emotion_video`，不要求其他电脑使用开发电脑盘符。

复制完成后双击 `check_emotion_materials.bat`：核对所有 11,087 个文件、ffprobe 时长和视频流，
并逐一验证情绪视频 SHA256。结果在 `logs/emotion_material_audit.json`。
不要重命名、裁剪、转码或调整正式视频的目录。缺少当前 Session 的视频时启动会报错，不会自动跳过。

若没有实验室硬盘副本，唯一原始来源是 [官方 eMotions 仓库](https://huggingface.co/datasets/Conna/eMotions)。
`emotion_source_index_v1.csv` 保存最终 ID、原始 parquet chunk、SHA256 和目标相对路径；
需从官方 parquet 的 `video_data` 恢复这些已选视频，并按该清单逐项核验。
公开 schema 没有可靠逐视频 platform 字段，本协议不猜测平台。
普通库的 GitHub Release **不包含这批情绪视频**。官方数据卡标记 Apache-2.0；
本仓库未据此推定所有第三方短视频均可再分发，因此没有把情绪视频再次上传到 Git/Release。
离线使用本实验已验证副本，或按官方适用条款取得原始材料。

正式启动：连接并检查 BrainCo/BCIGo、音频输出和数据盘空间，然后双击新 formal 入口。
填写被试编号和 1–45 的 Session 编号。正式入口要求真实 EEG，不能借用 Demo 记录作为正式数据。
设备配置仍在新 YAML 的 `device` 节；旧设备配置不被改写。新入口使用独立的
`VIDEO_EEG_EMOTION_CONFIG` 配置变量，避免旧 `VIDEO_EEG_CONFIG` 把新入口带回旧内容题流程。

## 2. 固定分组和播放顺序

全库共 11,087 个视频：普通 7,949，情绪 3,138；实际总净时长 67.64262 小时。
情绪库 17.46751 小时，三类各 1,046 个；原始类别 523 Excitation、523 Relaxation、
1,046 Neutral、349 Fear、349 Sad、348 Tension。

重新 ffprobe 发现普通视频当前文件时长与旧清单有小幅差异；本协议按实测总量分成 **45 组**：
每组 90.13296–90.22571 分钟，平均 90.19016 分钟。
46/47 组的平均值分别为 88.22951/86.35228 分钟，因此选 45 组更接近 90 分钟。
这是净视频时长，**不含评分、休息、连接、保存时间**，实际在场时间会更长，没有 90 分钟强制退出。

11 组正中负各 24 个，其余 34 组各 23 个；每组严格三类相等。
情绪三类每组各约 7.76 分钟；普通材料每组均覆盖原先五档长短视频。
分配只改变新协议的 Session 归属，旧 17/34 清单不变。

成员表 `session_manifest_emotion_v1.csv` 固定，不是播放顺序。
首次开始时按被试、Session 和保存的种子生成顺序；普通视频随机，情绪视频按普通视频累计时长均匀插入，
正中负交错，初始顺序避免连续三个情绪片段同类。S 重排或续跑后不保证该局部上限，但归属和总量不变。
队列在开始呈现前保存，续跑直接读取原队列，不能重新抽签。

## 3. 单个 trial 和按键

普通：注视 → 完整播放 → 短休息。

情绪：注视 → 完整播放 → **Valence → Arousal** → 短休息。

两次评分均是 1–9 整数、数字键直接选择、不限时、没有正确答案。
保持“先感受、后唤醒”的顺序；松开上一页的数字键再按下一次，避免长按跨页。
评分文字、锚点和文献见 [评分依据](emotion-v1.md)。
被试页面不显示正/中/负类别、原始标签、文件名或路径。
新协议不调用旧 alarm test、算术题、四选一题，也没有每组 18 次抽查。

短休息沿用默认 2 秒，空格可提前继续；两页评分结束之前不会进入休息。
长休息沿用累计实际观看约 30–45 分钟后提示，F 继续、J 保存退出；计时在视频边界检查，
不会为了精确踩中阈值打断正在播放的视频或两页评分。
评分和休息不计入净观看时间。S/Esc 前实际观看的部分，以及后续重播部分计入净观看累计。
完成百分比另外按已完成视频计算，避免重复观看使进度虚增。

S：当前视频记为未完成，稍后重新播放；情绪视频不进入评分。
Esc：保存退出。若在情绪视频或任一评分页退出，保留该 attempt 的部分记录，
下次完整重播视频，再从 Valence 开始重答两页。只有完整视频与两项评分一起提交后才算完成。
两页已提交后在短休息 Esc，不重播已完成视频。

## 4. EEG、事件和数据

EEG 从 Session 开始后持续采集，视频、两次评分和休息之间不 stop/start。
沿用 BrainCo、LSL、Neuracle 和 dummy 后端。真实硬件及声学/显示物理时延验证仍待主试完成。
`real hardware validation pending`。

| 新事件 | Marker |
|---|---:|
| EMOTION_VIDEO_ONSET / EMOTION_VIDEO_OFFSET | 150 / 151 |
| VALENCE_RATING_ONSET / VALENCE_RATING_RESPONSE | 152 / 153 |
| AROUSAL_RATING_ONSET / AROUSAL_RATING_RESPONSE | 154 / 155 |
| SHORT_REST_ONSET / SHORT_REST_OFFSET | 156 / 157 |

原普通 video_on/off 使用 132/133；旧协议的 marker 数值均保留。
页面和视频 onset 在 flip 回调记录；响应按键即时记录。每条事件保留相对/单调/日历时间、
sample_index、被试、Session、trial、attempt、video_id、标签和 eeg_part。
sample_index 属于对应 EEG 记录分段，应结合记录目录、eeg_part 和分段说明使用，不是跨恢复会话的全局序号。
BCIGo 外部 EDF 模式没有本地样本索引，值为 null；这时必须结合外部 EDF/LSL marker 对齐。

```text
data/video_emotion_eeg_runs/protocol_emotion_v1/<subject>/session_XX/
  session_state.json        # 恢复的权威状态；勿编辑/覆盖
  session_summary.json
  trial_log.csv             # ordinary/emotion、完整/跳过/中止、实际观看时长
  emotion_rating_log.csv    # 每个情绪 attempt 一行，含部分评分
  rest_log.csv              # 若发生长休息
  <timestamp>/
    continuous_eeg*.npy
    events*.json
    metadata.json
    eeg_segments.json
```

评分日志包含原始标签、三分类、路径、视频实际时长、valence/arousal 数值、RT、按键、onset/response、
样本索引、eeg_part、记录目录、completed/interrupted、replacement_reason。
分析时选择 `completed=True` 的最终 attempt；不把部分评分作为完成 trial。
这里没有 correct/accuracy 字段。`replacement_reason` 追踪材料提取时的替换，运行中不偷偷换刺激。

若 Excel 占用了 CSV，新协议将当前完整导出保存为同目录的 `.recovered_<time>.csv` 并记警告；
权威 Session 状态先保存。关闭 Excel 后再次退出/导出可恢复常规 CSV。真正的数据盘写入失败仍应由主试处理。
退出时即使行为摘要写入失败，也会尝试保存已经采集的 EEG。

当前采集器没有“某通道阻抗红色即终止”的自动阈值。设备后台明确抛异常会进入错误退出并尝试保存；
如果设备只是不再送样本、没有抛异常，现有实现不保证自动终止。
`events` 是阶段日志，**不是逐时刻阻抗或信号质量日志**。连续 EEG 可用于离线质控，
BCIGo 的阻抗/设备状态仍需主试现场监视。本次未添加未经验证的信号阈值或断流判定。

## 5. 离线更新及旧被试

先关闭范式，备份已有数据。用源码发布包更新 `video_eeg`、`scripts`、`docs`、新根目录入口；
保留本机 `.venv`、runtime、设备参数、本机路径配置，以及所有 `data`/records_storage。
不要从别的电脑复制被试 `session_state.json`；不要用新空数据目录覆盖已有目录。
将情绪视频另行通过硬盘复制到上述位置，并做材料审计、Demo、真实硬件短测，再开始新协议。
新采集数据写入独立 protocol_emotion_v1，旧数据保持原处。

| 被试原协议 | 续跑入口 |
|---|---|
| 新 Emotion v1，45 组 | run_video_emotion_formal.bat |
| 旧完整版 34 组内容题 | run_video_legacy_34.bat（原 run_video_formal.bat 也保留） |
| 旧完整版 17 组 | run_video_legacy_17.bat |
| 旧 2779 题版本 | run_video_legacy_2779.bat 或原部署入口 |

桌面旧 BAT 可能指向独立旧项目；为新协议建立新快捷方式，不覆盖正在采集被试的旧快捷方式。


---

## 合并记录 2：EMOTION_RATING_RATIONALE

> 2026年9月15日：本文保留V1及更早协议的历史说明。当前V2七级、喜好、抽查和疲劳流程见 [V2说明](emotion-v2.md)，最新硬盘部署见 [V2离线更新](../operations/OFFLINE_UPDATE.md)。

# 情绪评分的维度和量表依据

本协议测量观看者当时的主观体验：Valence（愉快—不愉快）和 Arousal（平静—激活），
两页固定先后顺序，均采用 1–9 整数、键盘选择、不限时。没有正确答案或准确率。
视频库的类别只用于刺激分组；被试自己的评分不由库标签推断。

Russell 的情绪环形模型以愉快程度和激活程度两个维度组织情绪：
兴奋与放松可以同属正效价，但激活程度不同。因此本库将 Excitation、Relaxation 映射到 positive；
Neutral 映射到 neutral；Fear、Sad、Tension 映射到 negative。
这只是本协议采用的类别映射，不声称每位被试必然体验到相同的效价。
原始字段保留 Sad 和 Excitation 的真实拼写，不改成 Sadness 或 Excitement。

- Russell, J. A. (1980). A circumplex model of affect. *Journal of Personality and Social Psychology*, 39(6), 1161–1178.
  [DOI](https://doi.org/10.1037/h0077714) · [论文全文](https://pdodds.w3.uvm.edu/research/papers/others/1980/russell1980a.pdf)。
- Bradley, M. M., & Lang, P. J. (1994). Measuring emotion: the Self-Assessment Manikin and the Semantic Differential.
  *Journal of Behavior Therapy and Experimental Psychiatry*, 25(1), 49–59.
  [DOI](https://doi.org/10.1016/0005-7916(94)90063-9) · [PubMed 原始摘要](https://pubmed.ncbi.nlm.nih.gov/7962581/)。

Bradley 与 Lang 的 SAM 工作支持将 pleasure、arousal 分开询问。本实现是**文字锚点的九级数字量表**，
借鉴这些维度及分开报告的思路，不复制 SAM 图像，也不将当前中文文字界面声称为已独立验证的 SAM 等价版本。
不使用 dominance，因为本次协议只要求两个维度。中文表述和键盘方式是本实验的操作化选择。

## 页面原文

Valence：**请评价刚才这段视频带给你的主观情绪感受。**

1 非常不愉快；5 中性；9 非常愉快。

Arousal：**请评价刚才这段视频引起的情绪唤醒程度。**

1 非常平静／几乎没有被激活；5 中等；9 非常激动／强烈被激活。

两个页面均显示数字 1–9 及“请按数字键 1–9 作答，答题不限时”。
RT 优先来自在页面 flip 重置的 PsychoPy 键盘时钟；无硬件键盘时间戳的测试适配器采用单调时钟轮询时刻。
事件同时记录按键时间和软件检测时刻。物理显示延迟、声学输出延迟和硬件 marker 延迟仍需实验室测量。

## 旧评分程序的使用范围

参考现有 jsPsych 评分程序的两页顺序、离散选项、无限等待和逐项保存设计。
原程序是五级鼠标选择；本协议按新要求实现九级键盘输入，直接接入 PsychoPy，运行不需要 Node.js。
不复制图片、被试记录或旧项目的个人配置。


---

## 合并记录 3：EMOTION_EEG_INTEGRATION_20260912

# Emotion EEG v1 集成记录 — 2026-09-12

## 审计与边界

先完成 [代码、入口、评分程序与材料审计](../maintenance/CHANGELOG.md)，再修改主项目。
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
