# Project-local Python provisioning. Dot-source from the installer or its tests.
function Find-ProjectPython([string]$InstallDir) {
    $candidates = @(Get-ChildItem -LiteralPath $InstallDir -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^cpython-3\.12\.\d+-windows-x86_64-none$' } |
        Sort-Object { [version]($_.Name -replace '^cpython-([\d.]+)-.*$', '$1') } -Descending)
    foreach ($candidate in $candidates) {
        $exe = Join-Path $candidate.FullName 'python.exe'
        if (Test-Path -LiteralPath $exe) {
            & $exe -I -c 'import sys,ssl,venv,ctypes,sqlite3; assert sys.version_info[:2] == (3,12); assert sys.maxsize > 2**32'
            if ($LASTEXITCODE -eq 0) { return $exe }
        }
    }
    return $null
}

function Install-ProjectPython([string]$UvExe, [string]$InstallDir) {
    # A prior exFAT attempt may have installed the complete interpreter before
    # failing to create uv's optional minor-version junction. Reuse the real path.
    $existing = Find-ProjectPython $InstallDir
    if ($existing) { return $existing }
    $savedPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = @(& $UvExe python install --no-bin --no-registry 3.12 2>&1)
        $result = $LASTEXITCODE
    } finally { $ErrorActionPreference = $savedPreference }
    $output | ForEach-Object { Write-Host "$_" }
    $python = Find-ProjectPython $InstallDir
    if ($result -ne 0) {
        # Accept only this specific post-install junction failure, and only if
        # the full interpreter passes the isolated standard-library check.
        if (-not $python -or ($output -join "`n") -notmatch 'Failed to create Python minor version link directory') {
            throw "Python installation failed (exit $result). See the original error above."
        }
        Write-Host 'Python is complete; this filesystem does not support the optional uv version junction. Using its exact directory.'
    }
    if (-not $python) { throw 'Python 3.12 installation is incomplete; keep the log and retry.' }
    return $python
}
