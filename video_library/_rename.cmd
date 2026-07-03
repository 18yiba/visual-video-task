@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

echo === before ===
dir /b /a-d 2>nul

set "n=0"
for /f "delims=" %%F in ('dir /b /a-d /on *.mp4 *.avi *.mov *.mkv *.webm 2^>nul') do (
  set "name=%%F"
  echo !name! | findstr /i /r "^stim_[0-9][0-9][0-9]\.mp4$" >nul
  if errorlevel 1 (
    set /a n+=1
    set "idx=00!n!"
    set "idx=0!idx!"
    set "idx=!idx:~-3!"
    ren "%%F" "__tmp_!idx!.tmp"
  )
)

set "n=0"
for /f "delims=" %%F in ('dir /b /a-d /on __tmp_*.tmp 2^>nul') do (
  set /a n+=1
  set "idx=00!n!"
  set "idx=0!idx!"
  set "idx=!idx:~-3!"
  ren "%%F" "stim_!idx!.mp4"
)

echo === after ===
dir /b /a-d 2>nul
