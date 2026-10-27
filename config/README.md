# 启动配置

`config.toml` 是统一入口 `main.py` 的默认配置。无参数时打开 v1/v2 选择页，默认选 v2 和 Demo；`--run` 按配置启动。正式采集需显式选择正式模式。

本机覆盖：复制为 `experiment.local.toml`，使用 `python main.py --config config/experiment.local.toml --validate` 检查，再用同一命令去掉 `--validate` 打开选择页，或加 `--run` 直接启动。相对配置路径从项目根解析，不依赖调用命令的工作目录。未知表、字段、协议、模式和 schema 版本均报错。

TOML 只控制启动选项；实验 YAML、固定 Session 清单、题库、材料索引位于 `src/video_eeg/config/`。文件内容及协议哈希保持不变。既有 YAML、状态快照中的 `video_eeg/config/...` 路径由路径解析器映射到新位置；不要复制、重写或重新生成这些文件来匹配模板的演示配置。原有 YAML 设备设置与路径覆盖方式继续有效。
