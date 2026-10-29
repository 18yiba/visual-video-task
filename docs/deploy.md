# 源码部署与验证

Windows 10/11 64 位按 [主操作手册](../README.md) 安装；实验运行固定 Python 3.12。项目是 source-only，uv 仅准备 `.venv` 和第三方依赖，不安装项目包、editable 路径或控制台别名。双击 `install_lab_env_uv.bat` 准备实验环境；已通过健康检查的现有实验环境继续复用。旧 editable 环境迁移前先正常结束实验并备份本机配置、凭据及数据，不运行 `git clean`。

## 启动

根目录运行以下命令；`--validate` 只需标准库，不加载 PsychoPy、不连接设备、不生成采集记录。

```powershell
$env:UV_PROJECT_ENVIRONMENT = Join-Path $PWD '.tmp/template-runtime-env'
uv sync --locked --group runtime --group bids
uv pip check --python (Join-Path $env:UV_PROJECT_ENVIRONMENT 'Scripts/python.exe')
uv run --no-sync python main.py --validate
uv run --no-sync python -m src --validate
uv run --no-sync python -m src.project_metadata
uv run --no-sync python scripts/check_source_environment.py
Remove-Item Env:UV_PROJECT_ENVIRONMENT
```

上述锁定安装命令用于干净隔离环境。现有实验机仍由安装器通过当前受验的实验室依赖清单维护；直到锁定运行组同时通过依赖检查、PsychoPy 窗口及设备适配回归，才切换安装器。不要在正在采集的环境同步依赖。

```powershell
.\.venv\Scripts\python.exe main.py --validate
.\.venv\Scripts\python.exe main.py
.\.venv\Scripts\python.exe main.py --paradigm v2 --mode demo --no-dialog --windowed --subject-id DEMO_TEST
```

双击 `run_experiment.bat` 打开 v1/v2 选择页；`run_emotion_v3.bat` 与 `run_neuracle_v3.bat` 转发到统一CLI并保留原v3控制台。统一选择页仅含公开协议v1/v2，保留 Demo/正式。

命令行统一从根目录 `main.py` 或 `python -m src` 进入；二者委托同一 CLI。用 `--paradigm v1|v2|v3` 选择范式，例如：`python main.py --paradigm v3 --phase acquisition --device emotivpro`、`python -m src --paradigm v3 --phase behavior-rating --device neuracle`。v1/v2还需 `--mode demo|formal`；v3不指定阶段时打开控制台。`--protocol` 暂作兼容别名，旧BAT参数继续有效。

v3 控制台提供独立的“开始行为评分”按钮；也可双击 `rating_emotion_v3.bat` 打开图形评分窗口，在同一页选择原采集设备、视频范围、被试和Session并查看待评分进度。两种入口均不检测或连接 EEG。

## 本机启动配置

复制 `config/config.toml` 为 `config/experiment.local.toml`，仅修改 `launcher.protocol` 和 `launcher.mode`。`[experiment]`、`[device]`、`[storage]` 是模板要求的部署元数据，不能替代启动路由设置。使用 `python main.py --config config/experiment.local.toml --validate` 校验。去掉 `--validate` 打开选择页，加 `--run` 按该配置直接启动。相对配置路径从项目根解析；本机文件不进入 Git 或源码发行包。

已有实验参数仍由原 YAML 管理；不要将固定清单、题库或历史快照改写成模板示例。默认启动模式为 Demo；正式采集需选择正式模式、准备真实材料并完成设备验收。

## 维护验证与发行

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe scripts/maintenance/build_release.py dist/source-check
uv lock --check
```

输出目录必须是新的空目录。源码包包含源码、启动 TOML、原协议资源和脚本，排除记录、视频、环境、缓存与本机配置；素材索引独立发布。CI 检查锁文件、第三方依赖、两个源码入口、项目元数据和干净发行包；不构建本项目 wheel。实际实验仅在 Windows 环境验收。

改动启动路径后运行 `scripts/validation/smoke_unified_entry.py --protocol v1` 和 `--protocol v2`，完成真实 PsychoPy 窗口的模拟 EEG 写盘检查。模拟通过不能证明真实设备、音频时延或硬件触发合格。
