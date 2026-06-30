@echo off
setlocal

set "PY=C:\Users\vermi\AppData\Local\Programs\Python\Python314\python.exe"
set "FFMPEG=C:\Users\vermi\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.2-full_build\bin"
set "PATH=%PATH%;%FFMPEG%"

cd /d "%~dp0"
"%PY%" -c "from youtube_script_app.gui import main; main()"
