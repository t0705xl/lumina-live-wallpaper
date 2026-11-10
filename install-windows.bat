@echo off
chcp 65001 >nul
setlocal
set "REPO_DIR=%~dp0"

echo ============================================================
echo   Lumina Live Wallpaper ^& Monet Engine - Windows Installer
echo ============================================================

echo [1/3] 安装 Python 依赖 (Pillow)...
python -m pip install --upgrade Pillow

echo [2/3] 检查硬件加速播放器 mpv...
where mpv >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo 未检测到 mpv，尝试通过 winget 自动安装 mpv...
    winget install --id=shinchiro.mpv -e --accept-source-agreements --accept-package-agreements
)

echo [3/3] 注册 Windows 开机自启守护进程...
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "LuminaLiveWallpaper" /t REG_SZ /d "pythonw \"%REPO_DIR%windows\win_wallpaper_daemon.py\" --daemon" /f

echo 正在后台启动 Lumina 守护进程...
start "" pythonw "%REPO_DIR%windows\win_wallpaper_daemon.py" --daemon

echo.
echo 安装完成！
echo 你可以直接将任意 .mp4 视频拖拽到 windows\set-live-wallpaper.bat 上，或运行:
echo   python lumina.py set ^<视频文件.mp4^>
pause
