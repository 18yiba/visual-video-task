@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup_virtual_serial.ps1" %*
set "RESULT=%ERRORLEVEL%"
pause
exit /b %RESULT%
