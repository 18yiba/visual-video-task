# 数据目录、续跑、采集日志与断流保护

## 统一入口的数据规则

新被试默认写入data/sourcedata/<协议>/<被试>/session_XX；协议为legacy17、legacy34、emotion-v1、emotion-v2或legacy2779。Demo单独位于data/sourcedata/demo/<协议>，并保留每次练习的run子目录。明确--seed的测试运行也可产生run子目录，不得拿测试路径冒充普通正式进度。

选择版本后，启动器只在该协议的新目录、YAML指定目录和已知旧目录查找当前被试的session_state.json。已有进度继续用原根目录，包括后续新Session；不搬文件、不重新创建被试、不覆盖旧题库快照。同一被试在两个候选目录都有状态时停止并列出路径，由主试核对，不自动猜选。旧入口/离线包未启用统一启动器时仍按其原配置保存。

| 协议 | 已知旧保存根目录 | 新被试默认根目录 |
|---|---|---|
| 17组完整版题库 | data/video_question_complete_runs | data/sourcedata/legacy17 |
| 34组 | data/video_question_complete_runs/protocol_34sessions | data/sourcedata/legacy34 |
| 45组九级 | data/video_emotion_eeg_runs/protocol_emotion_v1 | data/sourcedata/emotion-v1 |
| 45组七级 | data/video_emotion_eeg_runs/protocol_emotion_v2 | data/sourcedata/emotion-v2 |
| 旧2779题 | data/video_question_runs | data/sourcedata/legacy2779 |

这些旧目录没有删除。项目中历史data/sourcedata已有其他格式记录也不清理；新数据使用明确协议子目录避免碰撞。若只复制EEG、不复制状态和题库快照，不能恢复已完成进度。统一规则不是数据格式转换，也不是BIDS转换。

## 每个文件的含义

| 文件 | 用途与操作边界 |
|---|---|
| session_state.json | Session恢复依据，保存队列、attempt和完成状态；不可手改或用其他被试覆盖 |
| question_bank_snapshot.json | 本次实验题库快照；与哈希匹配，不随意替换 |
| session_summary.json | 进度摘要，不等价于EEG质量通过 |
| trial_log.csv | 视频各次观看、退出、重播及样本相关时间 |
| video_question_log.csv / attention_log.csv | 内容题与回答；不同协议字段略有不同 |
| video_liking_log.csv / fatigue_log.csv / ordinary_behavior_log.csv | V2喜好、疲劳及联合行为记录 |
| emotion_rating_log.csv | V1/V2效价、唤醒、反应时间与量尺版本 |
| rest_log.csv | 休息出现、选择及停留时间 |
| YYYYMMDD_HHMMSS/ | 一次EEG采集启动时刻命名的子目录，不是结束时刻 |
| continuous_eeg.npy | 通道×样本连续EEG，不应按视频分别拼出伪连续记录 |
| events.json | 事件、相对时间、样本索引和marker信息；重复样本索引可能提示断流 |
| metadata.json / eeg_segments.json | 设备、采样率、分段、退出原因及文件对应 |
| crash_report.txt | Python调用栈，区分文件保存、播放与采集异常 |

备份应复制整个被试目录，包括各Session状态、CSV、快照和所有采集时间戳目录。采集中不要用Excel占用写入文件。分析时检查completed和中止字段；有行为完成记录不表示一定有对应有效EEG。

以下为保护机制与小补丁操作。


---

## 合并记录 1：EEG_DISCONNECT_GUARD.zh-CN

# EEG断流保护、日志与离线补丁（2026-09-15）

## 现在如何保护

适用于程序本地接收并记录EEG的17组、34组及Emotion V1/V2入口。后台每0.1秒检查已写入的样本数，默认连续5秒不增长就锁定故障；启动后一直没有样本的等待上限为10秒。视频、内容题、主观评分和休息页均会检查采集错误，停止当前运行并显示警告，尝试保存已采数据。不会自动重连、填充缺口或将缺口伪装成连续EEG。

故障页显示“连续多少秒未收到新的EEG样本”或SDK返回的异常文本，并请被试联系主试。只能说明程序观察到的数据链路异常，不能直接判断放大器为何有电关机。关闭SDK失败也记录下来，仍尝试导出已写盘样本；迟到的后台读取不再写入已经冻结的记录。

当前未完成的视频保留用于重播。阈值前数秒仍可能有已提交的行为，必须结合健康日志检查；程序不事后静默改写已完成视频。原来已经缺失的EEG无法通过补丁恢复。

## 日志在哪里

每个Session内本次时间戳采集目录新增：

