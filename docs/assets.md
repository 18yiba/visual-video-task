# DVC 素材部署

项目标识由 metadata.toml 读取，当前为 EMOVID-20261008；远端为 oi-task-assets/EMOVID-20261008/dvc/。素材桶匿名可读，不能存储被试信息或采集数据。

在独立部署副本中执行 `uv sync --locked --group assets`。后续 DVC 命令均通过 `uv run --group assets` 执行；首次配置可运行 `uv run --group assets python scripts/configure_assets.py`。实验环境未通过锁定依赖验收前，不在现有实验目录直接执行 uv sync，以免精确同步移除实验依赖。

维护者先将获授权素材复制到 assets/stimuli，保留原目录层级和字节。使用本机 AWS profile，通过 `uv run --group assets python scripts/configure_assets.py --profile <profile>` 启用本机上传模式；共享配置仍保持匿名读取。执行 `uv run --group assets dvc add assets/stimuli` 和 `uv run --group assets dvc push assets/stimuli.dvc`，成功后才发布索引。完成后执行 `uv run --group assets dvc remote modify --local nas allow_anonymous_login true`。

实验机取得真实索引后执行 `uv run --group assets dvc pull assets/stimuli.dvc` 和 `uv run --group assets dvc status assets/stimuli.dvc`，通过现有材料设置选择下载后的本机根目录。原 SHA256 核验继续有效；正式试次不得自动下载或修改素材。

现有 SMB/NAS 直读代码保留，但使用它的部署不满足模板的本地播放要求。不要对共享远端执行垃圾回收；旧前缀、历史材料和本机缓存不自动删除。首次远端上传与干净缓存下载验收尚未执行。
