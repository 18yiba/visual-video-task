@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONNOUSERSITE=1"
set "APPDATA=%CD%\.psychopy_appdata"
set "TEMP=%CD%\.tmp"
set "TMP=%CD%\.tmp"
if not exist "%APPDATA%" mkdir "%APPDATA%"
if not exist "%TEMP%" mkdir "%TEMP%"
if not exist ".venv\Scripts\python.exe" (
  echo Please run install_lab_env_uv.bat first.
  pause
  exit /b 1
)
set "VIDEO_EEG_BACKEND=neuracle"
.venv\Scripts\python.exe main.py --protocol v3 --device neuracle %*
if errorlevel 1 pause
