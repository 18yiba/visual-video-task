# EEGQC 单记录交接（源码待发布）

当前源码按[采集端软件数据存储规范（2026-09-30 第一版）](https://omni-intel.feishu.cn/docx/KrHNd7XgZomAJMxuks8cNonQnwq)生成独立 EDF/BIDS 交接包；GitHub 已发布的 Windows 1.0.4 仍是 BrainVision 导出，尚未替换安装包。

## 配置后才能交接

v3按用户提供的第一版规范及本地 `examples.zip` 视频模板接入同一EDF/BIDS导出器：范式代码 `EMOVID-20261008` 已于2026-10-11确认，全部视频和仅情绪视频共用；任务标签为 `videov3`，完整代码在 `session.json`。v3控制台填写平台8位编号与代码，采集metadata保存身份/代码快照；新原生BrainCo EDF可用这些快照直接导出，无需额外设备配置文件。`eegqc.local.json` 可配置输出位置、`participant_map.v3` 旧编号映射及后续范式变更；不使用示例中四导配置替换实际32导。

v3独立行为评分没有EEG，保留原始行为CSV及状态，不混入已有记录的BIDS事件或改写封存包。全部视频模式采集中发生的普通喜好/抽查/疲劳仍按原事件与行为保存。新段UUID与平台预约Session无关联；仅在EEGQC人工确认范式、评分、上传和回写。

将 `video_eeg/config/eegqc_settings.example.json` 复制为本机私有 `eegqc.local.json`：源码版放项目根目录，安装版放 `%LOCALAPPDATA%/VisualVideoTask`。文件被 Git 和源码白名单排除；不要把被试映射提交到 GitHub。

必须填写以下四组信息，空模板不能用于正式导出：

- `paradigm_codes.v1/v2`：默认均为已确认的平台 code `AVEEG-20260923`。`task-videov1/videov2` 只是文件名标签；不是平台 code。平台日后变更时，先保留已导出包，再由负责人更新本机配置。
- `participant_map.v1/v2`：原实验编号到平台 8 位字符串编号的映射，例如 `{"旧编号": "00000001"}`。当前被试编号已与平台 8 位编号一致，可保持为空；不自行补零、不根据姓名生成、不改原始状态编号。主试仍需在平台确认该编号确实存在。
- `device`：仅旧NPY转换需提供实际 `model`、`confirmation`、`software_filters`及原31导的 `physical_ranges_uv`，沿用旧计数/IO参考合同。新原生EDF以采集时metadata快照为准，直接复制，不用后续配置覆盖通道或量程。具体硬件型号、低通和陷波仍未知，不能称为无滤波；其他设备需独立适配。
- 旧记录没有带时区起止时间时，在 `recording_times` 下以导出错误给出的 UUID 为键填写 `started_at`、`ended_at`、`clock_basis`；均需核对原日志，不能填写上传时间或猜测。原记录不回写。

文档存储位置尚为“待定”。当前可配置 `output_root`，默认使用现有 `sourcedata` 同级的 `eegqc`。原始数据与旧被试的续跑位置不变，多根冲突规则不变。

## 实际目录

```text
data/
  sourcedata/                         原始记录、行为、状态，原地保留
  eegqc/
    recording-<UUID>/                 每段独立、可单独交接的BIDS数据集
      dataset_description.json
      participants.tsv
      participants.json
      .bidsignore                     忽略公司扩展 **/session.json
      sub-00000001/
        ses-<UUID>/
          session.json
          eeg/
            sub-00000001_ses-<UUID>_task-videov2_run-01_eeg.edf
            ..._eeg.json
            ..._channels.tsv
            ..._events.tsv
            ..._events.json
      code/
        export_receipt.json
        validation_report.json
        validation_status.json
```

每个包只包含一段小写 `.edf`，不并排放 BrainVision、float32 或多个 run。`ses-UUID` 是连续记录编号，原实验 Session 1–45/1–17保存在 `session.json.source_session_number`，不是平台预约 Session ID。原始数据的 `session_id` 保持不变。

## 采集、封存和重试

新采集启动即保存 `recording_identity_part_NNN.json`、UUID4及EDF配置快照；事件追加到 `events_journal_part_NNN.jsonl`。连续采集写入可恢复float32临时spool，正常保存生成EDF后移除本段临时spool，不生成NPY；写盘或量程检查失败保留spool。零样本仅保存事件和metadata，不伪造空信号。metadata保留样本数、采样率、通道、量程、量化步长及带时区起止时间。断电后的临时文件需审计，不能当作正常封存记录。

交接只在原始保存结束后进行；配置不完整、EDF写入失败或官方校验失败会提示待重试，不影响已保存的原始记录。Demo 不生成正式交接包。每次重启采集是新 UUID，断流后不拼接、不补零。旧记录没有 UUID 时依据协议、原编号、实验组、采集时间戳和 part 生成稳定 UUID5，原件不改；身份碰撞而内容不同会拒绝覆盖。

先写独立暂存目录，完成后一次性改名为 `recording-UUID`。失败暂存目录保留供审计，不自动删除未知文件。重试检查原始与输出哈希；源数据、配置或已交付文件变化时停止，不能静默覆盖。官方校验逐行、离线运行，结果单独写入 `code/validation_status.json` 和原始报告。`export_receipt.json` 中 `NOT_RUN` 是封存时状态，最终以校验状态文件为准。

## 信号和事件语义

新原生EDF由edfio保存全部32导，按CH01→CH32：P8、P7、T8、T7、F8、F7、O2、O1、P4、P3、C4、C3、F4、F3、FP2、FP1、TP10、TP9、FT10、FT9、CP6、CP5、FC6、FC5、CP2、CP1、FC2、FC1、IO、Pz、Cz、Fz；不把CH01丢弃为计数。主试2026-10-08确认单位uV、±375 mV即±375000 uV及默认高通0.16 Hz；FCz为REF、AFz为BIAS。低通/陷波未知，不在程序内再次滤波。EDF16位量化步长约11.44 µV，交接直接复制原EDF，不二次量化。原样保留采样点数、采样率，不裁尾、不补齐末秒、不重采样。旧NPY仍按原31导合同转换且保留原件；超量程、NaN/Inf或旧计数异常停止交接。

`events.tsv` 前两列为 `onset` 和 `duration`。视频呈现占一行 `trial_type=video`，休息为 `rest`；原始点事件另标为 `marker`，行为汇总为 `behavior_summary`，不把它们当成额外刺激。每次重播有独立 `trial_id`，素材用稳定 `stimulus_id`，原 trial/attempt 和答案保留。完成为1，中断为0；证据不足用 `n/a`，不依据计划时长推断完成。

`sample_index` 从0开始，未知或文件末端之外填 `n/a`；`onset` 根据当时软件观察的样本数定位，`duration` 使用实际呈现软件时钟间隔。`trigger_value` 仅在外部发送明确成功时填值；软件发送与设备收到不同。`timing_source=software_timestamp`，原始呈现/发送时间保留在 `source_details`；无硬件校准结果，不填虚构的0延迟。内部断流和无效对齐标记保留，不以格式通过宣称信号有效。

## 主试操作

配置齐全后，新正式采集自动导出并校验。开始菜单原“视频EEG导出与检查BIDS”在本次源码构建后改为单记录交接导出；先选原协议，再选已保存记录目录。CLI 可使用：

```powershell
python scripts/export_eegqc.py --source "已结束采集的目录" --output "独立交接目录" --protocol v2 --config "本机/eegqc.local.json"
```

v3手工重试使用相同命令并改为 `--protocol v3`；公司身份和代码优先使用原采集metadata快照，不能因后来改配置或评分而变更已封存记录。原始记录和续跑目录始终不移动。

新v3原生EDF已保存身份快照时，手工重试可省略 `--config`；输出默认建议独立 `data/eegqc`，正式运行时自动完成，CLI仍需显式指定 `--source`、`--output` 和 `--protocol v3`。仅一采样点但能够读取的中断EDF同样保留并可交接，不填充或冒充正常完成记录。

默认运行官方校验；维护时 `--no-validate` 仅导出，不能宣称已验证。旧 BrainVision 分析工具 `scripts/export_bids.py` 保留，不能将其输出当成当前 EEGQC 已支持的交接格式。

将完整 `recording-UUID` 目录交给 EEGQC；如需ZIP，封存后保留完整相对目录打包。EEGQC 当前仍需人工选择本项目范式，并且整文件评分；有 events.tsv 不代表已支持逐视频评分。评分、可用时长、上传、回写及入库回执由 EEGQC 负责，采集端不代填质量通过、不自动上传。
