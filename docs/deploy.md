# 源码部署与验证

Windows 10/11 64 位按 [主操作手册](../README.md) 安装；Python 要求沿用项目的 3.12，不照搬模板的 3.11。双击 `install_lab_env_uv.bat`，安装器会准备解释器、PsychoPy 和设备依赖。保留当前开发机的运行时和环境；健康环境继续复用。

## 启动

根目录运行以下命令；`--validate` 只需标准库，不加载 PsychoPy、不连接设备、不生成采集记录。

```powershell
.\.venv\Scripts\python.exe main.py --validate
.\.venv\Scripts\python.exe main.py
.\.venv\Scripts\python.exe main.py --protocol v2 --mode demo --no-dialog --windowed --subject-id DEMO_TEST
```

双击 `run_experiment.bat` 打开 v1/v2 选择页；`run_emotion_v3.bat` 和已发布安装版入口继续有效。统一选择页仅含 v1/v2，保留 Demo/正式。

## 本机启动配置

复制 `config/config.toml` 为 `config/experiment.local.toml`，修改 `launcher.protocol` 和 `launcher.mode`。使用 `python main.py --config config/experiment.local.toml --validate` 校验。去掉 `--validate` 打开选择页，加 `--run` 按该配置直接启动。相对配置路径从项目根解析；本机文件不进入 Git 或源码发行包。

已有实验参数仍由原 YAML 管理；不要将固定清单、题库或历史快照改写成模板示例。默认启动模式为 Demo；正式采集需选择正式模式、准备真实材料并完成设备验收。

## 维护验证与发行

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe scripts/maintenance/build_release.py dist/source-check
```

输出目录必须是新的空目录。源码包包含 `src/`、启动 TOML、原协议资源和脚本，排除记录、视频、环境、缓存与本机配置；材料单独发布。跨平台 CI 检查标准库入口、结构、配置错误、安装包发现与干净发行包；实际实验仅在已部署 Windows 环境验收。

改动启动路径后运行 `scripts/validation/smoke_unified_entry.py --protocol v1` 和 `--protocol v2`，完成真实 PsychoPy 窗口的模拟 EEG 写盘检查。模拟通过不能证明真实设备、音频时延或硬件触发合格。
