# Windows 1.0.3：移除三条损坏视频，保留已有进度

v2不再播放或要求Session20的6076.mp4、Session24的2693.mp4、Session33的6241.mp4。其余视频原Session分配不变，共11,084条（普通7,946、情绪3,138）；保留1.0.2片尾修复。

**最小更新：保存退出并确认备份 → 把EXE复制到实验室本机 → 关闭程序后直接安装 → 原入口、v2、原编号、原Session继续。**无需卸载、重装环境、重迁移或重拷视频库。主试先用独立编号检查真实设备、声音、评分及写盘。

受影响旧Session先自动逐字节备份状态，再仅排除指定待播放项；EEG、attempt、答案和实际观看时间保留。未完成题目若绑定在排除片上，只将该题绑定到同组尚未完成且未绑定其他题的普通片，并记录映射。已完成Session不重写。无安全候选则保留状态并停止，不补造答案。

沿用现有本机材料路径及C:/Users/EDY/Desktop/video/data/sourcedata。共享母库和旧v1保留，不用手删MP4。文件保留不代表免于数据质量检查，中断及重复暴露应单独标记。

[详细步骤与旧数据说明](https://github.com/18yiba/visual-video-task/blob/master/docs/operations/V2_MATERIAL_REMOVALS.md)。软件回归使用模拟EEG，真实设备未在本轮验收。下载后可用同页SHA256SUMS核对安装包字节。
