# NAS视频材料设置（Windows v0.3.3）

EMOTIV/EmotivPRO、博睿康两个v3入口共用只读材料设置。普通视频位于共享根目录的videos，情绪视频位于emotion_video/selected；不移动EEG、面部录像或Session状态，不改变固定成员、题库或协议哈希。

## 设置与切换

先在Windows资源管理器打开SMB共享并用Windows登录，确认可以读取视频。进入任一设备控制台，点击“视频材料位置（本机 / NAS）”，或从开始菜单打开“视频EEG视频材料位置（本机或NAS）”。输入包含videos和emotion_video的根目录，例如 `\\NAS\share\video_materials\formal_v1`，保存后两个设备入口都会使用该位置。也支持固定本机磁盘目录和已映射的NAS盘符；优先使用UNC路径，以免不同电脑盘符不一致。

安装版设置保存在 `%LOCALAPPDATA%/VisualVideoTask/materials.local.json`，源码默认保存在项目的materials.local.json；仅包含ordinary_root和emotion_root，不含密码，不进入Git或源码发行。目录选择失败时保留原设置。旧安装的路径和数据根不自动迁移；未设置该文件时继续沿用原材料位置。Demo不读取NAS正式库。

## 校验与恢复

启动前检查目录可访问，每段正式视频播放前核验SHA256：普通视频使用不可变materials_manifest.json，情绪视频使用原Session清单。NAS只读；声音提取临时文件、录像、EEG、行为和session_state都保留在本机。选择NAS后，不会因断网或空目录回退到另一份本机材料。

断网、权限不足或读取/解码失败时按原异常保存流程停止，当前未完成视频保留待重播；系统SMB超时和缓冲可能使故障报告延迟，软件不承诺断网瞬间停止。恢复共享后继续原编号、原Session；不要改题库、修改材料哈希或创建新被试绕过故障。

当前支持直接SMB文件读取，不是网页视频链接，也不自动下载整个材料库到本机。真实NAS播放、摄像头与模拟EEG检查不代表已完成真实EMOTIV/博睿康联合采集验收。
