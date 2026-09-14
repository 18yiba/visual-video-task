# Video EEG Paradigm

新实验采用 **Emotion EEG v1**：在现有 PsychoPy 连续 EEG 框架中加入视频后的 Valence、Arousal 两页评分。
45 个固定 Session，每组约 90.13–90.23 分钟净视频；共 7,949 个普通视频和 3,138 个情绪视频，均恰好使用一次。
每个 Session 正/中/负数量完全相等。旧 17/34 组内容题协议和已有被试数据继续保留。

## 快速开始

实验室只有旧 17 组且不能联网：使用 [17 组到情绪协议的离线最小更新说明](docs/OFFLINE_EMOTION_UPDATE.zh-CN.md)，
只新增更新文件夹，复用该机环境和普通视频，另复制情绪库；无需先更新到 34 组。

1. Windows 10/11 64 位，完整解压源码，双击 `install_lab_env_uv.bat`。
   它转发至 `scripts/install_lab_env_uv.bat`，自动准备项目 Python 3.12 和依赖；不需要 Node.js。
2. 双击 **`run_video_emotion_demo.bat`**：自动生成四段练习视频，含三段 emotion trial、六次评分和 dummy EEG。
   不需要完整正式视频库。
3. 按 [新协议操作说明](docs/EMOTION_EEG_PROTOCOL.zh-CN.md) 放置普通库和最终情绪库，
   双击 `check_emotion_materials.bat` 完成 ffprobe/SHA256 审计。
4. 真实 EEG 连接、阻抗、声音和硬盘空间检查通过后，双击 **`run_video_emotion_formal.bat`**，填写被试编号及 1–45 的 Session。

正式模式默认 BrainCo SDK 直连、1000 Hz。软件测试使用 dummy EEG；真实硬件验证待实验室完成。
材料、环境、被试数据均不在源码 ZIP 中。已有健康 `.venv` 可以直接复用，无需为了新协议重装。

## 材料

普通视频沿用 [已发布母库](https://github.com/18yiba/visual-video-task/releases/tag/materials-v1-20260910)，
可运行 `download_materials.bat` 下载到 `stimuli/videos`，或复用项目旁的 `video_materials/formal_v1/videos`。

情绪视频使用最终验证后的 eMotions 3,138 文件，默认位置为项目旁
`../video_materials/formal_v1/emotion_video/selected`。可以通过硬盘复制本实验已验证的 `selected` 和最终 metadata。
自定义硬盘路径在项目根目录 `emotion_library.local.json` 设置，例如
`{"emotion_root":"F:/Materials/emotion_video"}`。
该本机配置不会上传。详细目录、官方来源和核验步骤见 [材料与部署](docs/EMOTION_EEG_PROTOCOL.zh-CN.md#1-安装材料和启动)。

普通母库 Release 不含情绪视频。eMotions 官方来源是 [Conna/eMotions](https://huggingface.co/datasets/Conna/eMotions)；
本仓库保留最终 ID、SHA256、来源 chunk 和目标相对路径，不再分发第三方情绪视频本体。
切勿用最初抽样计划覆盖最终清单，或自行剪辑、改名、替换正式视频。

## 操作和数据

普通视频自然结束后休息；情绪视频自然结束后依次评价主观感受、唤醒程度，各按数字 1–9、不限时。
没有正确答案，不再运行 alarm test。EEG 在视频、评分、休息之间持续记录。
短休息默认 2 秒，空格继续；累计实际观看约 30–45 分钟提示长休息，F 继续、J 保存退出。
S 将当前视频放回待播队列，Esc 保存退出；未完成视频/两页评分会在续跑时重新完整观看和评分。

新正式数据位于 `data/video_emotion_eeg_runs/protocol_emotion_v1`。
`session_state.json` 是恢复的权威状态；`emotion_rating_log.csv` 保存评分及部分 attempt，
`events*.json` 与连续 EEG 保存对应时序。不要手动修改状态或把旧协议进度迁入新协议。
90 分钟是净视频，不包括评分和休息，实际在场时间更长。

## 旧被试继续使用原协议

| 协议 | 入口 |
|---|---|
| 新 Emotion EEG v1：45 组 | `run_video_emotion_formal.bat` / `run_video_emotion_demo.bat` |
| 旧完整版 34 组：每组 18 次内容抽查 | `run_video_legacy_34.bat`；原 `run_video_formal.bat` / `run_video_demo.bat` 保留 |
| 旧完整版 17 组 | `run_video_legacy_17.bat` |
| 旧 2779 题 | `run_video_legacy_2779.bat` 或原部署入口 |

旧清单、题库、入口和数据不被覆盖。桌面旧快捷方式可能仍调用另一个旧项目，请为新协议新建快捷方式。

## 文档和目录

- [34组视频 EEG 被试与主试说明](docs/reports/视频EEG_34组_被试与主试说明.docx) · [在线阅读](docs/reports/视频EEG_34组_被试与主试说明.md)
- [45组融合情绪评分 被试与主试说明](docs/reports/视频EEG_45组融合情绪评分_被试与主试说明.docx) · [在线阅读](docs/reports/视频EEG_45组融合情绪评分_被试与主试说明.md)
- [本次仓库清理范围与验证](docs/REPOSITORY_CLEANUP_20260914.md)
- [新协议详细操作说明](docs/EMOTION_EEG_PROTOCOL.zh-CN.md)
- [九级 Valence/Arousal 评分依据](docs/EMOTION_RATING_RATIONALE.md)
- [完整主试手册与旧协议参考](docs/OPERATOR_MANUAL.zh-CN.md)
- [集成审计](docs/integration_audit.md) · [本次实施与验证记录](docs/EMOTION_EEG_INTEGRATION_20260912.md)
- [每组平衡统计](video_eeg/config/emotion_session_balance_v1.csv) · [全库唯一使用审计](video_eeg/config/emotion_global_usage_audit_v1.json)

```text
video_eeg/config/       # 新旧固定 manifest、设备及协议 YAML
video_eeg/experiment/   # 共用视频/EEG 框架及情绪评分 runner
video_eeg/devices/      # BrainCo、LSL、Neuracle、dummy
video_eeg/storage/      # 连续 EEG、事件和行为记录
video_eeg/utils/        # marker、恢复状态、视频库与顺序
scripts/               # 安装、入口、材料审计、分组、软件 smoke
docs/                  # 主试操作、协议依据、维护记录
stimuli/videos/        # 普通视频（源码只有空占位）
data/                  # 运行时生成；真实被试数据绝不发布
tests/                 # 自动测试
```
