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

如果运行时没有检测到完整 540 个正式视频，程序会自动进入 placeholder 模式：练习 trial 和正式 trial 都使用一个 5-10 秒的黑屏虚拟视频，以便在没有完整素材时测试流程。

## 配置

推荐配置为：

```yaml
protocol:
  video_library_dir: video_library/selected_540_balanced_videos
  video_library_mode: local
```
