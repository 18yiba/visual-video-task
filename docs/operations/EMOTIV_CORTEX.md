# EMOTIV Cortex 直接采集（源码更新，2026-11-07）

EMOTIV v3 控制台默认使用 Cortex 直接接收并保存 EEG；面部录像默认不勾选。已发布 v0.3.8 安装包未重建，仍按旧模式运行，更新源码须正常保存退出后重启。

## 使用

1. 启动本机 EMOTIV Launcher / CortexService，在 Launcher 中连接真实设备，确认应用具有 EEG 访问许可。停止占用同一设备的 EmotivPRO 会话；程序遇到已有会话会停止，不替主试关闭它。
2. 将本人授权的凭据 JSON 放在本机安全位置，通过 `EMOTIV_CREDS` 指定路径，内容字段为 `clientId` 与 `clientSecret`；也支持当前目录或 `~/.emotiv/credentials.json`。不要提交、打包或共享凭据；本次未复制附件 ZIP 中的 credentials.json。
3. 从原 `run_emotion_v3.bat` 进入，选择“Cortex SDK 直接采集”，点击“检测 Cortex EEG”。多个设备时用 `EMOTIV_HEADSET_ID` 明确设备；采样率和通道来自设备与订阅响应，未知参数不猜测。
4. 根据需要勾选“采集面部录像（可选）”。不勾选时不打开或预检摄像头，也不发送164；勾选后仍要求完整录像覆盖，摄像头故障会中断当前试次。EEG 始终必需。
5. 采集保存后从同一控制台“开始行为评分”进入。旧 EmotivPRO 记录仍需原来的外部 EDF 登记，可切回“EmotivPRO 外部录制（旧模式）”；历史标识、Session、目录和答案不转换。

源码命令支持 `--emotiv-transport cortex|serial` 与 `--facial-recording` / `--no-facial-recording`，通过 `main.py --protocol v3 --device emotivpro --phase acquisition --emotiv-transport cortex --no-facial-recording` 转发。原串口参数仍选择旧模式。开关只影响本次新采集，不改旧录像。

## 原始记录与故障

Cortex EEG 按实际订阅导联顺序写 `continuous_eeg.npy`，单位 µV；metadata 保存通道、设备ID、Cortex session/record ID及采样率。`cortex_packets_part_XXX.jsonl` 保留原包、Cortex Unix 时间、主机到达时间与打标回执；结束时未提交尾包标注 `uncommitted_tail`，不能据此自动扩展完成状态。reference/filter 未核实保持 unknown。备份整个 Session。

单接收线程、有界队列、RPC 超时与错误传播；断流由现有健康监视器停止。队列溢出、重复/跳号、时间倒退/异常间隔、Cortex 插值包会停止，不自动重连或填补。已写数据和中断试次保留，重新检测后用原编号续跑。官方每秒回绕与附件 Flex SDK 的16位 counter 回绕均显式支持，其他格式需现场核实。

打标先 createRecord，再 injectMarker（毫秒 Unix 时间），最后按 session 调用 stopRecord。软件回执不代表曝光同步或物理硬件 TRG；事件样本位置为主机读取到达估计，原始时间戳可供另行审计，未宣称采用 SDK 漂移校正。Cortex 本地 record 是并行记录，程序的原生保存与 session_state 仍是恢复依据。EMOTIV BIDS/EEGQC设备配置尚未验收，不套用 BrainCo 参数。

## 依赖与验收

使用现有 `websockets` 同步客户端实现本地 Cortex 协议；参考附件0.2.3客户端流程，未安装附件包或复制其凭据。候选依赖和 uv.lock 已更新；未同步现有实验环境。新环境按项目部署文档安装第三方依赖，项目自身仍不安装。真实设备需核验连接、持续样本、长时运行、断连保存、标记接收、重播续跑及实际信号质量；模拟通过不能保证真实硬件稳定。

接口依据：[设备采样率与通道](https://emotiv.gitbook.io/cortex-api/headset/headset-object)、[原始包](https://emotiv.gitbook.io/cortex-api/data-subscription/data-sample-object)、[injectMarker](https://emotiv.gitbook.io/cortex-api/markers/injectmarker)、[stopRecord](https://emotiv.gitbook.io/cortex-api/records/stoprecord)。修复版README中的性能数值未作为验收依据。

开发验证：409项、12个子测试通过，5项跳过；真实Qt/PsychoPy窗口配合模拟EEG分别验证关闭录像与合成摄像头开启录像，三段采集、评分退出续跑和EEG文件不变。源码发行包单独验证两个入口；未使用真实EMOTIV硬件。
