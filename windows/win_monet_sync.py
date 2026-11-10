#!/usr/bin/env python3
"""
windows/win_monet_sync.py - Windows 10 / 11 Material You (Monet) Synchronizer
Synchronizes:
1. Windows DWM Window Borders & Titlebars (HKCU\\Software\\Microsoft\\Windows\\DWM)
2. Windows Explorer Taskbar & Start Menu 8-Shade AccentPalette (HKCU\\...\\Explorer\\Accent)
3. Windows Terminal 16-Color ANSI Scheme & Acrylic Translucency (settings.json)
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.monet_engine import extract_palette


def is_windows_dark_mode():
    if sys.platform != "win32":
        return True
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return val == 0
    except Exception:
        return True


def apply_windows_dwm_accent(palette):
    """Write M3 Monet accent color into Windows DWM & Explorer registry and broadcast refresh."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        import winreg

        abgr = palette["dwm_abgr_dword"]
        argb = palette["dwm_argb_dword"]
        pal_bytes = palette["accent_palette_bytes"]

        with winreg.CreateKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\DWM",
        ) as key:
            winreg.SetValueEx(key, "AccentColor", 0, winreg.REG_DWORD, abgr)
            winreg.SetValueEx(key, "ColorizationColor", 0, winreg.REG_DWORD, argb)
            winreg.SetValueEx(key, "ColorizationAfterglow", 0, winreg.REG_DWORD, argb)

        with winreg.CreateKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Accent",
        ) as key:
            winreg.SetValueEx(key, "AccentPalette", 0, winreg.REG_BINARY, pal_bytes)
            winreg.SetValueEx(key, "AccentColorMenu", 0, winreg.REG_DWORD, abgr)
            winreg.SetValueEx(key, "StartColorMenu", 0, winreg.REG_DWORD, abgr)

        # Broadcast WM_SETTINGCHANGE ("ImmersiveColorSet") so Taskbar & DWM update immediately without flicker
        user32 = ctypes.windll.user32
        HWND_BROADCAST = 0xFFFF
        WM_SETTINGCHANGE = 0x001A
        SMTO_ABORTIFHUNG = 0x0002
        res = ctypes.c_ulong(0)
        user32.SendMessageTimeoutW(
            HWND_BROADCAST,
            WM_SETTINGCHANGE,
            0,
            "ImmersiveColorSet",
            SMTO_ABORTIFHUNG,
            1000,
            ctypes.byref(res),
        )
        print(f"[Monet-Win] Applied Windows DWM & Taskbar Accent: {palette['accent_hex']} (Hue: {palette['hue']}deg)")
    except Exception as e:
        print(f"[Monet-Win] Failed to apply DWM accent: {e}", file=sys.stderr)


def get_windows_terminal_settings_paths():
    local_appdata = os.environ.get("LOCALAPPDATA") or ""
    if not local_appdata:
        return []
    candidates = [
        os.path.join(
            local_appdata,
            "Packages",
            "Microsoft.WindowsTerminal_8wekyb3d8bbwe",
            "LocalState",
            "settings.json",
        ),
        os.path.join(
            local_appdata,
            "Packages",
            "Microsoft.WindowsTerminalPreview_8wekyb3d8bbwe",
            "LocalState",
            "settings.json",
        ),
        os.path.join(local_appdata, "Microsoft", "Windows Terminal", "settings.json"),
    ]
    return [p for p in candidates if os.path.isfile(p)]


def apply_windows_terminal_palette(palette):
    """Inject 'Monet' 16-color scheme and acrylic opacity into Windows Terminal settings.json."""
    term = palette["terminal"]
    c = term["colors"]
    monet_scheme = {
        "name": "Monet",
        "background": term["background"],
        "foreground": term["foreground"],
        "cursorColor": term["cursor"],
        "selectionBackground": palette["accent_hex"],
        "black": c[0],
        "red": c[1],
        "green": c[2],
        "yellow": c[3],
        "blue": c[4],
        "purple": c[5],
        "cyan": c[6],
        "white": c[7],
        "brightBlack": c[8],
        "brightRed": c[9],
        "brightGreen": c[10],
        "brightYellow": c[11],
        "brightBlue": c[12],
        "brightPurple": c[13],
        "brightCyan": c[14],
        "brightWhite": c[15],
    }

    for settings_path in get_windows_terminal_settings_paths():
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            schemes = data.setdefault("schemes", [])
            replaced = False
            for idx, s in enumerate(schemes):
                if isinstance(s, dict) and s.get("name") == "Monet":
                    schemes[idx] = monet_scheme
                    replaced = True
                    break
            if not replaced:
                schemes.append(monet_scheme)

            profiles = data.setdefault("profiles", {})
            defaults = profiles.setdefault("defaults", {})
            defaults["colorScheme"] = "Monet"
            defaults.setdefault("opacity", 92)
            defaults.setdefault("useAcrylic", True)

            tmp_path = f"{settings_path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            os.replace(tmp_path, settings_path)
            print(f"[Monet-Win] Synchronized Windows Terminal palette ({settings_path})")
        except Exception as e:
            print(f"[Monet-Win] Failed to update Windows Terminal ({settings_path}): {e}", file=sys.stderr)


def apply_windows_monet(wallpaper_path):
    scheme = "prefer-dark" if is_windows_dark_mode() else "prefer-light"
    palette = extract_palette(wallpaper_path, scheme=scheme)
    apply_windows_dwm_accent(palette)
    apply_windows_terminal_palette(palette)
    return palette
