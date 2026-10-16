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
if not "%~1"=="" goto run
.venv\Scripts\python.exe scripts\launch_emotion_v3.py
goto end
:run
.venv\Scripts\python.exe -m video_eeg.experiment.emotion_v3_runner %*
:end
if errorlevel 1 pause
