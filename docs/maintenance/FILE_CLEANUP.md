# 文件清理逐项说明

只从当前GitHub源码发行中移除；Git历史可追溯，开发电脑的旧入口/原文保留以免破坏桌面快捷方式。被试data、环境、视频和已发离线包不在删除范围。不是因为文件小就认定无意义。

| 原文件 | 内容/是否重复 | 处理与信息去向 |
|---|---|---|
| `docs/DEPLOYMENT_FIX_20260910.md` | 安装、退出与视频分发修复记录（2026-09-10） | 合并，保留有效协议/操作信息：`docs/maintenance/CHANGELOG.md` |
| `docs/EEG_DISCONNECT_GUARD.zh-CN.md` | EEG断流保护、日志与离线补丁（2026-09-15） | 合并，保留有效协议/操作信息：`docs/operations/EEG_AND_RECOVERY.md` |
| `docs/EEG_GUARD_MAINTENANCE_20260915.md` | 2026-09-15 EEG断流保护维护记录 | 合并，保留有效协议/操作信息：`docs/maintenance/CHANGELOG.md` |
| `docs/EMOTION_EEG_INTEGRATION_20260912.md` | Emotion EEG v1 集成记录 — 2026-09-12 | 合并，保留有效协议/操作信息：`docs/versions/emotion-v1.md` |
| `docs/EMOTION_EEG_PROTOCOL.zh-CN.md` | Emotion EEG v1：主试操作与协议说明 | 合并，保留有效协议/操作信息：`docs/versions/emotion-v1.md` |
| `docs/EMOTION_EEG_V2_PROTOCOL.zh-CN.md` | 视频 EEG 与情绪评分 V2 实验说明 | 合并，保留有效协议/操作信息：`docs/versions/emotion-v2.md` |
| `docs/EMOTION_RATING_RATIONALE.md` | 情绪评分的维度和量表依据 | 合并，保留有效协议/操作信息：`docs/versions/emotion-v1.md` |
| `docs/EMOTION_V2_MAINTENANCE_20260915.md` | 2026年9月15日 V2升级维护记录 | 合并，保留有效协议/操作信息：`docs/versions/emotion-v2.md` |
| `docs/EXPERIMENT_DESCRIPTION.zh-CN.md` | V1简述及旧17/34组内容抽查说明，和对应协议/操作手册重复 | 按版本归入 `docs/versions/emotion-v1.md`、`docs/versions/legacy17.md`、`docs/versions/legacy34.md`；当前采集与数据说明见README |
| `docs/FATIGUE_BINARY_RATIONALE.zh-CN.md` | 当前精神疲劳二分类的措辞与依据 | 合并，保留有效协议/操作信息：`docs/versions/emotion-v2.md` |
| `docs/MAINTENANCE_LOG_20260908.md` | 2026-09-08 维护记录 | 合并，保留有效协议/操作信息：`docs/maintenance/CHANGELOG.md` |
| `docs/MATERIALS_DOWNLOAD.zh-CN.md` | 正式视频库下载与核验 | 合并，保留有效协议/操作信息：`docs/operations/MATERIALS.md` |
| `docs/MATERIALS_RELEASE_v1_RECEIPT.json` | 机器验证回执或旧版Word副本 | 合并，保留有效协议/操作信息：`docs/evidence/MATERIALS_RELEASE_v1_RECEIPT.json` |
| `docs/MATERIALS_UPLOAD_STATUS.md` | 视频附件发布状态 | 主要是当时上传/同步状态，与Git记录和材料回执重复；摘要保留，不再单独成文：`docs/operations/MATERIALS.md` |
| `docs/OFFLINE_EMOTION_UPDATE.zh-CN.md` | 从旧 17 组更新到 Emotion EEG v1：离线最小操作说明 | 合并，保留有效协议/操作信息：`docs/operations/OFFLINE_UPDATE.md` |
| `docs/OFFLINE_EMOTION_V2_UPDATE.zh-CN.md` | 利用硬盘最快更新到情绪协议 V2 | 合并，保留有效协议/操作信息：`docs/operations/OFFLINE_UPDATE.md` |
| `docs/OFFLINE_LAB_UPDATE.zh-CN.md` | 实验室离线最小更新操作说明 | 合并，保留有效协议/操作信息：`docs/operations/OFFLINE_UPDATE.md` |
| `docs/OFFLINE_UPDATE_VALIDATION.md` | 离线更新包验证记录（2026-09-10） | 合并，保留有效协议/操作信息：`docs/maintenance/CHANGELOG.md` |
| `docs/OPERATOR_MANUAL.zh-CN.md` | 视频 EEG 主试操作手册 | 合并，保留有效协议/操作信息：`README.md` |
| `docs/PUBLICATION_20260910.md` | GitHub 发布记录（2026-09-10） | 主要是当时上传/同步状态，与Git记录和材料回执重复；摘要保留，不再单独成文：`docs/maintenance/CHANGELOG.md` |
| `docs/REPOSITORY_CLEANUP_20260914.md` | 2026年9月14日仓库清理与汇报说明 | 合并，保留有效协议/操作信息：`docs/maintenance/CHANGELOG.md` |
| `docs/SESSION_34_AND_LABEL_AUDIT.zh-CN.md` | 34 组与视频问题标签审计（2026-09-10） | 合并，保留有效协议/操作信息：`docs/versions/legacy34.md` |
| `docs/SYNC_20260910.md` | 后续修改已同步 GitHub（2026-09-10） | 主要是当时上传/同步状态，与Git记录和材料回执重复；摘要保留，不再单独成文：`docs/maintenance/CHANGELOG.md` |
| `docs/WINERROR5_AND_EEG_MONITORING_AUDIT.zh-CN.md` | WinError 5 与 EEG 断联、质量监测审计 | 合并，保留有效协议/操作信息：`docs/maintenance/CHANGELOG.md` |
| `docs/clean_install_validation.json` | 机器验证回执或旧版Word副本 | 旧机器单次验证产物，不参与运行；摘要留维护记录，原件留本地及Git历史：`docs/maintenance/CHANGELOG.md` |
| `docs/integration_audit.md` | Emotion EEG integration audit — 2026-09-12 | 与V1协议/集成记录或保留Word重复；关键范围已并入V1：`docs/maintenance/CHANGELOG.md` |
| `docs/material_audit_latest.json` | 机器验证回执或旧版Word副本 | 旧机器单次验证产物，不参与运行；摘要留维护记录，原件留本地及Git历史：`docs/maintenance/CHANGELOG.md` |
| `docs/reports/视频EEG_34组_被试与主试说明.md` | 34组视频 EEG 实验说明 | 合并，保留有效协议/操作信息：`docs/versions/legacy34.md` |
| `docs/reports/视频EEG_45组融合情绪评分_被试与主试说明.md` | 45组融合情绪评分视频 EEG 实验说明 | 与V1协议/集成记录或保留Word重复；关键范围已并入V1：`docs/versions/emotion-v1.md` |
| `docs/视频EEG_离线最小更新操作说明.docx` | 机器验证回执或旧版Word副本 | 旧离线操作Word与Markdown重复且入口已过时；现行操作并入离线说明：`docs/maintenance/CHANGELOG.md` |

