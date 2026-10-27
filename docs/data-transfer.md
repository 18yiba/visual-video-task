# 采集后 NAS 归档

归档是采集完成后的人工操作，不进入实验执行器。目标为认证访问的 oi-data/EMOVID-20261008/<UUID>/，不能使用匿名素材桶。一级目录必须由 `python -m src.project_metadata --unique-name` 读取；失败停止，不回退到仓库名。UUID 从该交接包唯一的 session.json.session_id 读取，重试保持不变。

只选择已正常关闭并封存的单记录交接包，不能选择整个 data/ 或仍在续跑的 Session。保留包内相对路径；面部录像、行为与恢复状态仍须另行备份整个被试目录，BIDS 包不能替代原始备份。

管理员在本机配置具备目标前缀权限的 rclone remote。先用 `rclone copy <source> <destination> --immutable --checksum --dry-run` 核对源目录和目标；确认后去掉 --dry-run 执行复制，再用 `rclone check <source> <destination> --download` 逐文件读回校验。两步退出码都为零才在包外保存回执，记录项目标识、UUID、源和目标、UTC时间及校验方法。

遇到冲突停止，不取消 --immutable 强行覆盖，不改变 UUID 隐藏失败；断网后用原目录重试。回执和日志视为私有数据，不提交 Git。归档成功不代表 BIDS 合格、信号质量通过或 EEGQC 入库；这些结果分别保存。本地原件不自动删除，恢复时复制到新的空目录。
