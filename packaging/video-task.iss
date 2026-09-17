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
UsePreviousAppDir=yes
[Languages]
Name: chinesesimplified; MessagesFile: ChineseSimplified.isl
[Tasks]
Name: desktopicon; Description: 创建桌面快捷方式; GroupDescription: 快捷方式：
[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{autoprograms}\视频EEG总范式"; Filename: "{app}\VisualVideoTask.exe"
Name: "{autoprograms}\视频EEG设置（绑定旧v1）"; Filename: "{app}\VisualVideoTask.exe"; Parameters: --settings
Name: "{autodesktop}\视频EEG总范式"; Filename: "{app}\VisualVideoTask.exe"; Tasks: desktopicon
[Run]
Filename: "{app}\VisualVideoTask.exe"; Description: 启动视频EEG总范式; Flags: nowait postinstall skipifsilent
[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
  if not WizardSilent then
    Result := MsgBox('安装程序将使用独立目录，不覆盖原v1实验。若正在采集，请先正常保存结束，再切换到新入口。已有被试首次启动请选择绑定原v1目录。', mbInformation, MB_OKCANCEL) = IDOK;
end;
