# 项目文档索引

本项目采用 [acq-task-template](https://github.com/Omni-Intel/acq-task-template) 的源码入口、`src/`、TOML 启动配置和文档分工，保留已有实验合同与恢复格式。模板是模拟采集起点，本项目继续使用自己的 PsychoPy、设备适配器和 EEG 保存实现。

| 文档 | 用途 |
|---|---|
| [部署](deploy.md) | 新 Windows 源码安装、启动、本机配置与验证 |
| [数据格式](data-format.md) / [交付约定](../data/README.md) | 原生记录、恢复、BIDS 副本与 EEGQC 单记录交付 |
| [v1](versions/v1.md) / [v2](versions/v2.md) / [v3](versions/v3.md) | 范式、刺激、问题、事件和按键；v3 保留独立入口 |
| [材料](operations/MATERIALS.md) / [EEG 与恢复](operations/EEG_AND_RECOVERY.md) | 准备素材、断流处理和旧进度续跑 |
| [面部录像](operations/FACIAL_RECORDING.md) | v3摄像头、同目录命名、软件同步及录像时长验证 |
| [结构迁移](maintenance/TEMPLATE_LAYOUT.md) / [维护记录](maintenance/CHANGELOG.md) | 目录职责、兼容边界及验证记录 |
