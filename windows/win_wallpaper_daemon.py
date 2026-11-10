#!/usr/bin/env python3
"""
windows/win_wallpaper_daemon.py - Windows 10 / 11 Live Wallpaper Daemon & CLI Controller
Features:
- Hardware-accelerated video playback inside Win32 WorkerW (behind desktop icons)
- Native Windows Settings -> Personalization integration (auto-fades to static when user changes wallpaper)
- 4-way zero-power auto-pause (Fullscreen D3D games, fullscreen apps, Lock Screen, Battery Saver)
- Automatic Material You (Monet) synchronization with Windows DWM Taskbar & Windows Terminal
"""

import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.registry import (
    get_data_dir,
    load_registry,
    register_wallpaper,
    resolve_video_for_wallpaper,
)
from windows.win_monet_sync import apply_windows_monet
from windows.win_occlusion import should_pause_playback
from windows.win_workerw import (
    animate_window_alpha,
    get_desktop_workerw_hwnd,
    get_windows_wallpaper_path,
    set_windows_wallpaper_path,
)

MPV_IPC_PIPE = r"\\.\pipe\lumina-mpv"


def extract_cover_frame_windows(video_path, cover_path):
    """Extract high-resolution cover frame using ffmpeg or mpv."""
    os.makedirs(os.path.dirname(cover_path), exist_ok=True)
    ffmpeg_bin = shutil.which("ffmpeg")
    if ffmpeg_bin:
        subprocess.run(
            [
                ffmpeg_bin,
                "-y",
                "-ss",
                "00:00:00.500",
                "-i",
                video_path,
                "-frames:v",
                "1",
                "-vf",
                "scale=in_color_matrix=bt709:out_color_matrix=bt709",
                cover_path,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if os.path.isfile(cover_path):
            return True

    mpv_bin = shutil.which("mpv")
    if mpv_bin:
        subprocess.run(
            [
                mpv_bin,
                video_path,
                "--no-audio",
                "--start=0.5",
                "--frames=1",
                f"--o={cover_path}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if os.path.isfile(cover_path):
            return True
    return False


def set_wallpaper_windows(input_path):
    """Set a live video (.mp4/.mkv/.webm) or static image on Windows and sync Monet colors."""
    abs_input = os.path.abspath(input_path)
    if not os.path.isfile(abs_input):
        print(f"Error: File not found: {abs_input}", file=sys.stderr)
        sys.exit(1)

    ext = os.path.splitext(abs_input)[1].lower()
    if ext in (".png", ".jpg", ".jpeg", ".bmp", ".webp"):
        set_windows_wallpaper_path(abs_input)
        apply_windows_monet(abs_input)
        print(f"[Lumina-Win] Switched to static wallpaper: {abs_input}")
        return

    data_dir = get_data_dir()
    covers_dir = os.path.join(data_dir, "covers")
    os.makedirs(covers_dir, exist_ok=True)

    stem = os.path.splitext(os.path.basename(abs_input))[0]
    if stem.endswith("-live"):
        stem = stem[:-5]

    target_mp4 = os.path.join(data_dir, f"{stem}-live{ext}")
    current_mp4 = os.path.join(data_dir, "current-live-wallpaper.mp4")
    cover_png = os.path.join(covers_dir, f"{stem}-cover.png")

    shutil.copy2(abs_input, target_mp4)
    shutil.copy2(abs_input, current_mp4)

    extract_cover_frame_windows(target_mp4, cover_png)
    register_wallpaper([cover_png], target_mp4)

    if os.path.isfile(cover_png):
        set_windows_wallpaper_path(cover_png)
        apply_windows_monet(cover_png)

    print(f"[Lumina-Win] Registered & activated live wallpaper: {target_mp4}")


def send_mpv_ipc(command_list):
    """Send JSON IPC command to running mpv process over Windows Named Pipe."""
    try:
        with open(MPV_IPC_PIPE, "r+b", buffering=0) as pipe:
            payload = (json.dumps({"command": command_list}) + "\n").encode("utf-8")
            pipe.write(payload)
        return True
    except Exception:
        return False


def run_daemon_windows():
    """Main Windows Live Wallpaper + Monet background daemon loop."""
    if sys.platform != "win32":
        print("Error: Windows daemon must be run on Windows 10/11.", file=sys.stderr)
        sys.exit(1)

    mpv_bin = shutil.which("mpv")
    if not mpv_bin:
        print(
            "[Lumina-Win] 'mpv' not found in PATH. Install via: winget install mpv.net or scoop install mpv",
            file=sys.stderr,
        )
        sys.exit(1)

    workerw = get_desktop_workerw_hwnd()
    print(f"[Lumina-Win] Attached to Desktop WorkerW HWND: 0x{workerw:08X}")

    mpv_proc = None
    current_video = None
    last_wallpaper = None
    is_paused = False

    def stop_player():
        nonlocal mpv_proc, current_video
        if mpv_proc and mpv_proc.poll() is None:
            animate_window_alpha(workerw, 255, 0, duration_ms=160)
            mpv_proc.terminate()
            try:
                mpv_proc.wait(timeout=2)
            except Exception:
                mpv_proc.kill()
        mpv_proc = None
        current_video = None

    def start_player(video_path):
        nonlocal mpv_proc, current_video, is_paused
        if mpv_proc and mpv_proc.poll() is None and current_video == video_path:
            return
        stop_player()
        current_video = video_path
        is_paused = False
        cmd = [
            mpv_bin,
            video_path,
            f"--wid={workerw}",
            "--loop-file=inf",
            "--no-audio",
            "--hwdec=auto",
            "--panscan=1.0",
            "--no-osc",
            "--no-osd-bar",
            "--cursor-autohide=no",
            f"--input-ipc-server={MPV_IPC_PIPE}",
        ]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        mpv_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        animate_window_alpha(workerw, 20, 255, duration_ms=180)
        print(f"[Lumina-Win] Playing hardware-accelerated live wallpaper: {video_path}")

    try:
        while True:
            wp = get_windows_wallpaper_path()
            if wp and wp != last_wallpaper:
                last_wallpaper = wp
                apply_windows_monet(wp)
                target_video = resolve_video_for_wallpaper(wp)
                if target_video:
                    start_player(target_video)
                else:
                    if current_video:
                        print(f"[Lumina-Win] Native static wallpaper selected ({wp}), stopping video layer.")
                    stop_player()

            if current_video and mpv_proc and mpv_proc.poll() is None:
                pause_needed, reason = should_pause_playback()
                if pause_needed != is_paused:
                    is_paused = pause_needed
                    send_mpv_ipc(["set_property", "pause", is_paused])
                    print(f"[Lumina-Win] {'Pausing' if is_paused else 'Resuming'} playback ({reason})")

            time.sleep(0.4)
    except (KeyboardInterrupt, SystemExit):
        stop_player()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("--daemon", "-d", "daemon"):
        run_daemon_windows()
    elif len(sys.argv) > 1:
        set_wallpaper_windows(sys.argv[1])
    else:
        print("Usage: python win_wallpaper_daemon.py <video.mp4 | image.png | --daemon>")
