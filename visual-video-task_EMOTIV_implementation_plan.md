# visual-video-task：EMOTIV 多型号同步适配实施规范

> 本文件用于作为后续 AI 修改代码时的长期背景与实施约束。  
> 在执行与 EMOTIV 适配相关的代码修改时，应优先遵循本文件，而不是重新设计整体架构。

## 1. 项目背景

目标仓库：

- GitHub: https://github.com/18yiba/visual-video-task
- README: https://github.com/18yiba/visual-video-task/blob/master/README.md

该仓库是 Omni-Intelligence 实验范式的草稿框架，主要包含：

- PsychoPy 实验流程与视频刺激呈现；
- EEG 设备采集抽象；
- EEG 连续数据记录；
- marker / trigger 事件同步；
- session 管理；
- 实验状态与健康检查；
- Demo 与正式实验模式。

当前任务不是重写实验范式，而是在**尽可能不影响现有前端与实验逻辑**的前提下，新增一个统一的 EMOTIV 后端，使 EPOC X、Insight、EPOC Flex、Flex 2 等设备能够通过修改参数完成切换。

## 2. 总体目标

实现一个统一的：

```text
Cortex-compatible EMOTIV backend
```

而不是分别实现：

```text
EpocXAcquirer
InsightAcquirer
FlexAcquirer
Flex2Acquirer
```

目标结构：

```text
PsychoPy / experiment frontend
            │
            │ existing parameters / config entry
            ▼
      EegSessionManager
            │
            ▼
      AbstractAcquirer
            │
            ▼
       EmotivAcquirer
            │
     ┌──────┼────────┐
     ▼      ▼        ▼
CortexClient ClockSync StreamParser
     │
     ▼
 EMOTIV Cortex
     │
     ▼
 EPOC X / Insight / Flex / Flex 2
```

设备差异应尽量被限制在：

```text
device profile
configuration
electrode mapping
runtime metadata validation
```

而不是散布在整个实验代码中。

## 3. 核心实施原则

### 3.1 最大限度保持现有前端不变

除非确有必要，不修改：

- PsychoPy 页面；
- 视频呈现逻辑；
- 行为评分界面；
- 实验流程；
- session 划分；
- UI 布局；
- 视觉样式；
- 实验操作习惯。

优先通过：

```text
config parameter
CLI parameter
factory entry
existing device abstraction
existing marker abstraction
```

接入 EMOTIV。

如果现有函数可以通过增加一个参数完成扩展，则优先增加参数入口，不重新设计前端调用流程。

### 3.2 新代码尽量集中在一个大文件夹内

EMOTIV 相关代码应尽量集中管理，例如：

```text
video_eeg/
└── devices/
    └── emotiv/
        ├── __init__.py
        ├── acquirer.py
        ├── cortex_client.py
        ├── profiles.py
        ├── stream_parser.py
        ├── buffer.py
        ├── clock_sync.py
        ├── marker_backend.py
        ├── record_manager.py
        ├── config.py
        └── errors.py
```

如现有目录结构不允许完全采用以上形式，可根据仓库实际结构微调，但必须遵守：

> EMOTIV 特有实现集中放在 `emotiv/` 大文件夹内，其他模块只增加必要的参数入口、factory 注册和少量调用代码。

不要把大量：

```python
if device_type == "emotiv":
    ...
```

散落在实验流程、UI、storage、runner 等多个文件中。

## 4. 设备抽象

优先复用现有：

```text
AbstractAcquirer
AcquirerFactory
EegSessionManager
SessionRecorder
MarkerBackend
```

新增：

```text
EmotivAcquirer
```

并注册：

```text
device_type = emotiv
```

理想调用：

```yaml
device:
  type: emotiv

  emotiv:
    model: auto
```

或：

```yaml
device:
  type: emotiv

  emotiv:
    model: epoc_x
```

实验层不应该直接处理 Cortex WebSocket、认证、EEG packet、Flex mapping 等实现细节。

## 5. 支持的 EMOTIV 型号

首批目标型号：

```text
EPOC X
Insight
EPOC Flex
Flex 2
```

