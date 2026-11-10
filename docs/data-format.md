博睿康 v3 可选[全程动作录像](operations/ACTION_RECORDING.md)使用 `Action_CAMERA`，首帧trigger为165；面部录像仍使用 `facialcamera` 和164。动作MP4、逐帧CSV与日志保存当前Session，属于原始记录，随整个Session备份，不进入源码或BIDS副本。更新整套源码后重启原BAT，已发布EXE未更新，真实设备待验收。

EMOTIV Cortex 新记录为实际通道顺序的 continuous_eeg.edf、metadata 和 cortex_packets_part_XXX.jsonl 原包审计；外部EmotivPRO历史EDF登记不变。详见[保存与恢复边界](operations/EMOTIV_CORTEX.md)。

# 数据格式与恢复边界

本次仅调整源码结构，不改变原始记录 schema、协议标识、Session 成员、行为字段或已有疲劳量尺。模板的模拟 `samples.csv` / `events.jsonl` 不替代本项目的保存合同。

| 层 | 文件与位置 | 用途 |
|---|---|---|
| 原始实验 | `data/sourcedata/v1`、`v2`；已有被试沿原根目录 | 原始数据与恢复依据；Demo 独立存储 |
| Session 状态 | `session_state.json`、题库快照、行为 CSV | 固定队列、回答、attempt 和完成状态；保留原协议哈希 |
| 连续采集 | Session 内时间戳目录中的 EDF、events、metadata、health 日志 | BrainCo 与新 Neuracle 记录为 EDF；历史 NPY 原样保留 |
| BIDS / EEGQC 副本 | 按导出设置生成的独立目录 | 保存完成后单独生成，失败可重试，不覆盖原始数据 |
| 质检与上传 | EEGQC 报告和入库回执 | 由 EEGQC 处理，不把结构校验通过当成信号质量通过 |

完整字段、部分试次重播和冲突根目录规则见 [EEG 与恢复](operations/EEG_AND_RECOVERY.md)；导出范围见 [BIDS](operations/BIDS_EXPORT.md) 和 [EEGQC 交接](operations/EEGQC_HANDOFF.md)。v3 的采集/行为阶段独立合同见 [v3](versions/v3.md)。

数据字段若发生不兼容变更，须另行提升相应 schema 并更新此说明；目录重排不能触发旧答案转换、旧 UUID 重建或历史记录迁移。

独立格式转换：[NPY → EDF+ / 模板BIDS工具](operations/NPY_TO_EDFPLUS_BIDS.md)。生成独立副本，保留原始NPY与恢复记录；默认执行离线官方校验。
# 2026-11-07 trigger码表调整

新采集数字码保留101/102、112–115、130–133、140/141、156–164、171–173、175，博睿康连通性检测保留250–252。110/111、134–139、142、152–155已从当前数字码表删除；对应流程事件保存在events日志，marker_code为空且external_marker_sent=false。历史数字码按各采集目录metadata中的trigger_codes解释。情绪视频开始按three_class_label发送positive=171、negative=172、neutral=173，结束统一175；150/151已废除。事件name保留EMOTION_VIDEO_ONSET/OFFSET，payload.marker_event_name记录具体发送名称，marker_code记录实际发送数字；类别缺失或未知时停止。
