#ifndef AppVersion
  #error AppVersion required
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\VisualVideoTask"
#endif
[Setup]
AppId={{03BA5555-D850-4B89-80FC-CC5B77EA2780}
AppName=视频EEG总范式
AppVersion={#AppVersion}
AppPublisher=visual-video-task
AppPublisherURL=https://github.com/18yiba/visual-video-task
AppSupportURL=https://github.com/18yiba/visual-video-task/releases
DefaultDirName={localappdata}\Programs\VisualVideoTask
DefaultGroupName=视频EEG总范式
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
SetupIconFile=app.ico
UninstallDisplayIcon={app}\VisualVideoTask.exe
OutputDir=..\dist
OutputBaseFilename=VisualVideoTask-Setup-Windows-x64
CloseApplications=no
AppMutex=VisualVideoTask.Desktop
RestartApplications=no
UsePreviousAppDir=no
DisableDirPage=yes
[Languages]
Name: chinesesimplified; MessagesFile: ChineseSimplified.isl
[Tasks]
Name: desktopicon; Description: 创建桌面快捷方式; GroupDescription: 快捷方式：
[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{autoprograms}\视频EEG总范式"; Filename: "{app}\VisualVideoTask.exe"
Name: "{autoprograms}\视频EEG设置（迁移到本机）"; Filename: "{app}\VisualVideoTask.exe"; Parameters: --settings
Name: "{autodesktop}\视频EEG总范式"; Filename: "{app}\VisualVideoTask.exe"; Tasks: desktopicon
Name: "{autoprograms}\视频EEG文件盘点"; Filename: "{app}\VisualVideoTask.exe"; Parameters: --audit
Name: "{autoprograms}\视频EEG归档缓存"; Filename: "{app}\VisualVideoTask.exe"; Parameters: --archive-caches
Name: "{autoprograms}\视频EEG检查硬盘占用"; Filename: "{app}\VisualVideoTask.exe"; Parameters: --drive-report
[Run]
Filename: "{app}\VisualVideoTask.exe"; Description: 启动视频EEG总范式; Flags: nowait postinstall skipifsilent
[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
  if not WizardSilent then
    Result := MsgBox('请先正常保存并关闭正在运行的采集，再安装。已有安装版会保留本机设置和数据，请更新后用原被试编号及Session续跑，无需重复迁移。首次从旧v1部署才需要进行迁移设置；原数据保留。', mbInformation, MB_OKCANCEL) = IDOK;
end;
