# 情绪评分的维度和量表依据

本协议测量观看者当时的主观体验：Valence（愉快—不愉快）和 Arousal（平静—激活），
两页固定先后顺序，均采用 1–9 整数、键盘选择、不限时。没有正确答案或准确率。
视频库的类别只用于刺激分组；被试自己的评分不由库标签推断。

Russell 的情绪环形模型以愉快程度和激活程度两个维度组织情绪：
兴奋与放松可以同属正效价，但激活程度不同。因此本库将 Excitation、Relaxation 映射到 positive；
Neutral 映射到 neutral；Fear、Sad、Tension 映射到 negative。
这只是本协议采用的类别映射，不声称每位被试必然体验到相同的效价。
原始字段保留 Sad 和 Excitation 的真实拼写，不改成 Sadness 或 Excitement。

- Russell, J. A. (1980). A circumplex model of affect. *Journal of Personality and Social Psychology*, 39(6), 1161–1178.
  [DOI](https://doi.org/10.1037/h0077714) · [论文全文](https://pdodds.w3.uvm.edu/research/papers/others/1980/russell1980a.pdf)。
- Bradley, M. M., & Lang, P. J. (1994). Measuring emotion: the Self-Assessment Manikin and the Semantic Differential.
  *Journal of Behavior Therapy and Experimental Psychiatry*, 25(1), 49–59.
  [DOI](https://doi.org/10.1016/0005-7916(94)90063-9) · [PubMed 原始摘要](https://pubmed.ncbi.nlm.nih.gov/7962581/)。

Bradley 与 Lang 的 SAM 工作支持将 pleasure、arousal 分开询问。本实现是**文字锚点的九级数字量表**，
借鉴这些维度及分开报告的思路，不复制 SAM 图像，也不将当前中文文字界面声称为已独立验证的 SAM 等价版本。
不使用 dominance，因为本次协议只要求两个维度。中文表述和键盘方式是本实验的操作化选择。

## 页面原文

Valence：**请评价刚才这段视频带给你的主观情绪感受。**

1 非常不愉快；5 中性；9 非常愉快。

Arousal：**请评价刚才这段视频引起的情绪唤醒程度。**

1 非常平静／几乎没有被激活；5 中等；9 非常激动／强烈被激活。

两个页面均显示数字 1–9 及“请按数字键 1–9 作答，答题不限时”。
RT 优先来自在页面 flip 重置的 PsychoPy 键盘时钟；无硬件键盘时间戳的测试适配器采用单调时钟轮询时刻。
事件同时记录按键时间和软件检测时刻。物理显示延迟、声学输出延迟和硬件 marker 延迟仍需实验室测量。

## 旧评分程序的使用范围

参考现有 jsPsych 评分程序的两页顺序、离散选项、无限等待和逐项保存设计。
原程序是五级鼠标选择；本协议按新要求实现九级键盘输入，直接接入 PsychoPy，运行不需要 Node.js。
不复制图片、被试记录或旧项目的个人配置。
