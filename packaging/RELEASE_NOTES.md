# Windows v0.3.2：双设备入口与情绪视频面部录像

本版同步GitHub master的src布局和v3情绪视频录像功能，自带Python、PsychoPy、设备适配器、FFmpeg H.264及官方离线BIDS校验运行环境，无需另装Python。视频材料单独准备，不包含被试记录、本机配置或摄像头影像。

## 安装和入口

先正常保存并退出实验，再运行 `VisualVideoTask-Setup-Windows-x64.exe`；已有数据和本机设置保留，不需卸载或重建被试。安装到当前用户 `%LOCALAPPDATA%/Programs/VisualVideoTask`。

- 开始菜单“视频EEG v3 EMOTIV设备入口”：EmotivPRO外部录制及Trigger发送端流程。
- 开始菜单“视频EEG v3 博睿康设备入口”：Collect数据转发、TCP接收及同步盒TRG流程。
- “视频EEG总范式”及“v3实验控制台”默认EMOTIV；旧v1/v2入口继续保留Demo/正式，不改变原协议或历史进度。

## 情绪视频面部录像

两个设备的v3 EEG阶段均使用UGREEN Camera 4K录制1080p/30帧无声H.264 MP4；普通视频、独立评分重播及v1/v2不录制。文件直接保存在当前Session，依次为“编码_facial.mp4”“编码_facial_02.mp4”等，已有录像及中断片段保留。

录像前后各至少0.5秒，解码时长须同时不短于材料时长及实际播放时长，验证通过后才提交该视频完成；设备或录像故障停止并保存进度，当前视频保留待重播。逐帧时间文件和录制日志关联EEG事件，软件观察时间不代表曝光时刻或硬件级同步。

## 源码一致性与验证边界

安装包 `BUNDLE_MANIFEST.json` 保存版本、准确Git提交、两个设备入口及逐文件SHA256，`app/SOURCE_MANIFEST.json`保存源码清单；构建会拒绝与提交不一致的源码。Release另提供白名单源码ZIP和SHA256SUMS.txt。录制原件和session_state仍是恢复依据，BIDS/EEGQC只是独立交接副本。

真实UGREEN摄像头、真实PsychoPy窗口及模拟EEG验证不替代EMOTIV或博睿康真实设备联合验收。真实EEG、长时间负载、拔线和屏幕闪烁同步偏差仍需现场验证；既有BrainCo `(96, 33)`布局问题未修复。本版不改变固定成员、题库、疲劳量尺或旧Session合同。
