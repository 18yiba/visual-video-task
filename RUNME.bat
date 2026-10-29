@echo off
setlocal
call "%~dp0run_experiment.bat" %*
exit /b %ERRORLEVEL%
