# 2026年9月14日仓库清理与汇报说明

本次清理面向 GitHub 源码发布，不删除本地历史文件、普通或情绪视频、环境和被试数据。
新实验仍使用45组 Emotion EEG v1；旧17组、34组和2779题版本的入口、清单、题库与恢复代码保留。

## 从发布源码移除的文件

| 文件 | 原因与替代 |
|---|---|
| docs/CONFIGURATION.md | 仅描述旧配置；当前配置及旧协议分别见 EMOTION_EEG_PROTOCOL.zh-CN.md 与 OPERATOR_MANUAL.zh-CN.md |
| docs/DATA_MODEL.md | 重复旧数据说明；新旧主试手册保留数据路径及恢复规则 |
| docs/EXPERIMENT_FLOW.md | 旧流程且混用17与34的Session范围；以两版汇报说明及主试手册为准 |
| docs/IMPLEMENTATION.md | 被集成审计、完整协议和实现维护记录替代 |
| docs/INSTRUCTION.md | 未区分协议的旧开场说明，容易误认为新版不评分 |
| docs/视频EEG_实验说明.docx | 用明确标注34组与45组的新Word说明替代 |
| docs/视频EEG_详细操作说明.docx | 保留持续维护的Markdown操作手册，新Word供汇报与口播 |
| scripts/export_manual_docx.py | 旧简易导出器会重新生成上述过时文件 |
| video_eeg/utils/preprocessing.py | 无调用的旧实时预处理辅助模块；当前连续EEG采集不使用它 |
| video_eeg/utils/session_store.py | 无调用的旧浏览器会话状态辅助模块；不是当前session_state恢复实现 |
| video_eeg/utils/stream_writer.py | 无调用的旧预测窗口写出器；不是当前连续EEG记录器 |
| SOURCE_MANIFEST.json | Git中静态副本会随后续提交过时；build_release.py在每次打包时重新生成准确校验表 |

前三个旧辅助模块经运行代码、脚本和测试引用检索确认未使用。移除不会改变当前EEG预处理或存储行为。
发布白名单排除以上本地历史副本，避免以后重新混入发布包；离线情绪更新打包器按同一白名单选取Python文件。
Git历史仍可追溯这些文件。审计、材料校验、测试、设备支持、安装脚本和历史被试兼容内容不按“非入口文件”简单删除。

## 汇报材料

- [34组视频 EEG 合并说明](reports/视频EEG_34组_被试与主试说明.docx)及[在线版](reports/视频EEG_34组_被试与主试说明.md)。
- [45组融合情绪评分合并说明](reports/视频EEG_45组融合情绪评分_被试与主试说明.docx)及[在线版](reports/视频EEG_45组融合情绪评分_被试与主试说明.md)。

参考用户提供的三个合并版Word文档的组织方式：被试阅读、主试参数、标准化口播、现场异常与结束核对。
参考项目链接为 [图片EEG](https://github.com/Omni-Intel/THINGS-EEG2-Extended)、
[情绪图片评分](https://github.com/Omni-Intel/Affective-Picture-Rating-Paradigm)、
[情绪视频评分](https://github.com/Omni-Intel/video_rating)。后两项目当前API不可访问，使用用户提供的文档。
没有复制或公开第三方原始Word文件，也没有把参考项目的五级鼠标评分或双Esc规则写入本项目。

## 发布验证

清理后建立独立的白名单源码副本，副本不带正式材料、环境或被试数据，验证时使用本机既有健康Python环境。
自动测试结果：79 passed，2 skipped；跳过的是要求本地正式材料的检查。
实际PsychoPy窗口和模拟EEG检查全部通过：完整4视频及6页评分、视频中止续跑、效价页中止续跑、
唤醒页中止续跑、S重排，以及F长休息继续，共8个运行场景；均核验EEG样本、事件和评分写出。
独立源码成功生成44文件离线更新包，验证清理后打包器仍可使用。
两份Word分别3页与4页，经逐页渲染检查。Windows工作区文档运行时未捆绑LibreOffice，
使用本机WPS转换PDF，再通过文档技能render_docx.py与运行时Poppler渲染检查；中间文件不发布。
安装脚本与依赖版本未改，本次不声称重新完成全新机器联网安装；既往首次安装记录保留。
真实BrainCo、物理显示/声学时延和实验室各电脑验收仍需现场完成。

README保留安装→独立Demo→两套材料→材料校验→真实硬件检查→新正式入口的顺序。
仅下载代码可运行合成Demo；正式实验仍须取得普通母库和最终3138个情绪视频。
