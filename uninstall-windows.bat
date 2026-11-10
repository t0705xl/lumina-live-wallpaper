@echo off
chcp 65001 >nul
echo 正在移除 Lumina 开机自启项并停止后台进程...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "LuminaLiveWallpaper" /f 2>nul
taskkill /F /IM mpv.exe 2>nul
echo 已完成卸载。
pause
