# 独立 NPY → EDF+ / BIDS 转换工具

使用 独立目录 `D:\Experiment\BIDS-convert\convert.py` 将已保存的项目 NPY 记录转为独立 EDF+C/BIDS 包；不启动实验、不连接设备、不改原始记录。每个采集段一个 `recording-UUID` 数据集，沿用项目 EEGQC 模板的8位平台被试编号、采集UUID、`session.json`、事件及通道表。实验 Session 编号保留在 `source_session_number`，不是把材料 Session 改为UUID。

## 运行

先结束采集并备份完整 Session。使用已具备 numpy、edfio、bids-validator-deno、deno 的独立 Python；无需安装本项目或重建实验环境。独立环境准备见 [工具说明](../../../BIDS-convert/README.md)，离线校验器由项目 BIDS 依赖提供，不联网、不上传数据。

```powershell
..\BIDS-convert\RUNME.bat --source "D:\records\v3_neuracle\00000001\session_01" --output "D:\exports\neuracle_00000001_new" --protocol v3
```

`--source` 接受采集时间戳目录、Session或被试目录，必须包含原始 metadata/events；只有 NPY 无法确认采样率、通道、设备、时间和身份。一次选择同一设备、范围和协议，输出必须是源目录树之外的新目录。v3仅作为转换协议参数，不加入实验公共v1/v2选择页。

历史 BrainCo 首行计数＋31导 NPY 还须提供 `--config "D:\private\eegqc.local.json"`，按 `src/video_eeg/config/eegqc_settings.example.json` 填写已确认的设备型号、逐通道物理量程及必要的被试/时间映射，不能套用新32导设备参数。博睿康使用记录内的转发通道和TRG合同，未知单位、参考和滤波保持未知，要求 `eeg_segments.json` 确认分段已结束。未知设备、混合采样率、矛盾元数据或缺失原件均停止。

## 输出与验收

每个 `recording-UUID/` 包含标准 `sub-编号/ses-UUID/eeg/*_eeg.edf`、`*_eeg.json`、`*_channels.tsv`、`*_events.tsv/json`，以及模板要求的 `session.json`、participants、dataset_description、哈希回执和官方校验报告。输出根的 `conversion_report.json` 汇总成功或失败。

EDF+包含注释通道和样本对应事件标记；完整事件、行为字段和未知时序仍以 events.tsv 为准，不以注释重建硬件TRG。逐段保留样本数、采样率、顺序，不拼接、不补零、不滤波；EDF为16位量化，逐通道回读误差写入 EEG JSON，博睿康TRG须完全一致。原NPY及计数行继续保留在源目录。

默认运行官方离线全量TSV校验；缺少校验器或校验失败返回非零退出码。仅当明确需要先转换时使用 `--no-validate`，报告标为 `NOT_RUN`。格式合格不代表信号质量、硬件健康或平台入库成功。v3后续独立评分不写入先前封存的EEG包，原评分日志留在Session。

失败输出保留用于审计，修复原因后换新输出目录重试，不覆盖既有包；原进度、题库快照和视频完成状态均不改。此工具随源码交付，尚未加入Windows安装器，不需要重装或重启采集程序。

EDF+编码使用 [edfio](https://github.com/the-siesta-group/edfio)；BIDS和恢复边界见 [BIDS说明](BIDS_EXPORT.md) 与 [数据恢复](EEG_AND_RECOVERY.md)。

工具实现、配置和BAT入口集中在 `bids-convert`，该目录可以单独复制；旧 `scripts/convert_npy_bids.py` 仅兼容转发，不再依赖采集主程序。

当前工具已迁移到与主仓库同级的 `D:\Experiment\BIDS-convert`，不再包含在主仓库源码发行包中；兼容脚本查找同级目录，其他电脑直接运行独立工具的RUNME.bat。
