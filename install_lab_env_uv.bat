@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem This installer is scoped to the video EEG project. It never touches
rem subject data, EEG recordings, manifests, stimuli, or the rating program.
set "NO_PAUSE=0"
if /I "%~1"=="--no-pause" set "NO_PAUSE=1"

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "ROOT=%%~fI\"
cd /d "%ROOT%"

set "VENV=%ROOT%.venv"
set "PY=%VENV%\Scripts\python.exe"
set "PORTABLE_PY=%ROOT%..\runtime\python312\python.exe"
for %%I in ("%ROOT%..\runtime\python312") do set "PORTABLE_HOME=%%~fI"
set "LAB_PROJECT=%ROOT%.uv_lab_env"
set "BIDS_CONVERTER_PROJECT=%ROOT%..\third_party\eeg-bids-converter"
set "UV_LOCAL=%ROOT%tools\uv.exe"
set "PYPI_MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple"
set "PYPI_OFFICIAL=https://pypi.org/simple"
set "UV_HTTP_TIMEOUT=120"
set "UV_HTTP_RETRIES=3"
set "UV_CONCURRENT_DOWNLOADS=8"
set "UV_CACHE_DIR=%ROOT%.uv-cache"
rem exFAT and copied lab bundles cannot provide reliable hardlinks.  Use uv's
rem documented per-process copy mode instead of warning and falling back.
set "UV_LINK_MODE=copy"
set "UV_NO_MANAGED_PYTHON=1"
set "UV_PYTHON_DOWNLOADS=never"
set "CHECK_LOG=%TEMP%\video_eeg_envcheck_%RANDOM%.log"
set "HEALTH_CHECK=%ROOT%scripts\check_video_eeg_env.py"
set "PYTHONNOUSERSITE=1"

if not exist "%ROOT%tools" mkdir "%ROOT%tools"
if errorlevel 1 goto failed

rem Prefer the package-local uv. PATH is only a fallback for older packages.
if exist "%UV_LOCAL%" (
    set "UV_CMD=%UV_LOCAL%"
) else (
    where uv >nul 2>nul
    if not errorlevel 1 set "UV_CMD=uv"
)

if not defined UV_CMD (
    echo No project-local uv.exe was found; installing the official standalone uv into:
    echo   %ROOT%tools
    set "UV_INSTALL_DIR=%ROOT%tools"
    set "UV_NO_MODIFY_PATH=1"
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    if errorlevel 1 goto failed
    if exist "%UV_LOCAL%" set "UV_CMD=%UV_LOCAL%"
)

if not defined UV_CMD (
    echo uv was installed but could not be located at "%UV_LOCAL%".
    goto failed
)

echo.
echo Controlled uv:
echo   %UV_CMD%
"%UV_CMD%" --version
if errorlevel 1 goto failed

rem This validates uv.toml before any dependency operation.
"%UV_CMD%" pip --help >nul 2>"%CHECK_LOG%"
if errorlevel 1 (
    echo uv.toml could not be parsed or uv is unusable:
    type "%CHECK_LOG%"
    goto failed
)

echo.
echo Selecting the fastest Python package index...
powershell.exe -NoProfile -Command "$ProgressPreference='SilentlyContinue'; try { Invoke-WebRequest -Method Head -Uri '%PYPI_MIRROR%/psychopy/' -TimeoutSec 8 -UseBasicParsing | Out-Null; exit 0 } catch { exit 1 }"
if errorlevel 1 (
    echo Mirror unavailable. Falling back to official PyPI.
    set "UV_DEFAULT_INDEX=%PYPI_OFFICIAL%"
) else (
    echo Using Tsinghua PyPI mirror.
    set "UV_DEFAULT_INDEX=%PYPI_MIRROR%"
)

if not exist "%PORTABLE_PY%" (
    echo Missing required portable Python:
    echo   %PORTABLE_PY%
    echo This deployment must not fall back to an external or system Python.
    goto failed
)

echo.
echo Portable Python:
"%PORTABLE_PY%" --version
if errorlevel 1 goto failed
"%PORTABLE_PY%" -m venv --help >nul 2>"%CHECK_LOG%"
if errorlevel 1 (
    echo Portable Python does not provide venv:
    type "%CHECK_LOG%"
    goto failed
)
"%PORTABLE_PY%" -c "import sys,ssl,venv; print(sys.executable); print(ssl.OPENSSL_VERSION)" >nul 2>"%CHECK_LOG%"
if errorlevel 1 (
    echo Portable Python failed the venv/SSL capability check:
    type "%CHECK_LOG%"
    goto failed
)

