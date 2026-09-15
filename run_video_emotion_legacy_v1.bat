@echo off
setlocal
set "VIDEO_EEG_EMOTION_CONFIG=video_emotion_v1_config.yaml"
call "%~dp0scripts\run_video_emotion_formal.bat" %*
