# 历史博睿康 NPY 转 EDF

`scripts/convert_neuracle_npy.py` 将一个已结束的采集分段转换为独立 EDF 副本，不改原 NPY、状态、事件或答案。它不会把中断段补成完整 Session，不切分、拼接、滤波或重采样。

## 在采集电脑执行

正常退出采集程序，在最新源码项目根目录打开 PowerShell。使用已有实验环境（需要 numpy、edfio）；无需安装本项目。下面替换实际路径，输出必须是尚不存在、且不与源采集目录互相包含的新目录：

```powershell
.\.venv\Scripts\python.exe scripts/convert_neuracle_npy.py --source "D:\数据\v3_neuracle\13467638\session_01\20261022_160505" --output "D:\EDF副本\13467638\session_01\20261022_160505"
```

上面仅预览，读取 NPY 头部和元数据；通过后在同一命令末尾加 `--apply` 才转换。每次处理一个时间戳目录中的 `metadata.json` 对应分段；不自动遍历所有被试，也不自动处理其他 `metadata_part_*.json`。失败时保留可能生成的部分文件供核对，未生成成功回执就不能当作已验证输出；重试使用新目录。

## 输入、输出及校验

- 输入须同目录包含 `metadata.json` 指定的 NPY 和事件 JSON，以及 `eeg_segments.json`；完整转发通道、TRG索引、已保存采样率与NPY形状必须一致。仅支持同采样率、float32、已 finalized 的博睿康分段；混合采样率和未知结构停止，不猜测。
- 输出为 `continuous_eeg.edf`、事件 JSON、衍生 `metadata.json`、`conversion_receipt.json`。衍生元数据保留原UUID、身份、协议及分段状态，标明转换来源与哈希；不能替换回 sourcedata 用于续跑。
- EDF回读检查通道顺序、样本数、采样率与逐通道量化误差，TRG逐样本完全一致；转换前后源文件SHA256必须相同。单位、参考、滤波未核实就保持未知，不套用BrainCo配置。EDF是量化格式，不能宣称原浮点值逐字节无损。
- 转换需要原数据、EDF和校验数组的内存及独立磁盘空间；长记录可能占用数倍NPY大小的内存。原NPY和所有历史记录不删除。`esc_emergency`等中断原因照实保留；转换成功不代表信号质量或硬件验收通过。
- 本工具只完成一个信号分段及事件的EDF转换，不是完整BIDS/EEGQC交付，不复制Session行为CSV。回执始终标记BIDS校验未运行。完整交接还需行为归属、公司元数据、通道/事件TSV和官方离线验证；不能因扩展名为EDF就宣称符合模板或BIDS。
