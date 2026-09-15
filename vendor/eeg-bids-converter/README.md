# Portable EEG/EMG BIDS Skill & Converter

这是一个可随仓库携带、复制和共享的 Codex Skill，同时提供可独立运行的命令行转换器。
推荐从实验范式设计阶段开始使用 Skill：由项目负责人、范式设计者、采集工程师和数据管理员
逐步提供已确认的信息，形成版本化的 `study-contract.yaml`；这些信息在适用且被确认时会生成
采集字段模板与转换配置，并进入最终 BIDS 数据集。未知信息保留为 `TODO`，不会被猜测或静默补全。

两种使用方式：

1. **推荐：作为便携 Skill 使用**——从范式设计、设备与事件定义开始，贯穿采集、转换和交付审核。
2. **直接使用 CLI**——已有符合源数据契约的数据时，执行 dry-run、局部转换、全量转换和验证。

> 工具始终只读 source，不移动、改名或删除原始数据。

快速入口：[安装并调用 Skill](#1-推荐作为便携-skill-使用) ·
[完整 Skill 使用说明](https://github.com/Omni-Intel/eeg-bids-converter/blob/main/docs/eeg-bids-converter-skill-usage.md) ·
[直接使用 CLI](#3-直接使用-cli获取和安装) ·
[第一次转换](#5-第一次运行)

## 1. 推荐：作为便携 Skill 使用

### 1.1 拉取仓库并安装 Skill

```powershell
git clone https://github.com/Omni-Intel/eeg-bids-converter.git
cd eeg-bids-converter

$codexSkills = Join-Path $env:USERPROFILE ".codex\skills"
New-Item -ItemType Directory -Force -Path $codexSkills | Out-Null
Copy-Item -Recurse -Force .\skills\eeg-bids-converter $codexSkills
```

Linux/macOS：

```bash
git clone https://github.com/Omni-Intel/eeg-bids-converter.git
cd eeg-bids-converter
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
cp -R ./skills/eeg-bids-converter "${CODEX_HOME:-$HOME/.codex}/skills/"
```

复制后重新开始一个 Codex 任务，即可通过 `$eeg-bids-converter` 调用。`pip install` 只安装
Python 转换器，不会自动安装 Skill；团队更新仓库后应重新复制 Skill 目录。

完整的安装、角色分工、契约字段、设备 profile、EMG/Ego 路由和对话示例见
[`docs/eeg-bids-converter-skill-usage.md`](https://github.com/Omni-Intel/eeg-bids-converter/blob/main/docs/eeg-bids-converter-skill-usage.md)。

### 1.2 第一步：告诉 Skill 你处于哪个阶段

不需要先读懂 BIDS，也不需要先编辑 YAML。直接复制下面这句话：

```text
使用 $eeg-bids-converter 帮我整理实验信息。请先判断我处于范式设计、采集程序开发、
pilot 还是已有数据阶段；每轮最多问 5 个问题，给出可直接填写的格式，并说明为什么需要。
```

如果阶段已经明确，也可以直接说“我正在设计范式”或“我已经有一批数据”。Skill 会从该阶段
开始，不会要求用户一次填写完整大表格。

### 1.3 第二步：回答第一轮 5 个问题

Skill 首轮会使用类似下面的格式。复制后在冒号后填写即可；不确定时填写“**不知道**”，
与本实验无关时填写“**不适用**”。

```text
1. 当前阶段：[范式设计 / 采集程序开发 / pilot / 已有数据]
   回答：

2. 数据集或实验的暂定名称：
   回答：

3. 请用一句话描述被试要完成的任务：
   回答：

4. 一次 trial 中，被试会看到、听到或执行什么：
   回答：

5. 计划记录的数据：[仅 EEG / EEG + 同步 EMG / EEG + 独立 EMG / 不知道]
   回答：
```

Skill 会在每个问题旁说明它影响的内容。例如问题 3 会影响 BIDS task 描述，问题 5 会决定
EMG 是 EEG 中的同步通道还是独立 `emg/` 模态。回答后，Skill 会：

1. 把已确认内容写入 `study-contract.yaml`；
2. 把未知项保留为 `TODO`，不猜测设备或科学信息；
3. 汇总“已确认 / 待确认 / 当前阻塞项”；
4. 根据当前阶段继续询问下一组最多 5 个问题；
5. 指出下一组问题应由范式设计者、采集工程师还是数据管理员确认。

完整的离线填写表见
[`study-intake.template.md`](https://github.com/Omni-Intel/eeg-bids-converter/blob/main/skills/eeg-bids-converter/assets/study-intake.template.md)。可填写后整段交给 Skill，
也可以完全通过对话逐轮完成。

### 1.4 问题会在什么时候出现

- **范式设计阶段**：任务名称和指导语、trial 类型、刺激、反应/评分含义，以及是否计划采集
  EEG、EMG 或 Ego 摄像头。此时只确认会影响程序设计的决定，不要求填写尚未选定的设备参数。
- **采集程序开发阶段**：设备 profile、真实采样率来源、通道类型、单位、参考、滤波、
  `trial_idx`、marker 名称、EEG sample index 和 part 规则。这些要求会在填写相应答案时同步显示。
- **pilot 阶段**：被试/session 命名、source 目录、metadata/trial/event 文件和 dry-run。
- **已有数据阶段**：先读取真实文件和 header，再反向填写契约；无法确认的事实保持 `TODO`，
  不从品牌惯例或信号幅度推测。

角色分工只作为交接提示，不作为第一张填写表：项目负责人确认数据集和发布信息；范式设计者
确认任务与事件语义；采集工程师确认设备和时序；数据管理员确认被试/session、去标识化和交付。

### 1.5 生成、检查并导出研究契约

Skill 会替用户维护 YAML。需要离线协作时，安装下文 CLI 环境后运行：

```powershell
.\.venv\Scripts\python.exe .\skills\eeg-bids-converter\scripts\study_contract.py `
  init `
  --output-dir D:\my-study\planning
```

该命令同时生成：

```text
planning/
├── study-intake.md       # 给人填写或粘贴给 Skill 的问答表
└── study-contract.yaml   # Skill/转换器使用的机器契约
```

填写问答表或完成对话后检查、导出：

```powershell
.\.venv\Scripts\python.exe .\skills\eeg-bids-converter\scripts\study_contract.py `
  check `
  --contract D:\my-study\planning\study-contract.yaml

.\.venv\Scripts\python.exe .\skills\eeg-bids-converter\scripts\study_contract.py `
  export `
  --contract D:\my-study\planning\study-contract.yaml `
  --output-dir D:\my-study\generated
```

导出目录包含转换器 `config.yaml`、采集端 metadata/trial/event 模板和
`contract-to-bids-map.tsv`。采集程序开发者应在 pilot 前落实这些字段。

## 2. 填写时会同步提示的边界

下面的要求不需要预先背诵。Skill 会在询问相应问题时显示，并说明是否会阻止下一阶段。

### 2.1 选择设备和数据模态时

- 设备品牌不是代码分支。每顶 EEG 帽或采集设备都通过 profile 描述 source 别名、厂商、
  文件/header 格式、采样率来源、通道、单位和参考。
- 当前转换器支持配置型 channel × sample NumPy EEG，以及可读取 `neuracle.nsf` 的
  博睿康/Neuracle 兼容 profile。其他格式需要先增加 adapter。
- 与 EEG 同文件、同一时基的 EMG 标为 EEG profile 中的 `emg` 通道；独立文件或独立时基的
  EMG 必须进入 BIDS `emg/`，当前需要取得真实源样本并实现专用 adapter 后才能交付。
- Ego 摄像头当前不进入 BIDS。只在 source 保留
  `subject_id + timestamp_label + session_id`，不复制视频、不生成 sidecar。

### 2.2 定义 trial 和事件时

- 行为行和 EEG event payload 使用相同且稳定的 `trial_idx`。
- 当前事件契约使用 `image_on` / `image_off`，并记录相对于 EEG part 的 sample index；
  如需其他事件词汇，应在正式采集前扩展转换器和测试。
- 刺激文件名应稳定且唯一，采集后不能静默替换同名内容。

### 2.3 进入 pilot 或已有数据阶段时

当前可直接 dry-run 的 source 使用 `S###/<timestamp>_<task>/session_##`，session 中包含已约定的
`metadata.json`、`trial_log.csv`、`events*.json` 和 `continuous_eeg*.npy`。完全不同的目录层级、
EDF/EEGLAB/厂商私有格式、未知 NPY 轴顺序或不同 marker 时间基准，需要先扩展 discovery/adapter。

工具始终只读 source。正式转换前先 dry-run，再转换一个被试/session；最终交付保留官方
BIDS Validator、PyBIDS 检查和 provenance 文件。

## 3. 直接使用 CLI：获取和安装

需要 Python 3.10 或更高版本。

### Windows PowerShell

#### 第 0 步：检测并安装 Python

在运行 `python -m venv .venv` 之前，先执行下面的检测。它会同时确认 `python` 不是
Microsoft Store 占位别名，并且版本不低于 3.10：

```powershell
$pythonOK = $false
try {
  python -c "import sys; print('Python', sys.version.split()[0]); raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
  $pythonOK = ($LASTEXITCODE -eq 0)
} catch {
  $pythonOK = $false
}

if ($pythonOK) {
  Write-Host "[PASS] Python 环境符合要求，可以继续执行第 1 步。" -ForegroundColor Green
} else {
  Write-Host "[INFO] 未检测到 Python 3.10+，开始安装 Python 3.12..." -ForegroundColor Yellow
  winget install --id Python.Python.3.12 --exact --scope user
  Write-Host "[NEXT] 请关闭并重新打开 PowerShell，然后再次运行第 0 步。" -ForegroundColor Yellow
}
```

检测通过时会明确显示绿色的 `[PASS]`。检测失败时会安装 Python 3.12；安装后必须重新打开
PowerShell，让新的 PATH 生效，然后再次运行第 0 步。不要在出现 `[NEXT]` 后立即执行第 1 步。

#### 第 1 步：进入工具目录

尚未 clone 时执行：

```powershell
git clone https://github.com/Omni-Intel/eeg-bids-converter.git
cd eeg-bids-converter
```

已经位于仓库目录时不用再次 clone，只需确认 PowerShell 提示符类似：

```text
PS ...\eeg-bids-converter>
```

#### 第 2 步：创建环境并安装

下面是 **3 条独立命令**。请逐条复制、逐条回车，等待上一条执行完成后再运行下一条；
不要删掉换行后粘贴成一整行。

```powershell
python -m venv .venv
```

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[validation]"
```

```powershell
Copy-Item .\config.example.yaml .\config.yaml
```

如果希望整行复制，必须使用下面这个带分号和错误检查的版本：

```powershell
python -m venv .venv; if ($LASTEXITCODE -ne 0) { throw "创建 .venv 失败" }; .\.venv\Scripts\python.exe -m pip install -e ".[validation]"; if ($LASTEXITCODE -ne 0) { throw "安装依赖失败" }; Copy-Item .\config.example.yaml .\config.yaml
```

验证安装：

```powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\eeg-bids-converter.exe --help
```

### Linux/macOS

```bash
# 先检查 Python 版本；必须为 3.10 或更高版本
python3 -c 'import sys; print("Python", sys.version.split()[0]); raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'

git clone https://github.com/Omni-Intel/eeg-bids-converter.git
cd eeg-bids-converter

python3 -m venv .venv
./.venv/bin/python -m pip install -e '.[validation]'
cp config.example.yaml config.yaml
```

`[validation]` 会安装官方 `bids-validator-deno`。建议在最终数据转换时保留验证功能。

## 4. 准备本机目录

工具、source 和 BIDS 输出可以位于任意位置。建议彼此分开，例如：

```text
workspace/
├── eeg-bids-converter/       # 工具仓库
├── my-eeg-source/            # 原始数据，只读
└── my-eeg-bids/              # 输出目录，由工具创建
```

不要把输出目录放在 source 内部，也不要把真实受试数据提交到工具仓库。

受支持的 source 大致如下：

```text
my-eeg-source/
├── S001/
│   └── 20260713_113514_image_b/
│       └── session_01/
│           ├── metadata.json
│           ├── trial_log.csv
│           ├── events.json
│           └── continuous_eeg.npy
├── S002/
│   └── ...
├── pilot/                    # 可选刺激库
│   ├── image_001.jpg
│   └── video_001.264
├── formal_500_v1/
└── formal_500_v2/
```

当前内置 adapter 支持：

- 配置型 NPY profile：通道名称/类型、单位、参考和可选 sample-counter 行完全由配置声明，可用于不同品牌脑电帽。
- Neuracle/博睿康兼容 NSF profile：通道、类型、单位、采样率和硬件滤波从该被试 source 中的 `neuracle.nsf` 获取。
- 同步 EMG：在同一 EEG 数据流中将相应通道类型配置为 `emg`，输出 `channels.tsv/type=EMG`。
- 多 part：`continuous_eeg_part_*.npy` 和 `events_part_*.json`，优先按 `eeg_segments.json` 排序。
- 仅行为 session：默认可写入 BIDS `beh/`；使用 `--eeg-only` 时跳过。
- 刺激物：支持图片以及 `.264`、`.h264`、`.mp4`、`.mov`、`.avi`、`.mkv`、`.webm` 等视频。
- 刺激索引：`trial_log.csv` 可使用 `stim_file`、`image_file` 或 `video_file` 列；BIDS 输出统一写入 `stim_file`。

独立采集、具有独立文件和时基的 EMG 应按 BIDS `emg/` 模态整理；在获得真实源格式样本并实现专用 adapter 前，转换器会阻止其被误写为 EEG。Ego 摄像头通过
`source.excluded_device_types` 排除，只保留源侧被试、时间戳和 session 标识，不复制到 BIDS。

开始转换前，请检查 `config.yaml` 中的数据集名称、时区、task 映射、刺激库、排除模态及每个设备 profile 是否符合真实采集配置。

## 5. 第一次运行

以下 Windows 示例假设 source 与工具仓库同级。Linux/macOS 将可执行文件替换为 `./.venv/bin/eeg-bids-converter`。

### 第一步：只读预检

```powershell
cd D:\path\to\eeg-bids-converter

.\.venv\Scripts\eeg-bids-converter.exe `
  --source ..\my-eeg-source `
  --config .\config.yaml `
  --dry-run
```

Dry-run 不创建 BIDS 输出。确认最后出现：

```text
[PASS] Source validation passed
```

查看每一条 source → BIDS 映射：

```powershell
.\.venv\Scripts\eeg-bids-converter.exe `
  --source ..\my-eeg-source `
  --config .\config.yaml `
  --dry-run `
  --show-mapping
```

### 第二步：转换一个 session

若源目录为：

```text
my-eeg-source\S004\20260715_105\session_02\
```

可先进行小范围测试：

```powershell
.\.venv\Scripts\eeg-bids-converter.exe `
  --source ..\my-eeg-source `
  --output ..\my-eeg-bids-test `
  --config .\config.yaml `
  --subject S004 `
  --session 20260715_105/session_02
```

`--subject` 和推荐的 `--session` 值均直接来自 source 目录，不需要记忆工具生成的 BIDS label。

### 第三步：全量转换

```powershell
.\.venv\Scripts\eeg-bids-converter.exe `
  --source ..\my-eeg-source `
  --output ..\my-eeg-bids `
  --config .\config.yaml `
  --eeg-only
```

转换可中断后重新运行。`conversion_manifest.tsv` 中已经成功的 recording 会自动跳过。

## 6. 终端输出

默认只显示关键汇总，例如：

```text
[SCAN] 1 recording(s), 1 subject(s), EEG=1, behavior-only=0
[WARNING] MISSING_ACQUISITION_TIME: 1 recording(s)
[PASS] Conversion complete: converted=1, skipped=0
[PASS] BIDS validation: errors=0
[WARNING] BIDS validation warnings=44
[PASS] PyBIDS index: subjects=1, sessions=1, EEG=1, behavior=0
```

- 绿色 `[PASS]`：该阶段成功。
- 黄色/橙色 `[WARNING]`：需要知晓，但默认不阻止转换。
- 红色 `[ERROR]` 或 `[FAILED]`：转换失败，需要处理。

显示逐 recording 的详细日志：

```powershell
.\.venv\Scripts\eeg-bids-converter.exe `
  --source ..\my-eeg-source `
  --output ..\my-eeg-bids `
  --config .\config.yaml `
  --log-level INFO
```

## 7. 筛选规则

常见筛选示例：

```text
--subject S004
--task image
--session session_02
--session 20260715_105
--session 20260715_105/session_02
```

`--session` 推荐使用 source 中可直接看到的值：

- `session_02`：匹配该 session 目录；建议同时指定 subject。
- `20260715_105`：匹配该 timestamp 目录下的 session。
- `20260715_105/session_02`：精确匹配 timestamp 和 session。
- 完整 source record ID 也可使用。

工具生成的 `ses-*` BIDS label 仅为向后兼容保留。筛选没有匹配任何 recording 时会直接失败，不会创建空数据集。

## 8. 常用参数

```text
--dry-run                 只扫描和验证 source
--subject VALUE           按 source subject 筛选，可重复
--session VALUE           按 source session/timestamp 筛选，可重复
--task VALUE              按 BIDS task 筛选，可重复
--show-mapping            显示全部 source → BIDS 映射
--eeg-only                只转换包含 EEG 的 recording
--replace-stimuli         显式替换同名但 SHA256 不同的刺激文件
--prune-stimuli           删除不再被任何选中 recording 引用的图片/视频
--log-level INFO          显示逐 recording 日志
--overwrite               重建已经成功的 recording
--no-strict               单条失败后继续转换其他 recording
--skip-validation         跳过官方 BIDS Validator
--warnings-as-errors      将 warning 视为失败
--no-color                禁用终端颜色
```

刺激物在每次正式转换时都会同步并验证 SHA256，结果写入 `code/stimuli_manifest.tsv`。默认不覆盖同名异内容文件；确认要更新同名文件时使用 `--replace-stimuli`。`--prune-stimuli` 是显式删除操作，不能与 `--subject`、`--task` 或 `--session` 筛选同时使用，避免小范围转换误删其他被试仍在引用的刺激物。

通常不要使用 `--overwrite`。最终交付的数据集不建议使用 `--skip-validation`。

查看全部参数：

```powershell
.\.venv\Scripts\eeg-bids-converter.exe --help
```

## 9. 输出结构

```text
my-eeg-bids/
├── dataset_description.json
├── participants.tsv
├── README
├── stimuli/
│   ├── image/<resolved-library>/...
│   └── video/<resolved-library>/...
├── code/
│   ├── conversion_manifest.tsv
│   ├── stimuli_manifest.tsv
│   ├── validation_report.json
│   └── dataset_index.json
└── sub-<id>/
    └── ses-<session>/
        ├── sub-<id>_ses-<session>_scans.tsv
        ├── eeg/...
        └── beh/...
```

图片和视频只在数据集根目录的 `stimuli/` 中保存一份。每个被试的 `*_events.tsv` 只保存相对于 `stimuli/` 的路径，例如 `image/pilot/image_001.jpg` 或 `video/pilot/video_001.264`。增加或删除未使用素材不需要修改被试目录；若重命名素材或改变某次实验实际呈现的素材，仍需同步更新源 `trial_log.csv` 中的索引，并使用 `--overwrite` 重新转换对应 EEG recording。

BIDS task 体现在文件名中，不建立 `task-image/` 目录，例如：

```text
sub-004_ses-20260715S02_task-image_eeg.vhdr
sub-004_ses-20260715S02_task-image_events.tsv
```

来源反查信息位于 `code/conversion_manifest.tsv`；官方验证详情位于 `code/validation_report.json`。

## 10. 当前映射行为

- `S001` 映射为 `sub-001`。
- `image_b` 默认映射为 `task-image`，可在配置中修改。
- 有完整采集时间时使用 `ses-YYYYMMDDTHHMMSS`。
- 旧 source 缺采集时间时使用确定性的 `ses-YYYYMMDDS##` 并产生 warning。
- events 优先根据 marker 的 EEG sample index 计算 onset；缺少 marker 文件时才回退到 trial log 时间。
- 重复嵌套 recording 自动选择较完整副本，并在 manifest 中保留重复来源。
- 未完成 recording 可转换并标记；截断的未完成 marker JSON 会尽力恢复并产生 warning。
- 刺激文件按引用进行存在性和 SHA256 内容检查；冲突不会静默覆盖。

## 11. 开发测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

测试使用运行时生成的合成数据，不包含真实受试数据。

## 12. 仓库内容

远程仓库只应包含：

```text
eeg_bids_converter/
tests/
skills/eeg-bids-converter/
docs/
.gitattributes
.gitignore
config.example.yaml
LICENSE
pyproject.toml
README.md
```

不要提交虚拟环境、缓存、构建产物、测试输出、真实 EEG、刺激图片或 BIDS 输出。项目采用 MIT License。
