@echo off
setlocal EnableExtensions
call "%~dp0scripts\install_lab_env_uv.bat" %*
exit /b %ERRORLEVEL%