统一使用一个：

```text
EmotivAcquirer
```

不要复制四套采集代码。

推荐 profile：

```python
DEVICE_PROFILES = {
    "auto": ...,
    "epoc_x": ...,
    "insight": ...,
    "epoc_flex": ...,
    "flex_2": ...,
}
```

Profile 仅描述设备行为差异，例如：

```text
是否需要 electrode mapping
是否允许自动 mapping
设备 family
特殊初始化行为
```

不要把 EEG 数据 slicing、采样率、通道数量等逻辑写死到 profile 中。

## 6. 运行时 metadata 优先

EEG 的真实：

```text
sampling rate
channel labels
channel count
stream labels
auxiliary fields
```

应尽可能从 Cortex 实际返回值中读取。

不要写死：

```python
if model == "epoc_x":
    sfreq = ...
    channels = [...]
```

优先：

```text
Cortex
  ↓
query headset / settings / subscribe labels
  ↓
runtime metadata
  ↓
AcquirerMetadata
```

Profile 是行为配置，不是设备规格数据库。

## 7. 自动识别模式

默认建议支持：

```yaml
model: auto
```

流程：

```text
queryHeadsets
    ↓
select headset
    ↓
detect model/family
    ↓
resolve DeviceProfile
```

同时必须支持显式模式：

```yaml
model: epoc_x
```

若配置型号和实际检测型号不一致：

```text
configured = epoc_x
detected = insight
```

应直接报错并停止。

禁止自动替用户修改型号或静默继续。

## 8. 多设备选择

支持：

```yaml
headset_id: auto
```

如果只发现一个合法 headset，可自动选择。

如果发现多个设备，而没有指定 `headset_id`，不要猜测。

应直接显示候选设备并要求明确选择。

## 9. Flex / Flex 2 特殊处理

Flex 系列需要支持 electrode mapping。

Mapping 应属于：

```text
experiment configuration
```

而不是硬编码。

推荐：

```yaml
device:
  type: emotiv

  emotiv:
    model: epoc_flex
    mapping_profile: visual_32ch
```

目录示例：

```text
config/
└── emotiv/
    └── mappings/
        ├── visual_32ch.yaml
        ├── motor_32ch.yaml
        └── standard_10_20.yaml
```

实际 mapping schema 必须根据当前 Cortex API 与设备要求实现。

如果 API schema、设备返回字段或 mapping 格式不确定：

> 不进行猜测，不自行构造字段，停止实现并明确指出缺失信息。

## 10. CortexClient

统一封装 Cortex JSON-RPC / WebSocket。

负责：

```text
open websocket
requestAccess
authorize
queryHeadsets
controlDevice
createSession
subscribe
unsubscribe
createRecord
stopRecord
injectMarker
syncWithHeadsetClock
closeSession
disconnect
```

实验层禁止直接发送 Cortex JSON-RPC。

所有 Cortex 调用集中在：

```text
emotiv/cortex_client.py
```

## 11. EmotivAcquirer 职责

`EmotivAcquirer` 只负责 EEG acquisition：

```text
connect
initialize
subscribe EEG
receive EEG packets
parse EEG
buffer EEG
get_new_samples
get_chunk
metadata
stop
```

不要让 `EmotivAcquirer` 承担所有：

```text
record export
marker management
clock conversion
UI state
experiment logic
```

这些功能应分别委托给专用模块。

## 12. StreamParser 必须动态解析

不要写：

```python
eeg = packet["eeg"][2:16]
```

不要依赖固定 index。

应根据 Cortex subscribe 返回的 labels 动态确定：

```text
EEG channels
COUNTER
INTERPOLATED
RAW_CQ
MARKER_HARDWARE
MARKERS
other auxiliary fields
```

建立：

```text
channel_name -> packet index
```

映射。

不同型号共用同一个 parser。

## 13. EEG timestamp

Cortex EEG packet 自带 timestamp 时：

> 以 Cortex 原始 timestamp 作为 EEG sample 的主要时间信息。

不要使用：

```python
time.time()
```

替代 headset / Cortex timestamp。

