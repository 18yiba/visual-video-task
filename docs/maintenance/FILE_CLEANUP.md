# 当前源码文件整理说明

当前公开范式只有visual-video-task v1（17个Session）和v2（45个Session）。启动页和命令行均只提供这两个版本，Demo与正式采集保留。

## 本次移除的独立版本

按用户2026-09-16要求，34组、九级评分和旧2779题独立版本的配置、专用Session清单、入口选择、专用构建/验证脚本、专用测试及汇报文档从当前公开源码移除。历史提交仍可追溯。本机已有数据、视频及已交付离线包不在删除范围。

## 保留的共享文件

v1保留原17组固定成员和完整版题库；v2保留原45组固定成员、材料索引和七级评分。v2材料清单中的旧修订标识与共享评分基类属于运行依赖，不作为额外公开版本，不重写已有状态或清单哈希。

新被试写到data/sourcedata/v1或v2；原complete、protocol_emotion_v2及此前sourcedata/legacy17、emotion-v2进度原位读取，冲突时停止并提示。

## 前次合并文件的信息去向

- 安装、设备、完整配置及操作手册：README。
- v1协议：docs/versions/v1.md；v2流程、评分和疲劳依据：docs/versions/v2.md。
- 材料下载与验证：docs/operations/MATERIALS.md；原Release校验回执：docs/evidence。
- 离线更新：docs/operations/OFFLINE_UPDATE.md；EEG日志、故障和恢复：docs/operations/EEG_AND_RECOVERY.md。
- 同步、上传、部署修复等重复过程说明：合并至CHANGELOG，完整原文在Git历史中。
- 开发维护工具：scripts/maintenance；有效窗口验证工具：scripts/validation。

完整排除路径记录在scripts/repository_layout.json；发行包按scripts/maintenance/build_release.py的白名单生成，不直接复制工作目录。
