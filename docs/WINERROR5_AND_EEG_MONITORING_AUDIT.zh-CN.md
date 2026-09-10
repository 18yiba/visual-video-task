# WinError 5 与 EEG 断联、质量监测审计

审计对象：本机 visual-video-task-master，并交叉检查 complete-20260908 副本的相关实现。实验室实际安装版本和两次事故完整 traceback 尚未取得。用户报告：正常观看约半小时或三小时后出现拒绝访问，重启同编号能续做，已有 trial 记录，部分通道阻抗颜色异常。

## 结论

截图显示数据目录下的“源路径 → 目标路径”及 WinError 5，优先指向文件替换/重命名失败，而非阻抗阈值。截图右侧文件名被裁掉，不能确定具体文件或进程。当前代码没有阻抗、电量或逐通道信号质量阈值终止条件。

## 可定位的代码

- `video_eeg/experiment/video_runner.py`：`_write_trial_log`、`_write_attention_log`、`_write_rest_log`、`_write_session_summary` 写临时文件后直接 `replace` 正式文件。没有短暂文件占用重试。
- `video_eeg/utils/session_protocol.py`：`save_state_atomic` 将 `session_state.json.tmp` 替换为 `session_state.json`。`_checkpoint` 先写 summary，再写 state，因此这些文件不是一个跨文件事务。
- `video_eeg/experiment/ready_question_runner.py`：内容题日志 `video_question_log.csv` 同样使用临时文件替换。
- `video_runner.run`：异常进入通用出错面板；异常分支还会再次 checkpoint。`_stop_and_export` 先写行为日志和 checkpoint，再调用 EEG 导出。同一文件若持续被占用，二次保存异常可能阻断 EEG 正式导出和 crash_report 写出。
- `video_eeg/storage/session_recorder.py`：EEG 先流式写原始临时文件，最终转换 NPY；导出也有重命名操作，但正常观看期间优先排查反复发生的进度/日志替换。旧记录并不由普通进度更新主动清空。

因此“能续做”和“trial 有记录”只证明部分进度已保存，不能据此认定整个 EEG 时间段完整。失败点附近最后一个视频/回答可能未完成提交，应核对 state、trial 和各 EEG 分段。

## 本机复现

在独立维护测试目录创建一个 CSV 和一个临时文件，保持目标 CSV 的普通 Python 读取句柄打开，再调用 `Path.replace`：出现 `PermissionError`，`winerror=5`。关闭句柄后相同替换成功。未访问实验数据。

另用返回空数组的模拟采集器连续调用 SessionRecorder.pull 100 次：sample_count 始终为0，没有异常。它验证当前没有空流超时机制，不是对实体放大器断电的测试。

Windows 文件共享规则要求重命名涉及删除访问；打开的句柄未允许 FILE_SHARE_DELETE 时可阻止这种操作。参考 [Microsoft CreateFileW 文档](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)。

## 可能原因及排查顺序

1. 先取得事故分段的 `crash_report.txt`，检查 traceback 最后一个本项目函数和完整源/目标路径。不要仅凭被裁掉的照片判断是哪个 CSV/JSON。
2. 回忆事故发生前是否用 Excel/WPS、编辑器、脚本打开了正在更新的 trial/attention/question CSV 或 JSON。运行中查看日志应看另存副本，不保持原文件打开。文件被占用已本机复现；并非所有查看器都会锁定文件。
3. 核查是否同时启动两份范式、使用相同被试和 Session。当前固定 `.tmp` 文件名且未见对应的 Session 跨进程排他锁，并发写入可竞争；可能导致不同错误或进度问题。
4. 核查安全软件保护历史、同步/备份软件在出错时刻的活动。它们只是待证实候选，不应直接关闭防护或认定为原因。
5. 检查完整目标文件的只读属性、当前用户修改/删除权限、实际磁盘及剩余空间。长期运行后恢复的表现更符合临时占用，但不能排除权限或安全软件动态变化。磁盘满通常有不同错误码，不能单凭运行了三小时认定内存或磁盘耗尽。

需要现场材料：两次出错的被试编号、Session、约发生时间、实际启动入口/版本，及对应 crash_report、session_summary、eeg_segments、metadata、events、trial_log。找不到 crash_report 时保留控制台文本和全部原始临时文件。

