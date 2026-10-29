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
