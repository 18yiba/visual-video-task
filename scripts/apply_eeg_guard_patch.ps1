param([string]$TargetRoot, [switch]$NonInteractive)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
if (-not $TargetRoot) {
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = '选择实际运行的程序目录，里面应有 video_eeg 文件夹。已装离线包的请选择该更新包目录。'
    if ($dialog.ShowDialog() -ne 'OK') { exit 1 }
    $TargetRoot = $dialog.SelectedPath
}
$target = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $TargetRoot).Path).TrimEnd('\')
if (-not (Test-Path -LiteralPath (Join-Path $target 'video_eeg\experiment\video_runner.py'))) { throw '所选位置不是视频EEG程序目录。' }
if (-not $NonInteractive) {
    if ([Windows.Forms.MessageBox]::Show('确认已经退出本机实验程序并保存数据？本补丁只更新Python源码，会先备份；不切换Session或评分协议。','EEG断流保护补丁','YesNo','Warning') -ne 'Yes') { exit 1 }
}
$busy = Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(w)?\.exe$' -and $_.CommandLine -and $_.CommandLine.IndexOf($target,[StringComparison]::OrdinalIgnoreCase) -ge 0 }
if ($busy) { throw '所选目录仍有Python程序运行，请先正常退出实验，再安装。' }
$entries = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'PATCH_FILES.json') -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($entry in $entries) {
    if ($entry.path -notmatch '^video_eeg/.*\.py$' -or $entry.path.Contains('..')) { throw '补丁文件路径无效。' }
    $destination = [IO.Path]::GetFullPath((Join-Path $target $entry.path))
    if (-not $destination.StartsWith($target+'\',[StringComparison]::OrdinalIgnoreCase)) { throw '目标路径越界。' }
    $ancestor = Split-Path -Parent $destination
    while ($ancestor.Length -ge $target.Length) {
        if ((Test-Path -LiteralPath $ancestor) -and ((Get-Item -LiteralPath $ancestor).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw '程序路径包含链接/junction，请选择实际目录。' }
        $ancestor = Split-Path -Parent $ancestor
    }
    $source = Join-Path (Join-Path $PSScriptRoot 'payload') $entry.path
    if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne $entry.sha256) { throw ('补丁校验失败：'+$entry.path) }
}
$backup = Join-Path $target ('runtime_patch_backups\eeg_guard_'+(Get-Date -Format 'yyyyMMdd_HHmmss_ffff'))
New-Item -ItemType Directory -Path $backup | Out-Null
$existing = @()
foreach ($entry in $entries) {
    $destination = Join-Path $target $entry.path
    if (Test-Path -LiteralPath $destination) {
        if ((Get-Item -LiteralPath $destination).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw '源码文件为链接，停止。' }
        $saved = Join-Path $backup $entry.path
        New-Item -ItemType Directory -Path (Split-Path -Parent $saved) -Force | Out-Null
        Copy-Item -LiteralPath $destination -Destination $saved
        $existing += $entry.path
    }
}
$offlineManifest = Join-Path $target 'OFFLINE_FILES.json'
if (Test-Path -LiteralPath $offlineManifest) { Copy-Item -LiteralPath $offlineManifest -Destination (Join-Path $backup 'OFFLINE_FILES.json') }
try {
    foreach ($entry in $entries) {
        $destination = Join-Path $target $entry.path
        New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
        Copy-Item -LiteralPath (Join-Path (Join-Path $PSScriptRoot 'payload') $entry.path) -Destination $destination -Force
        if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash -ne $entry.sha256) { throw '写入后校验失败。' }
    }
    if (Test-Path -LiteralPath $offlineManifest) {
        $old = Get-Content -LiteralPath $offlineManifest -Raw -Encoding UTF8 | ConvertFrom-Json
        $names = @($entries | ForEach-Object { $_.path })
        $updated = @($old | Where-Object { $_.path -notin $names }) + $entries
        [IO.File]::WriteAllText($offlineManifest,($updated | ConvertTo-Json -Depth 8),(New-Object Text.UTF8Encoding($false)))
    }
} catch {
    foreach ($relative in $existing) { Copy-Item -LiteralPath (Join-Path $backup $relative) -Destination (Join-Path $target $relative) -Force }
    if (Test-Path -LiteralPath (Join-Path $backup 'OFFLINE_FILES.json')) { Copy-Item -LiteralPath (Join-Path $backup 'OFFLINE_FILES.json') -Destination $offlineManifest -Force }
    throw
}
@{patch='eeg_guard_20260915';target=$target;backup=$backup;replaced_files=$existing;files=$entries} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $backup 'PATCH_RECEIPT.json') -Encoding UTF8
Write-Host ('安装成功。源码备份：'+$backup)
Write-Host '仍使用原入口和原编号继续原协议。先运行Demo，再由主试做无被试的真实设备短测。'
Write-Host '本补丁不修复已经缺失的脑电；也不把旧17/34组切换成情绪协议。'