## 启动与维护脚本

原启动/材料检查BAT 17 个（16个实验入口/转发，另1个材料检查入口）不再随源码重复发布，合为根目录run_experiment.bat。安装和下载BAT不是实验入口，保留其单一用途。旧17、34、V1、2779配置不删；隐藏的历史选项用于已有被试。

| 原脚本 | 新位置 |
|---|---|
| `scripts/audit_question_bank.py` | `scripts/maintenance/audit_question_bank.py` |
| `scripts/audit_session_pool.py` | `scripts/maintenance/audit_session_pool.py` |
| `scripts/brainco_device_doctor.py` | `scripts/maintenance/brainco_device_doctor.py` |
| `scripts/build_34_session_manifest.py` | `scripts/maintenance/build_34_session_manifest.py` |
| `scripts/build_eeg_guard_patch.py` | `scripts/maintenance/build_eeg_guard_patch.py` |
| `scripts/build_emotion_sessions.py` | `scripts/maintenance/build_emotion_sessions.py` |
| `scripts/build_offline_emotion_update.py` | `scripts/maintenance/build_offline_emotion_update.py` |
| `scripts/build_offline_lab_update.py` | `scripts/maintenance/build_offline_lab_update.py` |
| `scripts/build_release.py` | `scripts/maintenance/build_release.py` |
| `scripts/export_question_bank_csv.py` | `scripts/maintenance/export_question_bank_csv.py` |
| `scripts/export_video_question_labels.py` | `scripts/maintenance/export_video_question_labels.py` |
| `scripts/smoke_demo_entry.py` | `scripts/validation/smoke_demo_entry.py` |
| `scripts/smoke_eeg_disconnect.py` | `scripts/validation/smoke_eeg_disconnect.py` |
| `scripts/smoke_emotion_protocol.py` | `scripts/validation/smoke_emotion_protocol.py` |
| `scripts/smoke_emotion_v2.py` | `scripts/validation/smoke_emotion_v2.py` |
| `scripts/smoke_formal_session.py` | `scripts/validation/smoke_formal_session.py` |
| `scripts/smoke_ready_questions.py` | `scripts/validation/smoke_ready_questions.py` |
| `scripts/smoke_safe_exit.py` | `scripts/validation/smoke_safe_exit.py` |

配置目录未重排：清单、题库、来源索引和YAML是运行依赖，名字相似不等于重复文件。源码中只保留data/sourcedata空占位；原complete目录在已有电脑上仍原位保留。旧本机绝对路径、密码和被试资料不进入整理报告。
