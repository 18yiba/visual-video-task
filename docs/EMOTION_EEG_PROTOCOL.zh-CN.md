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
评分文字、锚点和文献见 [评分依据](EMOTION_RATING_RATIONALE.md)。
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