if not exist "%ROOT%lab_uv_env.toml" (
    echo Cannot find lab_uv_env.toml in:
    echo   %ROOT%
    goto failed
)
if not exist "%LAB_PROJECT%" mkdir "%LAB_PROJECT%"
copy /Y "%ROOT%lab_uv_env.toml" "%LAB_PROJECT%\pyproject.toml" >nul
if errorlevel 1 goto failed
if not exist "%HEALTH_CHECK%" (
    echo Missing dependency health checker:
    echo   %HEALTH_CHECK%
    goto failed
)
if not exist "%BIDS_CONVERTER_PROJECT%\pyproject.toml" (
    echo Missing bundled EEG BIDS converter project:
    echo   %BIDS_CONVERTER_PROJECT%
    goto failed
)

rem Reuse a healthy venv. A stale base Python requires a rebuild; a healthy
rem base with missing imports is repaired in place, so a network interruption
rem cannot discard the last usable environment.
set "NEEDS_REBUILD=0"
set "NEEDS_DEP_INSTALL=0"
if not exist "%PY%" set "NEEDS_REBUILD=1"
if "!NEEDS_REBUILD!"=="0" (
    "%PY%" -c "import sys,pathlib; assert sys.version_info[:2]==(3,12); assert pathlib.Path(sys.base_prefix).resolve()==pathlib.Path(r'%PORTABLE_HOME%').resolve()" >"%CHECK_LOG%" 2>&1
    if errorlevel 1 set "NEEDS_REBUILD=1"
)
if "!NEEDS_REBUILD!"=="0" (
    "%PY%" "%HEALTH_CHECK%" --quiet >"%CHECK_LOG%" 2>&1
    rem A failed import can mean package metadata exists while payload files are
    rem missing after an interrupted copy.  A normal uv sync trusts that stale
    rem metadata, so rebuild the disposable venv instead of reporting success
    rem from a partially repaired environment.
    if errorlevel 1 set "NEEDS_REBUILD=1"
)

if "!NEEDS_REBUILD!"=="1" (
    if exist "%VENV%" (
        echo Existing .venv is missing, stale, or unhealthy. Preserving it as a backup...
        set "BROKEN_NAME=.venv_broken_%RANDOM%"
        ren "%VENV%" "!BROKEN_NAME!"
        if errorlevel 1 (
            echo Could not preserve the broken .venv. No data directories were touched.
            goto failed
        )
        echo Preserved at %ROOT%!BROKEN_NAME!
    )
    echo Creating .venv from the package-local Python 3.12 runtime...
    "%PORTABLE_PY%" -m venv "%VENV%"
    if errorlevel 1 goto failed
    set "NEEDS_DEP_INSTALL=1"
)

if "!NEEDS_DEP_INSTALL!"=="1" (
    echo Installing video EEG runtime dependencies into:
    echo   %PY%
    rem PsychoPy is deliberately installed without optional pywinhook, which
    rem has no usable Python 3.12 wheel here and is not used by this paradigm.
    rem Its complete required runtime dependency set is declared in lab_uv_env.toml.
    "%UV_CMD%" pip install --python "%PY%" --no-deps psychopy==2026.2.2
    if errorlevel 1 goto failed
    "%UV_CMD%" pip install --python "%PY%" -r "%LAB_PROJECT%\pyproject.toml" --extra runtime
    if errorlevel 1 goto failed
    "%UV_CMD%" pip install --python "%PY%" "%BIDS_CONVERTER_PROJECT%"
    if errorlevel 1 goto failed
) else (
    echo Existing .venv is healthy; reusing it without rebuilding the environment.
)

if not exist "%PY%" (
    echo .venv creation did not produce:
    echo   %PY%
    goto failed
)

"%PY%" "%ROOT%scripts\patch_pyglet_win32.py"
if errorlevel 1 goto failed

echo.
echo Verifying video EEG imports with the venv interpreter...
"%PY%" -c "import sys,importlib; print(sys.executable); print(sys.version); [print(m, getattr(importlib.import_module(m),'__version__','installed')) for m in ('numpy','scipy','psychopy','cv2','imageio_ffmpeg','pylsl','psutil','serial','yaml','zeroconf','pytest')]; import video_eeg.experiment.video_runner; print('video_eeg core import ok')"
if errorlevel 1 goto failed
"%PY%" "%HEALTH_CHECK%"
if errorlevel 1 goto failed

if exist "%CHECK_LOG%" del /q "%CHECK_LOG%" >nul 2>nul
echo.
echo Lab environment is ready.
echo All packages were installed or repaired in the explicit project venv:
echo   %PY%
echo You can now double-click run_video_demo.bat or run_video_formal.bat.
if "%NO_PAUSE%"=="0" pause
exit /b 0

:failed
echo.
echo Lab environment setup failed.
if exist "%CHECK_LOG%" (
    echo Diagnostic output:
    type "%CHECK_LOG%"
    del /q "%CHECK_LOG%" >nul 2>nul
)
echo No subject data, EEG raw data, manifests, or video materials were deleted by this script.
if "%NO_PAUSE%"=="0" pause
exit /b 1
