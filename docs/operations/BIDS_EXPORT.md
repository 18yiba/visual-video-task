# BIDS 数据保存与实验室更新（Windows 1.0.4）

当前源码BrainCo新采集保存32导EDF（CH01→CH32，含IO，FCz参考），BIDS与[EEGQC交接](EEGQC_HANDOFF.md)直接复制该EDF，不二次量化。旧NPY仍按原“计数＋31导、IO参考”合同导出，不套用新映射。该修改尚未发布安装包；下文描述已发布1.0.4的BrainVision导出。

## 主试现在怎么操作

1. 结束正在进行的采集，等“原始数据已保存”后正常退出；保留整个被试目录的备份。
2. 将 1.0.4 安装包下载或复制到实验室电脑本机，再双击覆盖安装。已有 1.0.1–1.0.3 无需卸载、重新绑定材料、迁移数据或重拷视频。
3. 仍从原来的“视频EEG总范式”启动，选原协议、原编号、原 Session 续跑。先由主试使用独立测试编号检查真实 EEG、评分、退出保存、续跑。
4. 新的正式记录先按原方式保存 NPY、事件、行为表和进度，再自动生成一份 BIDS。整理副本时请等待结束；空间不足或转换失败会提示稍后重试，原始记录仍保留。
5. 要转换旧数据或做官方格式检查：开始菜单搜索 **视频EEG导出与检查BIDS** → 选择 v1 或 v2 → 选择该协议下的 Session/被试目录 → 确认输出位置 → 等待完成。一次只处理一个协议，勿选 Demo 或整个混合协议根目录。
6. 查看结果窗口；出现“部分导出未完成”时，打开窗口列出的本机操作报告。导出成功后，到 BIDS 目录的 `code/validation_report.json` 查看官方检查；到 `code/exports/` 查看每段原文件哈希、行为表行数和时序质量标记。全部离线可运行，无需 Node.js，也不上传任何数据。

本实验室已有绑定的默认路径：

| 文件 | 路径 | 用途 |
|---|---|---|
| 原始记录与续跑进度 | `C:\Users\EDY\Desktop\video\data\sourcedata` | 继续原地保留；不得删除或用 BIDS 替换 |
| v2 BIDS 副本 | `C:\Users\EDY\Desktop\video\data\bids\v2` | 情绪视频融合协议分析 |
| v1 BIDS 副本 | `C:\Users\EDY\Desktop\video\data\bids\v1` | 原 v1 分析，与 v2 分开 |
| 原视频库 | 原设置绑定的 `_materials` 等目录 | 保持原绑定，本次不搬动材料 |
| 操作报告 | `%LOCALAPPDATA%\VisualVideoTask\logs\bids_export_日期_时间.json` | 手动导出完成/失败说明 |

路径以启动器绑定的数据根目录为准；不是把别的电脑也硬编码成 EDY 用户。BIDS 放在 `sourcedata` 同级 `bids` 下。

## 生成的标准文件

```text
bids/v2/
  dataset_description.json
  README
  participants.tsv
  participants.json
  sub-TEST01/
    ses-01/
      eeg/
        sub-TEST01_ses-01_task-videov2_acq-20260922T120000_run-01_eeg.vhdr
        sub-TEST01_ses-01_task-videov2_acq-20260922T120000_run-01_eeg.vmrk
        sub-TEST01_ses-01_task-videov2_acq-20260922T120000_run-01_eeg.eeg
        sub-TEST01_ses-01_task-videov2_acq-20260922T120000_run-01_eeg.json
        sub-TEST01_ses-01_task-videov2_acq-20260922T120000_run-01_channels.tsv
        sub-TEST01_ses-01_task-videov2_acq-20260922T120000_run-01_events.tsv
        sub-TEST01_ses-01_task-videov2_acq-20260922T120000_run-01_events.json
  code/
    exports/...
    validation_report.json
```

示例中的编号是虚构编号。`.vhdr/.vmrk/.eeg` 是一组 BrainVision 文件，须一起保留；用 MNE 等软件读取 `.vhdr`。任务事件在 `events.tsv` 中，不能只读取 `.vmrk` 后以为没有任务事件。

- `sub-` 对应原匿名被试编号，只接受字母数字，不静默去除字符，以免两个编号合并。非字母数字编号须先制定显式映射，不能改原进度来绕过检查。
- `ses-01` 对应原范式 Session 组，可跨日期完成；不是把每次进实验室另算一个材料组。
- `acq-` 对应时间戳采集目录，`run-` 对应该目录内 `eeg_part`。退出续跑/休息后重新采集分别保存，不跨空档拼接、不补零、不重采样。
- 只接受已确认的17组内容题v1及45组v2；旧算术任务、34组或身份不明记录拒绝混入，需独立适配。
- v1 与 v2 独立数据集；题库、固定分组、1.0.3 的三条排除规则及历史答案不因 BIDS 改变。

## 信号、通道和事件怎样对应

按实验室确认的 BrainCo 配置：原 NPY 为首行计数加 31 个 EEG 通道，单位 µV、参考 IO。导出验证数组、首行计数与配置，再把 31 通道以原 float32 精度写入 BrainVision，单位换算信息写在头文件中。计数行仍保留在原 NPY，不当作 EEG。真实采样率来自每段 metadata，不照搬参考数据集。

通道顺序在 `src/video_eeg/config/bids_profile.json`。换帽子、型号、固件或通道输出顺序时必须先复核配置；不能仅凭“也是32行”判断一致。50 Hz 为现有实验室工频配置。未取得实际电极坐标、设备序列号、硬件滤波参数或独立坏导标记，不生成虚构信息，也不把所有通道写成“good”。

