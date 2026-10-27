param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$downloadRoot = $null
$downloadUrl = 'https://eterlogic.com/downloads/SetupVSPE_64_1.5.8.489.zip'
$expectedMsiHash = 'C6B6D46393B97C3C34430E400F1AD2370EAB41B66563BBD16D33D144348886B2'

function Find-Vspe {
    $candidates = @((Join-Path $env:ProgramFiles 'Eterlogic Software\Virtual Serial Ports Emulator (x64)\VSPEmulator.exe'))
    foreach ($key in @('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
                       'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*')) {
        Get-ItemProperty $key -ErrorAction SilentlyContinue | Where-Object {
            $_.DisplayName -like '*Virtual Serial Ports Emulator*' -and $_.InstallLocation
        } | ForEach-Object { $candidates += Join-Path $_.InstallLocation 'VSPEmulator.exe' }
    }
    foreach ($path in $candidates) {
        if (Test-Path -LiteralPath $path -PathType Leaf) { return $path }
    }
    return $null
}

try {
    $vspe = Find-Vspe
    Write-Host ('已安装 VSPE：' + [bool]$vspe)
    $ports = @([System.IO.Ports.SerialPort]::GetPortNames() | Sort-Object)
    Write-Host ('当前系统端口：' + ($ports -join ', '))
    Write-Host '端口存在不代表可用、已正确配对或脑电设备已连接。'
    if ($CheckOnly) {
        if (-not $vspe) {
            Write-Warning '未找到 VSPE。运行 setup_virtual_serial.bat 可从 Eterlogic 官方站点下载并安装。'
            exit 1
        }
        exit 0
    }

    if (-not $vspe) {
        $downloadRoot = Join-Path ([IO.Path]::GetTempPath()) ('visual-video-vspe-' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $downloadRoot | Out-Null
        $archivePath = Join-Path $downloadRoot 'SetupVSPE_64.zip'
        $installer = Join-Path $downloadRoot 'SetupVSPE_64.msi'
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Write-Host ('从 Eterlogic 官方站点下载 VSPE x64 1.5.8.489：' + $downloadUrl)
        Invoke-WebRequest -UseBasicParsing -Uri $downloadUrl -OutFile $archivePath

        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $archive = [IO.Compression.ZipFile]::OpenRead($archivePath)
        try {
            $matches = @($archive.Entries | Where-Object { $_.Name -eq 'SetupVSPE_64.msi' })
            if ($matches.Count -ne 1) { throw '官方 ZIP 中没有唯一的 SetupVSPE_64.msi。' }
            $inputStream = $matches[0].Open()
            try {
                $outputStream = [IO.File]::Open($installer, [IO.FileMode]::CreateNew,
                    [IO.FileAccess]::Write, [IO.FileShare]::None)
                try { $inputStream.CopyTo($outputStream) }
                finally { $outputStream.Dispose() }
            }
            finally { $inputStream.Dispose() }
        }
        finally { $archive.Dispose() }

        if ((Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash -ne $expectedMsiHash) {
            throw 'VSPE 官方安装包 SHA256 校验失败，未启动安装。'
        }
        $signature = Get-AuthenticodeSignature -LiteralPath $installer
        if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'ETERLOGIC SOFTWARE') {
            throw '无法验证 VSPE 官方数字签名，未启动安装。'
        }
        Write-Host 'VSPE 安装包 SHA256 和 Eterlogic 数字签名校验通过。'
        Write-Host 'Eterlogic 标注 x64 版本需要许可证；请在安装向导中阅读并接受其许可条款。'
        Write-Host '即将打开 Eterlogic 官方安装向导；如出现管理员权限提示，请确认。'
        $install = Start-Process msiexec.exe -ArgumentList @('/i', ('"' + $installer + '"'), '/norestart') -Wait -PassThru
        if ($install.ExitCode -eq 3010) {
            Write-Host '驱动需要重启电脑。保存其他工作并重启后，再运行 setup_virtual_serial.bat。'
            exit 3010
        }
        if ($install.ExitCode -ne 0) { throw ('VSPE 安装未完成，返回码：' + $install.ExitCode) }
        $vspe = Find-Vspe
        if (-not $vspe) { throw '未找到 VSPE，请检查安装结果后重试。' }
    }
    if (-not (Get-Process VSPEmulator -ErrorAction SilentlyContinue)) {
        Start-Process -FilePath $vspe | Out-Null
    }
    Write-Host 'VSPE 已打开；已运行时保留原有端口配置。'
    Write-Host '1. 在 VSPE 创建 Pair，选择两个空闲 COM 编号并启动。已有可用 Pair 时直接使用。'
    Write-Host '2. EmotivPRO 的 Serial port marking 选择接收端，设置 115200 / 8 / None / 1 / None，点击 Start。'
    Write-Host '3. 双击 run_emotion_v3.bat，点击“选择 / 检查 Trigger 发送端”，选择 Pair 的另一端。'
    Write-Host '4. 在 EmotivPRO 确认波形并开始录制，再启动范式。'
    Write-Host '未注册版不支持加载已保存的配置，重启后可能需要重新手动创建 Pair。'
    $guide = Join-Path $project '虚拟串口使用说明.txt'
    if (Test-Path -LiteralPath $guide -PathType Leaf) {
        Start-Process notepad.exe -ArgumentList ('"' + $guide + '"') | Out-Null
    }
    exit 0
} catch {
    Write-Host ('虚拟串口准备未完成：' + $_.Exception.Message) -ForegroundColor Red
    exit 1
} finally {
    if ($downloadRoot -and (Test-Path -LiteralPath $downloadRoot -PathType Container)) {
        Remove-Item -LiteralPath $downloadRoot -Recurse -Force
    }
}
