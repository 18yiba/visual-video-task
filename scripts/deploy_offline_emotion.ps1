param([string]$OldProject, [switch]$NoOpen)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
$packageName = '_video_eeg_emotion_v1_update'
$sourcePackage = Join-Path $PSScriptRoot $packageName
$sourceVideos = Join-Path (Split-Path -Parent $PSScriptRoot) 'video_materials\formal_v1\emotion_video\selected'
$deployLog = Join-Path $PSScriptRoot 'deployment_copy.log'
try {
    if (-not $OldProject) {
        $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
        $dialog.Description = '选择实验室原17组程序目录：里面应有 video_eeg、原启动BAT，通常还有 .venv。'
        $dialog.ShowNewFolderButton = $false
        if ($dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { exit 0 }
        $OldProject = $dialog.SelectedPath
    }
    $oldRoot = (Resolve-Path -LiteralPath $OldProject).Path
    if (-not (Test-Path -LiteralPath (Join-Path $oldRoot 'video_eeg\config\video_config.yaml'))) {
        throw '没有找到旧配置，请选择真正的旧程序目录，不是桌面或快捷方式目录。'
    }
    $pythonPath = Join-Path $oldRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $pythonPath)) {
        $pythonPath = Join-Path (Split-Path -Parent $oldRoot) '.venv\Scripts\python.exe'
    }
    if (-not (Test-Path -LiteralPath $pythonPath)) { throw '没有找到原Python环境。请保留旧程序，带回报告处理。' }
    $manifest = Join-Path $sourcePackage 'OFFLINE_FILES.json'
    if (-not (Test-Path -LiteralPath $manifest)) { throw '硬盘更新文件夹缺失，请带上完整交付目录。' }
    $packageHash = (Get-FileHash -LiteralPath $manifest -Algorithm SHA256).Hash
    foreach ($entry in (Get-Content -LiteralPath $manifest -Raw -Encoding UTF8 | ConvertFrom-Json)) {
        $file = Join-Path $sourcePackage $entry.path
        if (-not (Test-Path -LiteralPath $file) -or (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ne $entry.sha256) {
            throw ('硬盘代码包校验失败：' + $entry.path)
        }
    }
    $sourceFiles = @(Get-ChildItem -LiteralPath $sourceVideos -Filter '*.mp4' -File -Recurse)
    if ($sourceFiles.Count -ne 3138) { throw '硬盘selected文件夹不是完整3138个视频，请核对材料路径。' }
    $destination = [System.IO.Path]::GetFullPath((Join-Path $oldRoot $packageName))
    if ((Split-Path -Parent $destination) -ne $oldRoot.TrimEnd('\')) { throw '目标路径验证失败。' }
    $marker = Join-Path $destination 'DEPLOYMENT.json'
    if (Test-Path -LiteralPath $destination) {
        if (-not (Test-Path -LiteralPath $marker)) { throw '已存在同名更新文件夹。不会覆盖，请使用已有入口或让维护人员核对。' }
        $prior = Get-Content -LiteralPath $marker -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($prior.package_sha256 -ne $packageHash) { throw '同名目录是另一个版本，不覆盖。' }
        if ($prior.status -eq 'copied') {
            Write-Host '这台电脑已复制完成，请运行其中的01检查、02Demo、03正式入口。'
            if (-not $NoOpen) { Invoke-Item -LiteralPath $destination }
            exit 0
        }
    } else { New-Item -ItemType Directory -Path $destination | Out-Null }
    @{status='copying'; package_sha256=$packageHash; old_project=$oldRoot} | ConvertTo-Json | Set-Content -LiteralPath $marker -Encoding UTF8
    Write-Host '复制新版代码；旧程序、环境和数据不变……'
    & robocopy $sourcePackage $destination /E /COPY:DAT /DCOPY:T /Z /R:2 /W:1 /MT:8 /NP "/LOG+:$deployLog"
    if ($LASTEXITCODE -ge 8) { throw '代码复制未完成。保留硬盘并重新运行即可继续。' }
    $videoDestination = Join-Path $destination 'emotion_video\selected'
    Write-Host '复制3138个情绪视频（9.87 GB），请勿拔出硬盘……'
    & robocopy $sourceVideos $videoDestination /E /COPY:DAT /DCOPY:T /Z /R:2 /W:1 /MT:8 /NP "/LOG+:$deployLog"
    if ($LASTEXITCODE -ge 8) { throw '视频复制未完成。重新运行可继续，不用删除已复制文件。' }
    foreach ($file in $sourceFiles) {
        $relative = $file.FullName.Substring($sourceVideos.TrimEnd('\').Length).TrimStart('\')
        $copied = Join-Path $videoDestination $relative
        if (-not (Test-Path -LiteralPath $copied) -or (Get-Item -LiteralPath $copied).Length -ne $file.Length) {
            throw '复制大小核对失败，请重新运行后再进行完整材料检查。'
        }
    }
    @{status='copied'; package_sha256=$packageHash; old_project=$oldRoot; video_count=3138; full_sha256_check='run 01_先检查.bat'} | ConvertTo-Json | Set-Content -LiteralPath $marker -Encoding UTF8
    Write-Host '复制完成！接下来：01_先检查.bat → 02_Demo.bat → 真实设备短测 → 03_正式45组.bat。'
    Write-Host '旧17组被试仍用原入口。完整检查通过后再开始新正式实验。'
    if (-not $NoOpen) { Invoke-Item -LiteralPath $destination }
} catch {
    Write-Host ('部署停止：' + $_.Exception.Message) -ForegroundColor Red
    Write-Host '未替换旧程序或旧数据。保留本窗口和deployment_copy.log用于排查。'
    exit 1
}
