@echo off
setlocal EnableExtensions
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo Please run install_lab_env_uv.bat first.
  pause
  exit /b 1
)
"%~dp0.venv\Scripts\python.exe" "%~dp0scripts\download_materials.py" %*
set "RESULT=%ERRORLEVEL%"
if /I not "%~1"=="--no-pause" pause
exit /b %RESULT%