- `eeg_health_part_001.jsonl`：约每秒一行，包含电脑Unix时间、单调时钟、采集相对时间、累计样本数、该日志区间新增样本数/秒、距最近观察到新样本的秒数与阈值。它测量样本到达，不是逐通道信号质量日志。
- `eeg_error_part_001.json`：故障发生时立即写入，含`code`、`detail`、检测时间、样本数和`hardware_cause=unknown`。断流为`no_samples_timeout`，读取抛异常为`acquisition_exception`，健康日志自身异常为`health_monitor_error`。
- `events.json`：本地`eeg_acquisition_error`事件；不发送虚构的硬件marker。故障后的终止边界注明`eeg_available=false`，不可当有效EEG对齐点。
- `metadata.json`：`termination_reason=eeg_background_error`，以及`eeg_health_monitor`设置、故障和关闭错误。`crash_report.txt`保留调用栈。

同目录再次追加分段时后缀按part编号递增。每秒日志会刷新，异常JSON不依赖实验最终导出；突然断电仍不能保证操作系统尚未落盘内容全部保留。

仅使用外部BCIGo录制、程序自己不接收EEG样本时不启用此监测，metadata明确`enabled=false`；此模式应由主试/外部采集软件监视。阻抗偏高、噪声变大或SDK重复返回伪新样本不一定造成样本数停止，本补丁不以未经验证的幅值阈值自动判断质量，也没有电池遥测。

设备配置可选：`device.eeg_no_sample_timeout_sec: 5.0`和`device.eeg_startup_timeout_sec: 10.0`，未配置即使用上述默认值。两者必须为正的有限数。阈值是工程保护设置，不是生理学判断标准；短于阈值的间断仍需审计。

## 用硬盘给已开采的电脑打补丁

硬盘目录：`E:\video\EEG断流保护补丁_20260915`。这是源码安全补丁，不要求切换17/34/45组或1–9/1–7评分协议。

1. 正常结束实验并保存数据。备份旧数据；不要在采集中更新。
2. 双击`安装断流保护.bat`，选择**实际使用的程序目录**：旧17组直接启动就选主项目；通过`_video_eeg_34_update`或`_video_eeg_emotion_v2_update`启动就选对应更新包目录。该目录应直接包含`video_eeg/experiment/video_runner.py`。
3. 安装器先校验硬盘源码、备份目标源码到`runtime_patch_backups/eeg_guard_时间戳`，再复制Python源码；不复制视频，不改YAML、manifest、题库、环境、data或session_state。已有离线文件校验清单会同步更新源码哈希。
4. 安装完成后**仍用原入口、原被试编号和原Session续跑原协议**。先做Demo，然后由主试在无被试测试运行中短暂断开采集链路，确认约5秒后出现警告、健康/故障日志和EEG导出。恢复设备后重新启动，核对样本增长。
5. 如果需要回退，退出实验后按备份中的`PATCH_RECEIPT.json`恢复被替换的原源码和原`OFFLINE_FILES.json`。不要用回退操作覆盖data或被试状态；新增且原先不存在的模块可留存，勿删除整个video_eeg目录。

此前制作的情绪V2整包可以先正常部署，再给目标更新包安装此补丁；不需要重拷9.87GB情绪视频。若给硬盘上的尚未部署包安装本补丁，也需保留其完整OFFLINE_FILES.json；已部署目标版本的校验可能与硬盘版本不同，优先直接修补目标，不重新运行旧部署器覆盖它。

## 如何区别设备断流与WinError 5

`sample_index`在多个相隔很久的事件上不变，而`relative_time_sec`持续增长，是没有新样本的重要证据；NPY文件长度可独立核实。旧版只记Esc退出，不能据此推断EEG一直正常。

`crash_report.txt`中`Path.replace → PermissionError [WinError 5]`是文件操作被拒绝，应按栈定位具体文件；它本身不是阻抗或关机证据。是否文件占用、同步程序或权限问题还需现场证据。

要查有电关机的根因，另外保留同一时刻设备指示灯/重启表现、BCIGo与SDK日志、连接方式、设备编号和电量记录；软件断连和硬件真正关机分开登记。

## 验证范围

已验证模拟空读取、明确读取异常、启动无样本、关闭SDK异常仍导出、冻结后迟到读取被拒绝、外部录制不误报。真实PsychoPy窗口对视频、疲劳、情绪评分和休息页注入断流，提示、文件写盘及视频中断后续跑通过。真实BrainCo关机/断连、实验室各台电脑及物理时延仍需现场验收。事故原始数据与详细个案报告仅存本地，不上传GitHub。
