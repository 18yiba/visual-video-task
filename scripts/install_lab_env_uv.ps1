param([switch]$ForceRepair)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Set-Location -LiteralPath $projectRoot
$env:PYTHONUTF8 = '1'
$env:PYTHONNOUSERSITE = '1'
$env:UV_CACHE_DIR = Join-Path $projectRoot '.uv-cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $projectRoot '.runtime\python'
$env:UV_PYTHON_DOWNLOADS = 'automatic'
$env:UV_LINK_MODE = 'copy'
$env:UV_HTTP_TIMEOUT = '120'
$env:UV_HTTP_RETRIES = '3'
Remove-Item Env:UV_NO_MANAGED_PYTHON -ErrorAction SilentlyContinue
$env:APPDATA = Join-Path $projectRoot '.psychopy_appdata'
$env:TEMP = Join-Path $projectRoot '.tmp'
$env:TMP = $env:TEMP
foreach ($dir in @($env:APPDATA, $env:TEMP, (Join-Path $projectRoot 'logs'))) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
}
$log = Join-Path $projectRoot ('logs\install_{0}.log' -f (Get-Date -Format 'yyyyMMdd_HHmmss'))
Start-Transcript -Path $log | Out-Null

function Run-Checked([string]$Executable, [string[]]$Arguments) {
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed (exit $LASTEXITCODE): $Executable $($Arguments -join ' ')" }
}

try {
    $venvPath = Join-Path $projectRoot '.venv'
    $pythonExe = Join-Path $venvPath 'Scripts\python.exe'
    $checker = Join-Path $PSScriptRoot 'check_video_eeg_env.py'
    $healthy = $false
    if ((Test-Path -LiteralPath $pythonExe) -and -not $ForceRepair) {
        & $pythonExe -c 'import sys; assert sys.version_info[:2] == (3,12)'
        if ($LASTEXITCODE -eq 0) {
            & $pythonExe $checker --quiet
            $healthy = ($LASTEXITCODE -eq 0)
        }
    }
    if (-not $healthy) {
        $uvExe = Join-Path $projectRoot 'tools\uv.exe'
        if (-not (Test-Path -LiteralPath $uvExe)) {
            New-Item -ItemType Directory -Path (Split-Path -Parent $uvExe) -Force | Out-Null
            $env:UV_INSTALL_DIR = Split-Path -Parent $uvExe
            $env:UV_NO_MODIFY_PATH = '1'
            $bootstrap = Join-Path $env:TEMP 'install_uv.ps1'
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -UseBasicParsing -Uri 'https://astral.sh/uv/install.ps1' -OutFile $bootstrap
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $bootstrap
            if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $uvExe)) { throw 'uv installation failed' }
        }
        Run-Checked $uvExe @('--version')
        $basePython = [IO.Path]::GetFullPath((Join-Path $projectRoot '..\runtime\python312\python.exe'))
        if (-not (Test-Path -LiteralPath $basePython)) {
            Write-Host 'Downloading project-local Python 3.12 (no system Python required)...'
            Run-Checked $uvExe @('python', 'install', '--no-bin', '--no-registry', '3.12')
            $found = & $uvExe python find --managed-python --system --no-project 3.12
            if ($LASTEXITCODE -ne 0) { throw 'Cannot locate managed Python 3.12' }
            $basePython = "$found".Trim()
        }
        Run-Checked $basePython @('-c', 'import sys,ssl; assert sys.version_info[:2] == (3,12)')
        # Retain a copied or broken venv for rollback; recordings are never moved.
        if (Test-Path -LiteralPath $venvPath) {
            $backup = Join-Path $projectRoot ('.venv_backup_' + (Get-Date -Format 'yyyyMMdd_HHmmss_ffff'))
            if ([IO.Path]::GetFullPath($venvPath) -ne (Join-Path $projectRoot '.venv') -or
                (Split-Path -Parent $backup) -ne $projectRoot) { throw 'Invalid environment backup path' }
            Move-Item -LiteralPath $venvPath -Destination $backup
            Write-Host "Previous environment preserved: $backup"
        }
        Run-Checked $uvExe @('venv', '--python', $basePython, $venvPath)
        # PsychoPy's unused pywinhook dependency has no Python 3.12 wheel.
        # The tested runtime set is listed explicitly in lab_uv_env.toml.
        $env:UV_DEFAULT_INDEX = 'https://pypi.org/simple'
        Run-Checked $uvExe @('pip', 'install', '--python', $pythonExe, '--no-deps', 'psychopy==2026.2.2')
        $labProject = Join-Path $projectRoot '.uv_lab_env'
        New-Item -ItemType Directory -Force -Path $labProject | Out-Null
        $requirements = Join-Path $labProject 'pyproject.toml'
        Copy-Item -LiteralPath (Join-Path $projectRoot 'lab_uv_env.toml') -Destination $requirements -Force
        Run-Checked $uvExe @('pip', 'install', '--python', $pythonExe, '-r', $requirements, '--extra', 'runtime')
        $converter = Join-Path $projectRoot 'vendor\eeg-bids-converter'
        if (-not (Test-Path -LiteralPath (Join-Path $converter 'pyproject.toml'))) {
            $converter = Join-Path $projectRoot '..\third_party\eeg-bids-converter'
        }
        if (-not (Test-Path -LiteralPath (Join-Path $converter 'pyproject.toml'))) { throw 'Missing bundled BIDS converter source' }
        Run-Checked $uvExe @('pip', 'install', '--python', $pythonExe, $converter)
    } else {
        Write-Host 'Existing Python 3.12 environment passed checks; reusing it.'
    }
    Run-Checked $pythonExe @((Join-Path $PSScriptRoot 'patch_pyglet_win32.py'))
    Run-Checked $pythonExe @($checker)
    Run-Checked $pythonExe @((Join-Path $PSScriptRoot 'prepare_demo_materials.py'))
    Write-Host 'Environment ready. No data or materials were deleted.' -ForegroundColor Green
    Write-Host 'Double-click run_experiment.bat, choose protocol and Demo first, then Formal.'
    Write-Host 'Installation, materials, device configuration and data: see README.md.'
    Stop-Transcript | Out-Null
    exit 0
} catch {
    Write-Host "Installation failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Log: $log"
    Write-Host 'Check your network and rerun this installer. Existing recordings are preserved.'
    Stop-Transcript | Out-Null
    exit 1
}
