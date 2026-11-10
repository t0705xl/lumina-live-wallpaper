@echo off
chcp 65001 >nul
setlocal
set "SCRIPT_DIR=%~dp0"

if "%~1"=="" (
    echo 用法 / Usage:
    echo   将 .mp4 视频文件直接拖拽到此脚本上，或在命令行运行:
    echo   set-live-wallpaper.bat ^<视频路径.mp4 或 静态图片.png^>
    echo   set-live-wallpaper.bat --daemon
    pause
    exit /b 1
)

python "%SCRIPT_DIR%win_wallpaper_daemon.py" "%~1"
