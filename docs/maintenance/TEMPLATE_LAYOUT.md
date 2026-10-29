# 模板结构与兼容边界

依据 [`Omni-Intel/acq-task-template` 提交 `b44af0a905cb604515bc1ff843df794b16f7952f`](https://github.com/Omni-Intel/acq-task-template/commit/b44af0a905cb604515bc1ff843df794b16f7952f)（2026-10-23），调整源码运行和交付组织，保留本项目已确认的实验与设备合同。

| 路径 | 当前职责 |
|---|---|
| `main.py` / `python -m src` / `config/` | 同一 CLI 的实验入口；`--paradigm`选择范式，TOML提供严格校验的启动默认值与私有覆盖 |
| `RUNME.bat` / `run_experiment.bat` / `run_emotion_v3.bat` / `run_neuracle_v3.bat` / `run_brainco_v3.bat` / `rating_emotion_v3.bat` | `RUNME.bat` 是模板要求的兼容别名，只转发到 `run_experiment.bat`；其余入口提供v1/v2选择页、各设备v3控制台及独立评分启动入口 |
| `src/video_eeg/` | 实验执行器、共享设备/Trigger 组装、EEG记录服务契约、适配器和 CLI 的唯一实现 |
| `src/video_eeg/config/` / `video_eeg.py` | 协议资源和唯一配置副本归入源码包；根目录单文件 shim 兼容旧脚本导入，不保留根 `video_eeg/` 目录 |
| `assets/` / `stimuli/` / `data/` | 品牌资源、已有刺激路径、私有原始记录；视频与数据不移动、不进入源码包 |
| `docs/` / `tests/` / `scripts/` | 文档索引与数据说明、自动验证、安装及显式白名单发行 |

Windows安装器构建源码单独维护在仓库外的`visual-video-package/`目录；范式仓库只保留调用构建流程的维护脚本，不包含Inno Setup定义、桌面启动器或安装器图标。默认构建产物放在外置目录的`artifacts/`子目录，避免打包文件混入源码发行。

模板改为 source-only：`uv sync` 只安装第三方依赖，不安装本项目或生成 CLI 别名。入口统一转发到既有 `src/video_eeg.cli`。根目录 `video_eeg.py` 只承担旧导入兼容，全部实现和配置资源位于 `src/video_eeg/`，不创建第二套执行器。`config/config.toml` 必须包含模板要求的 `[experiment]`、`[device]`、`[storage]` 和现有 `[launcher]`；前三个段仅记录项目身份及部署默认值，启动路由仍只读取 `[launcher]`。固定 Session、恢复状态、协议 YAML 和原始数据格式不变。

`pyproject.toml` 设置 `[tool.uv] package = false`。`main.py`、`python -m src` 和既有 BAT 直接运行源码；模板要求的 `RUNME.bat` 仅作为 `run_experiment.bat` 的转发别名，不增加运行逻辑。项目 distribution、editable `.pth` 和控制台命令不作为运行依赖。Windows EXE 自带第三方环境与源码，不从 site-packages 复制本项目。现有 `.venv` 和 `runtime/python312` 在锁定运行环境完成验收前继续保留。

安装器检查旧项目 distribution、入口别名及专属 `.pth/.egg-link`；若存在则保留旧 `.venv` 备份后重建。Windows 打包器在复制第三方 site-packages 前执行同类检查，发现旧别名即停止，避免将开发机安装路径带入可搬迁包。源码发行包由显式白名单构建，并按 `repository_layout.json` 校验必需入口和文件；DVC 本机凭据不进入发行包。

runner 通过 `video_runner.main(..., default_config_filename=..., demo_config_filename=..., config_transform=...)` 显式选择配置，不再临时替换执行器全局变量。`experiment/acquisition.py` 统一构造采集设备和 Trigger；`video_protocol.EegSessionManager` 依赖 `recording_contracts.py` 定义的记录器、健康监测接口，按设备注入原有 SessionRecorder 或 Neuracle 专用记录器。SessionRecorder 的 export 是封存边界，事件、EEG文件和 metadata 仍保持原格式。后续协议迁移应继续经这些接口，逐步把设备检查、封存验证与协议 UI 分开。

项目身份由 `metadata.toml` 提供，当前 `EMOVID-20261008`，只用于素材与归档目录，不重写内部协议 ID、EEGQC 范式代码或历史记录。DVC 素材是单独副本；正式材料采集前下载到本机是模板要求，旧 NAS 直读保留为兼容路径。NAS 归档只处理已封存单记录包，原始数据仍是恢复依据。

旧 v1/v2、v3、设备专用入口继续保留，统一公开选择仍恰为 v1/v2。历史文件和未知本机文件保留；retired 白名单同时适用于迁移后的 src 路径。离线更新包携带 src 和兼容层；针对旧平铺安装的安全补丁仍按原路径交付源码。
