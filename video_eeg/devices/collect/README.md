# `collect` 目录说明

这个目录保存了从旧项目迁移过来的 Neuracle / JellyFish 相关代码。

## 当前 `oi-mi` 仍在使用的文件

- `neuracle_api.py`
  - 提供 `DataServerThread`
  - 当前被 `NeuracleAcquirer` 直接复用
- `triggerBox.py`
  - 提供 `TriggerBox`
  - 当前被 `TriggerBoxMarkerBackend` 直接复用

## 已归档的历史实验代码

- `legacy/client_experiment.py`
- `legacy/pygame_experiment.py`

这两份代码来自旧的图形化实验流程，依赖 `pygame`、HTTP/socket 交互以及缺失的旧预处理脚本，
**不是当前 `oi-mi` CLI 主流程的一部分**。

如果后续要继续整理真实采集链路，应该优先围绕：

- `collect/neuracle_api.py`
- `collect/triggerBox.py`

而不是回到 `legacy/` 里的实验脚本。