#!/usr/bin/env python3
"""
lumina.py - Unified Cross-Platform Entrypoint for Lumina Live Wallpaper & Material You (Monet) Engine
Automatically dispatches to the native Linux (GNOME / GTK4 / GStreamer) or Windows 10/11 (WorkerW / DWM) backend.
"""

import os
import subprocess
import sys

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))


def print_usage():
    print(
        """Lumina Live Wallpaper & Monet Engine (Linux & Windows 10/11)

用法 / Usage:
  python lumina.py set <video.mp4 | image.png>   设置动态视频壁纸或静态壁纸，并自动同步全局莫奈配色
  python lumina.py live                          切换回最近使用的动态视频壁纸
  python lumina.py static                        切换回原生静态壁纸
  python lumina.py list                          列出所有已注册的动态壁纸
  python lumina.py remove <名称>                 删除指定的动态壁纸并清理封面
  python lumina.py daemon                        启动动态壁纸后台守护进程
  python lumina.py monet                         立即根据当前壁纸提取并应用莫奈 (Material You) 主题色
  python lumina.py refresh-badges                刷新系统设置中的「▶ LIVE」缩略图角标 (Linux GNOME)
  python lumina.py fit                           按屏幕尺寸重新生成 ≤30fps 播放副本（换显示器后运行，Linux GNOME）
"""
    )


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print_usage()
        return

    cmd = sys.argv[1].lower()
    is_win = sys.platform == "win32"

    if is_win:
        from windows.win_monet_sync import apply_windows_monet
        from windows.win_wallpaper_daemon import run_daemon_windows, set_wallpaper_windows
        from windows.win_workerw import get_windows_wallpaper_path

        if cmd == "set" and len(sys.argv) >= 3:
            set_wallpaper_windows(sys.argv[2])
        elif cmd == "daemon":
            run_daemon_windows()
        elif cmd == "monet":
            wp = get_windows_wallpaper_path()
            apply_windows_monet(wp)
        else:
            set_wallpaper_windows(sys.argv[1])
    else:
        linux_dir = os.path.join(ROOT_DIR, "linux")
        set_script = os.path.join(linux_dir, "set-live-wallpaper")
        daemon_script = os.path.join(linux_dir, "live-wallpaper-daemon")
        monet_script = os.path.join(linux_dir, "monet-panel.py")

        if cmd == "set" and len(sys.argv) >= 3:
            subprocess.run([set_script, sys.argv[2]], check=True)
        elif cmd == "live":
            subprocess.run([set_script, "--live"], check=True)
        elif cmd == "static":
            subprocess.run([set_script, "--static"], check=True)
        elif cmd == "list":
            subprocess.run([set_script, "--list"], check=True)
        elif cmd == "remove" and len(sys.argv) >= 3:
            subprocess.run([set_script, "--remove", sys.argv[2]], check=True)
        elif cmd == "refresh-badges":
            subprocess.run([set_script, "--refresh-badges"], check=True)
        elif cmd == "fit":
            subprocess.run([set_script, "--fit-all"], check=True)
        elif cmd == "daemon":
            subprocess.run(["gjs", daemon_script], check=True)
        elif cmd == "monet":
            subprocess.run([sys.executable, monet_script], check=True)
        elif os.path.isfile(sys.argv[1]):
            subprocess.run([set_script, sys.argv[1]], check=True)
        else:
            print_usage()


if __name__ == "__main__":
    main()