`get_new_samples()` 应尽量返回：

```text
samples
timestamps
```

并保持现有 `AbstractAcquirer` 数据契约。

## 14. 时间同步

同步是该适配任务的核心，而不仅仅是“能够收到 EEG”。

使用 Cortex：

```text
syncWithHeadsetClock
```

建立：

```text
Python monotonic clock
        ↕
Cortex headset clock
```

关系。

理想：

```text
cortex_time ≈ monotonic_time + adjustment
```

设备连接完成后同步。

断开并重新连接后重新同步。

不要默认旧 adjustment 在重连后仍有效。

## 15. Marker 设计

新增统一：

```text
EmotivCortexMarkerBackend
```

所有 EMOTIV 型号共用 Cortex marker。

事件流程：

```text
PsychoPy event
    ↓
monotonic timestamp
    ↓
clock adjustment
    ↓
Cortex timestamp
    ↓
injectMarker
```

继续保留仓库原有：

```text
events.json
sample_index
relative_time_sec
```

形成双记录。

## 16. 双 marker / 多 backend

如果现有 `CompositeMarkerBackend` 可以复用，则允许：

```text
Emotiv Cortex marker
+
LSL marker
```

同时写出。

不要修改现有实验事件定义。

例如：

```text
VIDEO_ONSET
VIDEO_OFFSET
VALENCE
AROUSAL
...
```

继续由原实验层产生。

## 17. 不以 sample_count 作为唯一同步依据

现有：

```text
event occurs
  ↓
current sample_count
  ↓
sample_index
```

可继续保留用于本地数据兼容。

但 EMOTIV 无线链路可能存在：

```text
headset
→ Cortex
→ WebSocket buffer
→ Python
```

延迟。

因此：

> EMOTIV 的高精度同步必须优先依赖 EEG timestamp + Cortex marker timestamp，而不是仅依赖 Python 当前已收到多少样本。

## 18. Cortex Record

推荐开发阶段同时启用：

```text
visual-video-task local record
+
Cortex native record
```

用于交叉验证。

流程：

```text
createSession
    ↓
sync clock
    ↓
createRecord
    ↓
subscribe EEG
    ↓
experiment
    ↓
stopRecord
```

开发阶段需要能够对比：

```text
local EEG
vs
Cortex exported EEG
```

以及：

```text
local events
vs
Cortex markers
```

稳定后是否长期双记录可再决定。

## 19. Sampling rate 原则

禁止为了适配现有配置而：

```text
128 Hz -> fake 1000 Hz
256 Hz -> fake 1000 Hz
```

禁止静默 resample。

真实采样率应来自 Cortex。

如果实验配置中存在：

```yaml
expected_sfreq: 256
```

则执行：

```text
actual_sfreq == expected_sfreq
```

校验。

不一致直接报错。

## 20. Channel validation

允许配置：

```yaml
validation:
  expected_sfreq: null
  expected_channels: null
```

表示接受设备实际配置。

正式实验可指定：

```yaml
validation:
  expected_sfreq: 256
  expected_channels:
    - ...
```

若不匹配则报错。

不要自动删除、多加、重排通道以掩盖问题。

## 21. 数据质量字段

若 Cortex 提供：

```text
COUNTER
INTERPOLATED
RAW_CQ
MARKER_HARDWARE
```

不要直接丢弃。

至少保存为：

```text
auxiliary data
metadata
health logs
```

第一阶段可记录：

```text
interpolated ratio
counter continuity
contact quality
```

但不要在未经实验验证的情况下自行定义：

```text
bad signal threshold
automatic experiment stop threshold
```

## 22. Health Monitor

保持现有：

```text
startup no sample timeout
continuous no sample timeout
```

策略。

EMOTIV 可扩展：

```text
Level 1: transport health
Level 2: signal/data quality
```

第一阶段：

```text
Level 1
```

可作为硬错误。

```text
Level 2
```

优先记录，不自动停止实验。

## 23. 错误处理原则

本项目明确减少非必要防御性代码。

### 禁止

禁止：

