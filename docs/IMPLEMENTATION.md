# Implementation

核心入口：

```text
video_eeg/experiment/video_runner.py
```

主要模块：

```text
video_eeg/devices/     # 采集设备适配层
video_eeg/experiment/  # 实验 session、marker 和 trial 流程
video_eeg/storage/     # session 数据写出
video_eeg/utils/       # marker、视频库扫描、播放列表构建
```

正式启动器调用：

```text
python -m video_eeg.experiment.video_runner --config video_eeg/config/video_config.yaml --real-eeg --device-type brainco --brainco-transport sdk
```

Demo 启动器调用：

```text
python -m video_eeg.experiment.video_runner --demo
```