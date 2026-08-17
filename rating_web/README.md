# Image B rating Web

该目录是 Session 1 纯行为评分的 jsPsych Web 入口。图片集、被试固定清单、Block、随机顺序、练习、时序、四道评分题、默认值、F/J/空格操作、逐题不限时、每试次保存和中断恢复均沿用现有 PsychoPy 逻辑；原 PsychoPy 文件未修改。

## 构建

```powershell
Set-Location D:\QW_FILE\visual-video-task\rating_web
cmd /c npm install
cmd /c npm run build
```

## 运行

```powershell
python server.py
```

浏览器打开 `http://127.0.0.1:8000`。数据继续写入项目现有的 `records_storage/<subject>/<timestamp>/session_01`，并可被原 PsychoPy EEG Session 2–6 复用。