```text
silent fallback
dummy EEG
fake sample
zero padding to hide loss
automatic device substitution
automatic sampling-rate correction
catch Exception: pass
silent reconnect
silent config rewrite
fabricated metadata
```

禁止为了“让程序继续运行”掩盖真实错误。

### 允许

只有确实属于正常业务行为时才使用：

```text
明确的 retry
用户主动允许的 reconnect
可验证的 timeout
清晰的 validation
明确的 recoverable state
```

### 错误应从源头暴露

例如没有 EEG sample，不要直接生成空数据补齐。

应检查：

```text
headset connection
Cortex session
subscription
WebSocket
packet parser
buffer
```

例如 `sfreq mismatch`，不要自动 resample。

应输出：

```text
configured sfreq
detected sfreq
headset
session
```

## 24. 未知条件处理

开发过程中若遇到以下情况：

```text
API schema 不确定
Cortex 返回字段不确定
Flex mapping schema 不确定
设备能力无法从官方文档确认
现有仓库调用关系无法确定
一个修改可能改变实验行为但影响未知
```

禁止自行假设。

应：

1. 停止该部分实现；
2. 明确指出未知条件；
3. 给出当前已确认信息；
4. 提出需要用户补充或确认的具体问题。

不要用猜测完成代码。

## 25. 配置建议

示例：

```yaml
device:
  type: emotiv

  emotiv:
    model: auto
    headset_id: auto

    streams:
      - eeg

    record:
      enabled: true

    markers:
      enabled: true

    clock_sync:
      enabled: true

    mapping_profile: null

    validation:
      expected_sfreq: null
      expected_channels: null
```

EPOC X：

```yaml
device:
  type: emotiv

  emotiv:
    model: epoc_x
    headset_id: auto
```

Insight：

```yaml
device:
  type: emotiv

  emotiv:
    model: insight
    headset_id: auto
```

Flex：

```yaml
device:
  type: emotiv

  emotiv:
    model: epoc_flex
    headset_id: auto
    mapping_profile: visual_32ch
```

## 26. Credential 管理

禁止把：

```text
client_id
client_secret
license credentials
tokens
```

直接提交到 Git 仓库。

推荐：

```text
environment variables
local private config
system credential storage
```

公开 YAML 仅包含 credential 的引用或变量名。

## 27. 需要修改的现有代码范围

优先将修改限制在：

```text
device factory
device selection CLI/config
runner parameter entry
preflight/environment check
marker backend registration
dependency declaration
tests
```

不要因为 EMOTIV 新增而重构无关模块。

## 28. 推荐目录

理想：

```text
video_eeg/
├── devices/
│   ├── base.py
│   ├── factory.py
│   └── emotiv/
│       ├── __init__.py
│       ├── acquirer.py
│       ├── cortex_client.py
│       ├── profiles.py
│       ├── stream_parser.py
│       ├── buffer.py
│       ├── clock_sync.py
│       ├── marker_backend.py
│       ├── record_manager.py
│       ├── config.py
│       └── errors.py
│
└── ...
```

如果现有 marker 体系要求 `MarkerBackend` 位于其他目录，可以在原文件增加一个薄入口，但实际 EMOTIV 实现仍放在：

```text
devices/emotiv/
```

中。

例如：

```text
utils/markers.py
    ↓
import EmotivCortexMarkerBackend
```

而不是把完整 Cortex marker 逻辑写进 `utils/markers.py`。

## 29. 实施阶段

### Stage 1：Acquisition

目标：

```text
Cortex authentication
headset discovery
headset selection
session creation
EEG subscription
dynamic labels
runtime metadata
EEG buffer
get_new_samples
stop
```

验收：

```text
连续收到真实 EEG
timestamps 连续
channel 数与 labels 对应
metadata 正确
```

### Stage 2：Clock Sync

实现：

```text
syncWithHeadsetClock
monotonic -> Cortex time
reconnect resync
```

验收：

```text
clock adjustment 可记录
EEG timestamp 和 application timestamp 可比较
```

### Stage 3：Marker

实现：

```text
EmotivCortexMarkerBackend
injectMarker
event code
event label
timestamp conversion
```

