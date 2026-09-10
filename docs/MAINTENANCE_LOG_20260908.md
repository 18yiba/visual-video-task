# 2026-09-08 维护记录

## 用户目标

核实桌面完整版题库是否覆盖每条视频；整理 video 工作区；保留范式运行和数据记录；
参考 oi-eegqc 编写实验说明，提供详细操作文档；准备向 18yiba/visual-video-task 发布源码；
确保其他 Windows 电脑可双击安装、正式和 Demo 入口。

## 路径核实与题库结论

实际桌面入口为 `视频题库完整版_采脑电.bat`，指向
`video/visual-video-task-complete-20260908/run_complete_formal.bat`。
用户写出的 `视频题库完整版/_采脑电.bat` 目录形式当前不存在。

快照文件 SHA-256：`6ed36faaccdb4b4d3982c1304ae1252967dd50e2543353c2707fc4231ed2466a`。
视频母库 7996 段；正式 7949 段；题库 7993 道；正式覆盖 7946 段。
缺题：5728.mp4、6722.mp4、6883.mp4。未发现题目重复绑定或题目所指视频文件缺失。
题目状态为 ready 2779、generated_unreviewed 5214。
因此不能宣称每条视频都有题，也不能宣称所有题都完成独立复核。

## 修改

- 将上述快照复制到主项目 complete_questions_20260908，并保留来源及复核状态记录。
- 主正式/Demo 配置启用新版题库；正式输出另存 data/video_question_complete_runs。
- 保存旧配置为 video_legacy_2779_config.yaml，增加 run_video_legacy_2779.bat 续跑入口。
- 保留完整范式第一页及抽查页简短答题说明。
- 重写安装器：健康环境复用；新机器自动下载本地 uv/Python 3.12，安装依赖及本地 BIDS 转换器源代码。
- 真实母库缺失时，Demo 使用安装器生成的合成练习片；正式仍要求原母库及固定清单。
- 增加材料审计、源码打包脚本和敏感/大文件排除规则。
- 根目录安装及环境检查移除 Node.js/评分程序前置条件。
- 编写实验说明、详细操作文档及工作区/项目 AGENTS.md。

## 清理与保全

清理前为 239 个既有数据文件建立 SHA-256 基线，共 2,787,407,616 字节。
主项目与独立完整版的 data 均保留，正式母库未迁移。
评分程序、Node、旧根目录 uv 工具、两组 BIDS 测试目录移入 `_archive/non_eeg_and_legacy`。
旧根目录安装/检查脚本保留归档副本。
删除三个已损坏的旧虚拟环境与可再生成的 uv 下载缓存；当前 `.venv` 和其 base Python 保留。
机器本地精确移动清单及数据哈希在 `_maintenance`，不发布到 GitHub。
独立首次安装验证结束后，其模拟记录和安装日志移入 `_archive/validation_20260908`；
临时测试环境、下载缓存与失败的 Git clone 暂存目录已清理，避免重新堆积无用副本。

## 安装验证中发现的问题

从独立源代码副本执行首次安装，成功下载 uv 和 Python；发现 uv 不接受
`-r lab_uv_env.toml` 作为 pyproject 依赖输入，修正为复制到 `.uv_lab_env/pyproject.toml`。
再次运行发现 uv python find 会选中旧 venv，修正为 `--managed-python --system --no-project`。
下载 Python 增加 `--no-bin --no-registry`，不要求修改系统 PATH 或注册 Python。

## 发布状态与验证记录

最终验证结果：

- 主工作目录：49 项测试全部通过，7949 个正式视频文件检查通过，17 个 Session 各可生成 18 个唯一抽查目标。
- 独立源码副本：从无 uv、无 Python、无 venv 开始联网安装成功，使用本地 Python 3.12.14。
- 独立环境：47 项测试通过，2 项真实母库集成检查因源码包未附带材料而跳过。
- 独立环境真实 Demo 入口：10 段合成视频、3 次抽查，Session 完成；CSV、连续 EEG 及 3 对抽查事件验证通过。
- 工作目录真实视频单轮 smoke：0001.mp4 与对应题目显示、作答、记录通过；截图包含总体说明和抽查页。
- 从另一工作目录执行安装 `.bat --no-pause` 成功；健康环境复用检查通过。
- 数据保全：239/239 个既有文件 SHA-256 一致，0 个缺失或改变。截图验证改为每次运行独立存放。
- 未连接真实脑电设备；未在另一台物理电脑上测硬件。独立环境测试不等于物理时序和信号质量验收。

机器可读摘要：`clean_install_validation.json`、`material_audit_latest.json`。
Word 版操作说明和实验说明由 `scripts/export_manual_docx.py` 从 Markdown 导出。
题库 CSV 为 `complete_questions_20260908/questions_audit.csv`，保留状态和来源。

发布白名单仅包含源代码、题库、清单、文档、测试及许可文件。
不含真实视频、受试者记录、已安装环境或凭据。
GitHub 目标仓库可读，默认分支 master，审计时 HEAD 为
`81f7a6dfe78a70e538ab7dac17813deaa0c9e72b`。目标仓库现含旧图片范式和素材，
发布应保留远端历史，不做强制推送。CLI 尚未以用户要求的 18yiba 登录；
连接器身份不同，未使用该身份代替用户发布。对话中提供的密码未写入任何文件或命令。

Git 只读 clone 两次尝试遇到连接重置/停滞；GitHub REST 只读文件列表与参考 README 已成功读取。
最终源码包在工作区 `release` 中准备；目前未向远程创建提交、推送分支或覆盖远程内容。
后续使用 18yiba 的浏览器授权登录 `gh auth login` 后，再从白名单源码包发布并记录提交 SHA。
不要把当前含 data、环境及旧项目的整个工作区直接上传。
