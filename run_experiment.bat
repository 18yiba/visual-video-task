@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONNOUSERSITE=1"
set "APPDATA=%~dp0.psychopy_appdata"
set "TEMP=%~dp0.tmp"
set "TMP=%~dp0.tmp"
if not exist "%APPDATA%" mkdir "%APPDATA%"
if not exist "%TEMP%" mkdir "%TEMP%"
set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
  echo Please run install_lab_env_uv.bat first.
  pause
  exit /b 1
)
"%PYTHON_EXE%" "%~dp0scripts\check_video_eeg_env.py" --quiet
if errorlevel 1 (
  echo Environment check failed. See README.md installation steps.
  pause
  exit /b 1
)
"%PYTHON_EXE%" "%~dp0scripts\launch_experiment.py" %*
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" pause
exit /b %RESULT%