验收：

```text
实验事件能够进入 Cortex record
```

### Stage 4：Local + Cortex dual record

同时保存：

```text
continuous_eeg.npy
events.json
metadata.json
Cortex native record
```

比较：

```text
sample count
duration
timestamps
event ordering
marker timing
```

### Stage 5：Multi-model validation

测试：

```text
EPOC X
Insight
EPOC Flex
Flex 2
```

没有实际设备的型号：

> 只实现基于官方 API 可验证的代码路径，不宣称已经完成真实硬件兼容测试。

## 30. 同步验证

不要仅以：

```text
程序没有报错
```

作为同步成功标准。

至少构建：

```text
PsychoPy flip
+
marker
```

周期性 timing test。

如果实验条件允许，使用：

```text
photodiode
TTL
hardware marker
```

作为客观参照。

关注：

```text
latency
jitter
clock drift
marker ordering
packet delay
```

软件 marker 与硬件 marker 的差异必须可量化。

## 31. 异常测试

至少覆盖：

```text
Cortex 未启动
headset 未连接
未授权
license 不支持 EEG
多个 headset
错误型号
sampling rate mismatch
channel mismatch
EEG subscribe 失败
启动后无 sample
运行中断流
WebSocket disconnect
设备断开
设备重连
record 创建失败
marker injection 失败
Flex mapping 错误
Esc 正常退出
异常退出
partial data 保存
```

错误应明确暴露。

## 32. 不要做的事情

不要为了“代码更优雅”而：

```text
重写前端
更换实验框架
重新设计全部 session 逻辑
重新定义现有 marker 编码
大规模重构 storage
修改实验视觉设计
改变行为学问卷逻辑
```

除非该修改是 EMOTIV 适配必须条件，并且能够说明原因。

## 33. 代码风格

优先：

```text
清晰
直接
职责单一
显式错误
少隐藏状态
少 fallback
少自动修复
```

避免：

```text
过度抽象
无必要的 adapter 套 adapter
为潜在未来需求提前设计大量接口
巨大 try/except
重复 wrapper
```

## 34. AI 修改代码时的执行规则

每次修改前：

1. 先确认当前仓库实际代码结构；
2. 阅读目标文件和调用链；
3. 不根据本文件中的示例路径假设仓库一定相同；
4. 在现有设计基础上最小化修改；
5. EMOTIV 新实现优先放入统一 `emotiv/` 文件夹；
6. 原代码只增加必要入口；
7. 修改完成后进行静态检查和最小真实逻辑测试；
8. 不使用 dummy data 伪造通过；
9. 不通过 fallback 掩盖错误；
10. 如果无法验证一个关键条件，直接指出。

## 35. 最终期望结果

最终用户只需要修改参数，例如：

```yaml
device:
  type: emotiv

  emotiv:
    model: epoc_x
```

切换为：

```yaml
device:
  type: emotiv

  emotiv:
    model: insight
```

或者：

```yaml
device:
  type: emotiv

  emotiv:
    model: epoc_flex
    mapping_profile: visual_32ch
```

即可使用不同设备。

实验前端、视频流程和行为学逻辑原则上不需要跟着修改。

## 36. 最终架构要求

```text
Experiment / PsychoPy
        │
        │ minimal parameter entry
        ▼
EegSessionManager
        │
        ├─────────────── MarkerBackend
        │                       │
        │                       ▼
        │             EmotivCortexMarkerBackend
        │
        ▼
AbstractAcquirer
        │
        ▼
EmotivAcquirer
        │
        ├── CortexClient
        ├── DeviceProfile
        ├── StreamParser
        ├── EEGBuffer
        ├── ClockSync
        └── RecordManager
                │
                ▼
            Cortex API
                │
                ▼
      EPOC X / Insight / Flex / Flex 2
```

核心原则：

> **设备型号通过配置与 runtime metadata 管理；设备协议通过统一 Cortex backend 管理；同步通过 Cortex timestamp 与 headset clock sync 管理；EMOTIV 特有代码集中在一个目录；现有实验前端仅增加必要参数入口，不做无关重构。**
