# 项目文档索引

本项目按 [acq-task-template](https://github.com/Omni-Intel/acq-task-template/commit/b44af0a905cb604515bc1ff843df794b16f7952f) 使用 source-only 入口、uv 锁文件和文档分工。项目自身不安装；现有 `src/video_eeg` 是唯一范式实现，保留已有实验合同、设备适配器和 EEG 恢复格式。

| 文档 | 用途 |
|---|---|
| [部署](deploy.md) | 新 Windows 源码安装、启动、本机配置与验证 |
| [DVC 素材](assets.md) / [采集后归档](data-transfer.md) | 素材索引与封存单记录包的独立 NAS 操作 |
| [数据格式](data-format.md) / [交付约定](../data/README.md) | 原生记录、恢复、BIDS 副本与 EEGQC 单记录交付 |
| [v1](versions/v1.md) / [v2](versions/v2.md) / [v3](versions/v3.md) | 范式、刺激、问题、事件和按键；v3 保留独立入口 |
| [材料](operations/MATERIALS.md) / [EEG 与恢复](operations/EEG_AND_RECOVERY.md) | 准备素材、断流处理和旧进度续跑 |
| [面部录像](operations/FACIAL_RECORDING.md) | v3摄像头、同目录命名、软件同步及录像时长验证 |
| [NAS材料](operations/NAS_MATERIALS.md) | 两设备共用只读材料路径，本机记录与进度不变 |
| [结构迁移](maintenance/TEMPLATE_LAYOUT.md) / [维护记录](maintenance/CHANGELOG.md) | 目录职责、兼容边界及验证记录 |
