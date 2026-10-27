# VSPE 虚拟串口

EmotivPRO 的串口 Trigger 流程可使用 Eterlogic VSPE 创建一对虚拟 COM 端口。64 位 VSPE 需要有效许可证；请先阅读并接受 Eterlogic 安装向导中的许可条款。

运行 `setup_virtual_serial.bat` 时，如果尚未安装 VSPE，脚本会从 [Eterlogic 官方下载页](https://eterlogic.com/Downloads.html)下载正式版 x64 1.5.8.489 ZIP，从中提取唯一的 MSI，并在启动安装器前验证已固定的 SHA256 和 Eterlogic Authenticode 签名。安装包只暂存在系统临时目录，流程结束后删除；仓库不再保存或分发 MSI。

运行 `check_virtual_serial.bat` 只检查 VSPE 是否已安装并列出系统 COM 端口，不联网、不安装软件。安装后在 VSPE 创建 Pair，再按界面提示将两端分别配置给 EmotivPRO 和 `run_emotion_v3.bat`。端口存在不代表设备连接、Trigger 配对或实验采集已通过验证。