`events.tsv` 的 `onset`、`duration` 使用段内样本索引/实际采样率，秒为单位；不是把系统单调时钟直接当起始时间。保留原事件名称、样本索引、反应、RT、视频ID、attempt编号及 JSON 编码的完整原字段 `source_details`。

原 trial、情绪评分、普通行为、喜好、内容题、疲劳、注意题、休息 CSV 按采集目录/时间和 part 归属选择。每个源表行作为 `behavior_summary` 保留，并注明 `source_table`。它们可能是同一试次的不同视图，**统计试次数不能把这些行全都相加**。评分详细时间、量表上下限、回答和对错保留在原字段中；历史二级/七级疲劳不改写成五级。

源事件越界、终末样本冻结或找不到可靠对应时，EEG 时间写 `n/a`，同时保留原时钟及质量标记；不把所有后续事件压到最后一帧。时间戳对齐仍受原软件标记/无线采集延迟限制，BIDS 转换没有新增硬件同步证据。

视频本身不重复复制，也不产生指向不存在文件的 `stim_file`。视频 ID、来源标签保留，研究人员按现有固定材料清单关联原视频。公开分享时须另外核对匿名编号、真实时间戳、许可和刺激材料授权，安装升级不会自动公开数据。

## 检查结果怎么处理

| 看到的提示 | 含义 | 主试怎么做 |
|---|---|---|
| 原始记录已保存；BIDS导出未完成 | 原记录已先保存，副本失败 | 不要重做实验来“修格式”。记下原因，用开始菜单 BIDS 入口重试 |
| 磁盘空间不足 | BIDS EEG 需额外约原 32行float32 NPY 的 31/32 大小，另加表格 | 清理与实验无关文件或选择另一块足够大的本机盘；保留 sourcedata |
| 官方校验 0 错误、有警告 | 通过结构检查，部分推荐说明缺失 | 看报告中的 code/subCode；作者、许可、型号/电极位置须据实补充，不能照抄别的数据集 |
| SAMPLE_FREEZE / UNAVAILABLE_EVENT_TIMING | 源事件继续而 EEG 样本不再增加，或无可靠样本时间 | 保留原记录，交分析人员确定受影响试次；转换不会修复原断流 |
| TIMING_GAP / possible_acquisition_gap | 墙钟间隔与样本时间有明显差异 | 对照原 events、eeg_health、trial_log 核查；这是筛查标记，不是已证实的病因 |
| 已有 BIDS 副本与当前源数据不同 / 文件缺失修改 | 旧导出与现在的源文件或副本哈希不一致 | 保留旧导出，另选一个空的本机输出目录重导；不要覆盖旧数据 |
| 多段行为行缺少 eeg_part | 旧数据不足以可靠分配到采集段 | 保留原表和导出报告，请研究人员核对归属；不能复制到每个run冒充确定对应 |
| 发现恢复 CSV | `.recovered_...csv` 可能比被锁住的原 CSV 更新 | 先核对哪份包含完整行，保留两份，解决原写盘问题后再做明确合并；不自动猜选 |
| 编号需要显式匿名映射 | 原编号包含下划线/汉字等 | 由研究人员建立一对一映射后适配导出；不要重命名原采集目录和进度 |
| 已有导出锁 / 同名未完成导出 | 上次导出可能仍运行或中途停止 | 先确认进程已退出，保存日志；使用新的空输出目录重试，不删除原记录 |

自动导出只生成副本，官方全量格式检查从开始菜单运行。已验证的同一记录再次导出会校验后跳过，不重复拼接。Demo 和外部录制模式不会伪装成本地真实 EEG。

## 参考和验证边界

参考 [BIDS EEG 文件结构](https://bids.neuroimaging.io/getting_started/folders_and_files/files.html#eeg)、[BIDS 1.11.1 EEG规范](https://bids-specification.readthedocs.io/en/v1.11.1/modality-specific-files/electroencephalography.html) 和 [OpenNeuro ds003505 1.1.2](https://openneuro.org/datasets/ds003505/versions/1.1.2)。该参考数据集使用 BioSemi/128通道/2048Hz，只参考组织方式，不复制设备元数据、被试或数据许可。

本版使用 BIDS Validator 3.0.1 + Deno 2.9.6，在禁止网络访问的参数下检查全部 TSV 行；安装包已包含所需运行时。源数据不上传。官方校验的零错误只说明格式检查通过，不等于实验设计、信号质量、有效试次数或真实硬件验收通过。

源码使用：在干净隔离环境准备锁定的 BIDS 与运行依赖组（PowerShell先设置 `$env:UV_PROJECT_ENVIRONMENT = Join-Path $PWD '.tmp/bids-runtime-env'`，再执行 `uv sync --locked --group bids --group runtime`），然后由该环境 Python 执行以下命令；不安装本项目，不生成控制台别名。不要在既有实验环境执行 `uv sync`。

```powershell
uv run --no-sync python scripts/export_bids.py --source "C:\Users\EDY\Desktop\video\data\sourcedata\v2\被试编号" --output "C:\Users\EDY\Desktop\video\data\bids\v2" --protocol v2 --validate
```

旧 `vendor/eeg-bids-converter` 作为历史通用组件保留。本次桌面功能使用针对本范式事件和行为表实现的 `src/video_eeg/utils/bids_export.py`，不再让主试手动套用旧通用转换配置。
