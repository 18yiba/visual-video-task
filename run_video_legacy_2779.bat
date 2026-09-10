@echo off
setlocal
set "VIDEO_EEG_CONFIG=video_legacy_2779_config.yaml"
call "%~dp0scripts\run_video_formal.bat"
exit /b %ERRORLEVEL%
