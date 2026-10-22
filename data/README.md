# 数据保存与交付

`data/` 是私有本地输出目录。Git 与源码包仅包含本说明和空的 `sourcedata/.gitkeep`；真实记录、模拟测试记录、配置快照、质检报告和上传回执均不提交。

项目遵循 [模板的数据存储与交付规范](https://github.com/Omni-Intel/acq-task-template/blob/main/data/README.md) 中“原始信号、身份、事件、单连续记录包”的分工；本项目实际实现与操作以 [EEGQC 交接](../docs/operations/EEGQC_HANDOFF.md) 和 [BIDS 导出](../docs/operations/BIDS_EXPORT.md) 为准。

| 内容 | 规则 |
|---|---|
| 原生记录与恢复 | 保留 EDF/历史 NPY、行为、`session_state.json` 和题库快照整目录；新 v1/v2 被试写 `sourcedata/v1` 或 `sourcedata/v2`，旧被试原位恢复 |
| 独立交接包 | 一包一段连续 EEG、小写 `.edf`、配套 BIDS 文件及公司扩展 `session.json`；每段 UUID 稳定，重试复用 |
| 人员与范式 | 平台 8 位编号按字符串保留前导零，范式代码据实际协议保存；不把采集 UUID 当作平台预约 Session |
| 信号与事件 | 单位、通道、量程和时钟依据来自实际设备；不中断拼接、不补零伪造信号、不虚构硬件延迟 |
| 验证与入库 | 官方离线 Validator 通过后才声明结构已验证；信号质检、上传和入库回执由 EEGQC 负责 |

中断记录保留真实状态，质量未知保持未知。BIDS/交接是原生保存后的副本，不能取代恢复状态；历史格式不因结构迁移批量转换。
