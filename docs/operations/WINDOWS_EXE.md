# Windows EXE安装、离线材料与旧v1续跑

下载Release的 `VisualVideoTask-Setup-Windows-x64.exe`，在Windows 10/11 x64电脑双击安装。安装包包含完整Python、PsychoPy、Qt、视频解码器和设备接口；目标电脑不需要Python、uv、Node.js或联网安装依赖。安装后运行“视频EEG总范式”。

默认按当前Windows用户安装到 `%LOCALAPPDATA%/Programs/VisualVideoTask`，无需管理员权限。程序体积主要来自PsychoPy与视频/科学计算运行环境，正式视频不包含在安装器中。

## 实验室已有v1并正在采集

安装使用独立目录，不覆盖原程序。当前采集先按原入口正常结束、保存并备份，之后再切换新入口；不要在采集过程中改动设备配置或数据。

首次启动选择“绑定已有v1”，选择直接包含 `video_eeg` 的旧程序目录。新版会读取原17组配置、固定清单、题库及设备设置，已有被试继续在原数据根目录保存，不复制或重建Session。若旧版使用算术注意任务，保持原任务，不静默转换为内容题。旧代码、环境及数据不会被安装器改写。

只绑定原17组v1，不把历史34组或其他协议当成v1恢复。相同编号在多个候选目录都有进度时停止，不自动合并。找不到原配置或原状态时保留文件排查，不能删除state重新开始。

绑定后先用新测试编号做Demo，再由主试完成真实设备短测，核对原被试续跑位置，之后继续采集。原BAT入口仍可使用，但同一Session不能同时从两个入口运行。

开始菜单中的“视频EEG设置（绑定旧v1）”可以重新选择绑定位置。设置文件在 `%LOCALAPPDATA%/VisualVideoTask/settings.json`；更换绑定前正常结束采集。

## 离线材料

下载、复制安装包可以联网；日常运行不检查在线更新，不连接GitHub，不下载依赖。两个Demo使用自动生成的练习视频，无需正式材料。

普通母库 `videos`（7996段，约44.2GB）和情绪库 `emotion_video/selected`（3138段，约9.87GB）从移动硬盘复制到实验室本地磁盘。已有v1完整普通母库可直接复用；选择v2正式实验时才需要情绪库。

首次正式启动按提示选择目录，程序逐文件核对固定索引SHA256。核验不改名、不覆盖、不删除材料；出错会指出缺失或不匹配文件。后续根据大小和修改时间识别变化，对变化文件重新计算哈希。复制完成后保留目录位置，不要采集中拔出材料所在磁盘。

## 数据与设备

- 未绑定旧项目的新电脑：新记录在 `%LOCALAPPDATA%/VisualVideoTask/data/sourcedata/v1` 或 `v2`；Demo在独立 `demo` 子目录。
- 绑定旧项目：旧被试原位恢复；新被试默认放在旧项目 `data/sourcedata/v1` 或 `v2`，自定义旧保存根目录按原配置读取。
- v2与v1的Session编号和状态不可互换，不能把v1被试的进度迁入v2。
- 默认真实BrainCo SDK、1000Hz；绑定旧版时继承其设备配置。新电脑需要自定义设备时，可在用户配置目录添加 `device.local.yaml`，只支持 `device_type`、`device`、`sfreq`、`eeg_sampling_rate_hz`、`buffer_sec`。完整字段参考README的设备配置。
- 日志在 `%LOCALAPPDATA%/VisualVideoTask/logs`。升级、卸载不会主动清理这个用户数据目录，也不会处理已绑定旧项目的数据。

安装包未做商业代码签名，Windows可能显示未知发布者。发布提供SHA256校验值。软件模拟验收不代表每台电脑的设备、驱动、物理触发和音视频时延已测；正式采集前仍需真实设备短测。

## 构建

先在干净源码运行安装器建立 `.venv`，然后执行：

```powershell
.\.venv\Scripts\python.exe scripts/build_windows_release.py --iscc 'C:/path/to/ISCC.exe'
```

构建脚本按源码白名单复制代码，再打包完整独立Python和依赖，编译原生Windows启动器，运行打包后依赖自检，最后用Inno Setup生成EXE。禁止把开发目录data、正式视频、日志、旧环境或账户配置加入安装包。