## 断电、断联和质量差时程序实际行为

| 情况 | 当前行为 |
| --- | --- |
| 启动前无 EEG 样本 | 启动/连接检查有超时，不能正常进入采集 |
| 已运行后阻抗升高、坏通道增多，但仍有数值样本 | 没有质量阈值判断，通常继续播放、记录这些样本 |
| 放大器断电/断联，SDK 返回空数组 | 没有运行中无样本超时；可能继续播放、行为继续推进而 EEG 停止增长 |
| 采集读取或写盘实际抛异常 | 后台存下异常，前台检查/事件发送时抛“EEG 后台采集失败”，进入错误退出流程 |
| SDK 仅发连接状态回调 | 当前回调只 `LOGGER.info`，不会据此终止、暂停或可靠恢复 |

`brainco_acquirer.get_chunk` 虽有新样本超时逻辑，但正式连续记录使用的是 `get_new_samples`，不能把前者当作正式流程的断联保护。真实 SDK 在具体断电情形中是抛错还是返回空流，仍需实体设备测试。

当前不读取/保存电量阈值，不计算质量阈值，也没有可靠的断流后自动暂停与恢复流程。现场发现设备断联时应人工停止，记录时间、恢复设备并按原编号续做；保留多个采集分段，不把断联期间的行为进度当作 EEG 有效覆盖。

## 现有哪些日志，缺哪些日志

在该被试、该 Session 的实际输出目录查找（旧版通常位于 `data/video_question_complete_runs`，新版34组在其 `protocol_34sessions` 下）。

| 文件 | 能回答什么 |
| --- | --- |
| `crash_report.txt` | 若成功写出，记录异常完整调用栈及出错路径；可能因导出再次失败而缺失 |
| `session_summary.json`、`session_state.json` | 退出原因、行为进度、续做状态；不是 EEG 质量报告 |
| `trial_log.csv`、`video_question_log.csv`、`attention_log.csv` | 刺激/答题及其时间，不证明 EEG 全程正常 |
| `metadata.json` / `metadata_part_*.json` | 采样率、样本数、设备、退出原因；采集异常时可能有 background_error |
| `events.json` / `events_part_*.json` | 事件相对时间与 sample_index，可辅助识别两个事件之间样本增长不足；并非每秒连接状态日志 |
| `eeg_segments.json` | 分段 EEG 文件及 finalized/incomplete_raw 状态 |
| `continuous_eeg.npy` / `continuous_eeg_part_*.npy` | 原始信号，可做事后质量检查；不能直接等同于阻抗记录 |
| `.continuous_eeg*.f32.tmp`、`.writing` | 中断时可能保留的采集/转换临时数据，切勿删除，需结合通道数等恢复 |

目前没有“每个时间点每个通道的阻抗/质量/电量”日志。连接回调只使用 Python logging；标准启动入口未配置专用持久化连接日志，不能保证 INFO 已被保存。离线更新入口的 formal_report.txt 是控制台转存，也不能补回未记录的质量信息。

重要时间轴限制：BrainCo 增量读取返回的是每块从0开始的合成时间；SessionRecorder.pull 丢弃传入 timestamps，只连续拼接样本。因此断流后重新有数据时，不能仅用 NPY 列号/采样率还原真实停流间隔。events 的相对时刻和样本数可帮助圈定异常区间，但不等于精确的逐样本设备时间戳。

## 后续加固建议（本次未修改运行逻辑）

- 给短暂文件占用增加有限重试、唯一临时文件；拒绝同被试同 Session 并发运行。
- 异常堆栈应先独立落盘；行为日志写失败也应继续尝试关闭采集和导出 EEG，避免二次错误阻断保存。
- 增加每秒采集健康日志：墙钟/单调时间、累计样本数、本秒样本数、距上次样本时间、连接状态；明确断流阈值和暂停/退出策略后实施。
- 独立定义信号质量指标及阈值；若需阻抗/电量，先确认 SDK 提供的接口和单位。不能把幅度异常或空流简单视为阻抗高。

本次只审计和复现，不改变已在实验室采集中的方案、源代码行为或现有离线包。
