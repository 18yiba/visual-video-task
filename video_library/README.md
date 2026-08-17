# 视频材料库

正式刺激视频请放入以下目录：

```
video_library/
  selected_540_balanced_videos/
    100025_科技商业.mp4
    100084_时尚美妆.mp4
    ...
```

`selected_540_balanced_videos/` 已在 `.gitignore` 中忽略，视频文件不会提交到仓库。

## 文件命名

正式视频文件名应保持为：

```
视频ID_分类名.mp4
```

例如：

```
100025_科技商业.mp4
100150_游戏动漫.mp4
```

后续实验代码会根据文件名中下划线后的分类名进行均衡抽样。

独立 PsychoPy 视频实验不会使用 placeholder。视频数量不足、分类缺失或文件不存在时，程序会在创建实验窗口前报错，避免把黑屏误当作正式刺激。

## 配置

推荐配置为：

```yaml
protocol:
  default_video_sec: 60.0
  eyes_open_baseline_sec: 60.0
  eyes_closed_baseline_sec: 60.0
  video_library_dir: video_library/selected_540_balanced_videos
  video_library_mode: local
```
