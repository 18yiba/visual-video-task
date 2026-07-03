# 视频材料库

实验程序**只从此目录**（`config.yaml` → `protocol.video_library_dir`）加载刺激视频。

## 目录结构

```
video_library/
  manifest.json    # 视频目录（10 条 assets）
  stim_001.mp4
  stim_002.mp4
  ...
  stim_010.mp4
```

## 文件命名

视频文件必须命名为 `stim_001.mp4` … `stim_010.mp4`，与 `manifest.json` 中 `assets` 一致。

若原始文件名不同，在本机终端（Cursor 底部已打开的 `(omni)` 终端即可）执行一行：

```bat
D:\QW_FILE\visual-video-task\video_library\_rename.cmd
```

执行完成后可删除 `_rename.cmd`。

## 加载模式

| 模式 | 行为 |
|------|------|
| `local` | 扫描目录中的视频文件 |
| `manifest` | 读取 `manifest.json` |
| `auto` | 优先 manifest，否则扫描目录 |

当前 `config.yaml` 使用 `local` 模式，需保证磁盘上存在与 manifest 同名的文件。
