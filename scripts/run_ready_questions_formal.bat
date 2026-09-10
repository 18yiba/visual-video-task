@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "ROOT=%%~fI\"
cd /d "%ROOT%"

set "APPDATA=%ROOT%.psychopy_appdata"
set "TEMP=%ROOT%.tmp"
set "TMP=%ROOT%.tmp"
if not exist "%APPDATA%" mkdir "%APPDATA%"
if not exist "%TEMP%" mkdir "%TEMP%"

set "PYTHONUTF8=1"
set "PYTHONWARNINGS=ignore::SyntaxWarning"
set "QT_LOGGING_RULES=qt.qpa.*=false;*.debug=false"
set "PYTHON_EXE=%ROOT%.venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    echo Cannot find Python environment.
    echo Expected:
    echo   %ROOT%.venv\Scripts\python.exe
    pause
    exit /b 1
)

"%PYTHON_EXE%" "%ROOT%scripts\check_video_eeg_env.py" --quiet
if errorlevel 1 (
    echo.
    echo Video EEG Python environment is incomplete.
    echo Please run:
    echo   "%ROOT%scripts\install_lab_env_uv.bat"
    echo.
    "%PYTHON_EXE%" "%ROOT%scripts\check_video_eeg_env.py"
    pause
    exit /b 1
)

"%PYTHON_EXE%" -m video_eeg.experiment.ready_question_runner --config "%ROOT%video_eeg\config\video_ready_config.yaml" --real-eeg --device-type brainco --brainco-transport sdk
if errorlevel 1 (
    echo.
    echo Formal experiment exited with an error.
    pause
)
