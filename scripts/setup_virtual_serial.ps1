param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot

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
    $installer = Join-Path $project 'dependencies\vspe\SetupVSPE_64.msi'
    $expectedHash = 'C6B6D46393B97C3C34430E400F1AD2370EAB41B66563BBD16D33D144348886B2'
    if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) {
        throw '缺少 dependencies\vspe\SetupVSPE_64.msi，请重新复制完整文件夹。'
    }
    if ((Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash -ne $expectedHash) {
        throw 'VSPE 安装包校验失败，请重新复制完整文件夹。'
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $installer
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'ETERLOGIC SOFTWARE') {
        throw '无法验证 VSPE 官方数字签名，未启动安装。'
    }
    $vspe = Find-Vspe
    Write-Host '随包 VSPE 1.5.8.489 安装包：SHA256 和官方签名校验通过。'
    Write-Host ('已安装 VSPE：' + [bool]$vspe)
    $ports = @([System.IO.Ports.SerialPort]::GetPortNames() | Sort-Object)
    Write-Host ('当前系统端口：' + ($ports -join ', '))
    Write-Host '端口存在不代表可用、已正确配对或脑电设备已连接。'
    if ($CheckOnly) { exit 0 }

    if (-not $vspe) {
        Write-Host '将打开随包官方安装向导；按提示接受许可并完成安装。若出现管理员权限提示，请确认。'
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
}
