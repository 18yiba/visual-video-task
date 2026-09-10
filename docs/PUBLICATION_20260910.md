# GitHub 发布记录（2026-09-10）

- 仓库：https://github.com/18yiba/visual-video-task
- 默认分支：master
- 实际认证账号：0hSophia，已核实具有目标仓库写入权限。
- PR：https://github.com/18yiba/visual-video-task/pull/1 （已合并）
- 源码提交：`3121f81306984410a0ad113dc9c0a3cd2092b9de`
- 代码合并提交：`77ad8cb31d32e97945538bc84e97aeffd991b24e`
- 合并时间（UTC）：2026-09-10T01:46:22Z

发布前核对 124 个白名单源文件 SHA-256，与此前验证过的源码包完全一致。
远端 125 个 blob（包含 SOURCE_MANIFEST.json）逐一核对 Git blob SHA，路径和内容全部一致。
通过独立分支和 PR 合入默认分支，保留原 Git 历史，无强制推送。
旧图片范式及素材从当前默认文件树移除，仍可通过原历史提交查看。

不发布受试者数据、真实刺激视频、密码/令牌、已安装环境或缓存。
源码的功能验证沿用 2026-09-08 记录：本机 49 项测试通过；独立首次安装成功，
完整 Demo 完成 10 视频和 3 次抽查，模拟 EEG 与事件记录验证通过。代码未因本次上传改变。
本次操作未启动新的实验采集，未修改本地被试记录，真实脑电设备未重新测试。

正常下载默认分支后，完整解压并双击 `scripts/install_lab_env_uv.bat`，
再运行 `run_video_demo.bat`。正式入口 `run_video_formal.bat` 仍需实验室视频母库和真实设备。
当前快照仍缺 5728.mp4、6722.mp4、6883.mp4 三题；不能把“源码上传完成”理解为题库全部复核通过。

此文件记录代码发布提交；维护记录与清单的文档提交可能晚于上述合并提交。
本地最终发布回执位于工作区 `release/PUBLICATION_RECEIPT_20260910.json`。
