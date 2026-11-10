#!/usr/bin/env python3
"""
core/registry.py - Cross-Platform Live Wallpaper Registry & Path Manager
Manages cover-to-video mappings on both Linux (~/.config/live-wallpaper) and Windows (%APPDATA%/LuminaWallpaper).
"""

import json
import os
import sys


def get_config_dir():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "LuminaWallpaper")
    return os.path.expanduser("~/.config/live-wallpaper")


def get_data_dir():
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "LuminaWallpaper")
    return os.path.expanduser("~/.local/share/live-wallpaper")


def get_registry_path():
    return os.path.join(get_config_dir(), "registry.json")


def load_registry():
    reg_path = get_registry_path()
    default_video = os.path.join(get_data_dir(), "current-live-wallpaper.mp4")
    if os.path.exists(reg_path):
        try:
            with open(reg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                data.setdefault("wallpapers", {})
                data.setdefault("defaultVideo", default_video)
                return data
        except Exception:
            pass
    return {"wallpapers": {}, "defaultVideo": default_video}


def save_registry(data):
    reg_path = get_registry_path()
    os.makedirs(os.path.dirname(reg_path), exist_ok=True)
    with open(reg_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def register_wallpaper(cover_paths, video_path):
    data = load_registry()
    wallpapers = data.setdefault("wallpapers", {})
    norm_video = os.path.abspath(video_path)
    for cp in cover_paths:
        if not cp:
            continue
        norm_cp = os.path.abspath(cp)
        wallpapers[norm_cp] = norm_video
        wallpapers[os.path.normcase(norm_cp)] = norm_video
        wallpapers[os.path.basename(norm_cp)] = norm_video
    data["defaultVideo"] = os.path.join(get_data_dir(), "current-live-wallpaper.mp4")
    save_registry(data)
    return data


def resolve_video_for_wallpaper(wallpaper_path):
    if not wallpaper_path:
        return None
    norm_wp = os.path.abspath(wallpaper_path)
    base_name = os.path.basename(norm_wp)
    data = load_registry()
    wallpapers = data.get("wallpapers", {})

    for key in (norm_wp, os.path.normcase(norm_wp), base_name):
        candidate = wallpapers.get(key)
        if candidate and os.path.isfile(candidate):
            return candidate

    lower_base = base_name.lower()
    for suffix in ("-live-cover.png", "-cover.png", "-cover.jpg", "-cover.jpeg"):
        if lower_base.endswith(suffix):
            stem = base_name[: -len(suffix)]
            candidate = os.path.join(get_data_dir(), f"{stem}-live.mp4")
            if os.path.isfile(candidate):
                return candidate
            default_vid = data.get("defaultVideo")
            if default_vid and os.path.isfile(default_vid):
                return default_vid
    return None
