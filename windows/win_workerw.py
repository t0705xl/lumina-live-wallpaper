#!/usr/bin/env python3
"""
windows/win_workerw.py - Windows 10 / 11 Desktop WorkerW Layer & Native Wallpaper API
Mounts video windows behind desktop icons (SHELLDLL_DefView) and above the native static wallpaper.
"""

import sys
import time

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    SPI_GETDESKWALLPAPER = 0x0073
    SPI_SETDESKWALLPAPER = 0x0014
    SPIF_UPDATEINIFILE = 0x01
    SPIF_SENDCHANGE = 0x02

    GWL_EXSTYLE = -20
    GWL_STYLE = -16
    WS_EX_LAYERED = 0x00080000
    WS_EX_NOACTIVATE = 0x08000000
    WS_EX_TOOLWINDOW = 0x00000080
    WS_CHILD = 0x40000000
    WS_POPUP = 0x80000000
    LWA_ALPHA = 0x00000002
    SMTO_NORMAL = 0x0000

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def get_desktop_workerw_hwnd():
    """
    Spawn and locate the hidden WorkerW window behind SHELLDLL_DefView on Windows 10 & Windows 11 (including 24H2).
    """
    if sys.platform != "win32":
        raise RuntimeError("win_workerw is only supported on Windows.")

    progman = user32.FindWindowW("Progman", None)
    if not progman:
        return 0

    result = wintypes.DWORD(0)
    # Send undocumented 0x052C message to Progman to split WorkerW layer behind desktop icons
    user32.SendMessageTimeoutW(
        progman,
        0x052C,
        0xD,
        0x1,
        SMTO_NORMAL,
        1000,
        ctypes.byref(result),
    )

    workerw_hwnd = [0]

    def _enum_windows_proc(hwnd, _lparam):
        defview = user32.FindWindowExW(hwnd, 0, "SHELLDLL_DefView", None)
        if defview:
            # Classic Windows 10 / 11 (21H2-23H2): WorkerW is the next sibling after the SHELLDLL_DefView host
            sibling = user32.FindWindowExW(0, hwnd, "WorkerW", None)
            if sibling:
                workerw_hwnd[0] = sibling
                return False
            # Windows 11 24H2 raised desktop fallback: WorkerW is a direct child of Progman
            child = user32.FindWindowExW(progman, 0, "WorkerW", None)
            if child:
                workerw_hwnd[0] = child
                return False
        return True

    enum_cb = WNDENUMPROC(_enum_windows_proc)
    user32.EnumWindows(enum_cb, 0)
    return workerw_hwnd[0] or progman


def get_primary_screen_rect():
    """Return (width, height) of primary monitor on Windows."""
    if sys.platform != "win32":
        return 1920, 1080
    width = user32.GetSystemMetrics(0)
    height = user32.GetSystemMetrics(1)
    return width, height


def attach_window_to_desktop(child_hwnd):
    """Reparent a video player window into the desktop WorkerW layer and resize to cover screen."""
    if sys.platform != "win32" or not child_hwnd:
        return False
    workerw = get_desktop_workerw_hwnd()
    if not workerw:
        return False

    w, h = get_primary_screen_rect()
    style = user32.GetWindowLongW(child_hwnd, GWL_STYLE)
    style = (style & ~WS_POPUP) | WS_CHILD
    user32.SetWindowLongW(child_hwnd, GWL_STYLE, style)

    ex_style = user32.GetWindowLongW(child_hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(
        child_hwnd,
        GWL_EXSTYLE,
        ex_style | WS_EX_LAYERED | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW,
    )

    user32.SetParent(child_hwnd, workerw)
    user32.MoveWindow(child_hwnd, 0, 0, w, h, True)
    return True


def animate_window_alpha(hwnd, start_alpha, end_alpha, duration_ms=180, steps=9):
    """Smoothly crossfade window opacity (0..255) using Win32 SetLayeredWindowAttributes."""
    if sys.platform != "win32" or not hwnd:
        return
    ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    if not (ex_style & WS_EX_LAYERED):
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style | WS_EX_LAYERED)

    step_delay = max(0.01, (duration_ms / 1000.0) / steps)
    for i in range(1, steps + 1):
        t = i / steps
        eased = 1.0 - (1.0 - t) ** 3 if end_alpha > start_alpha else t
        cur = int(start_alpha + (end_alpha - start_alpha) * eased)
        cur = max(0, min(255, cur))
        user32.SetLayeredWindowAttributes(hwnd, 0, cur, LWA_ALPHA)
        time.sleep(step_delay)


def get_windows_wallpaper_path():
    """Query current static wallpaper path from Windows Explorer."""
    if sys.platform != "win32":
        return None
    buf = ctypes.create_unicode_buffer(512)
    if user32.SystemParametersInfoW(SPI_GETDESKWALLPAPER, 512, buf, 0):
        return buf.value
    return None


def set_windows_wallpaper_path(image_path):
    """Set Windows native static wallpaper (updates Task View, Lock Screen & Registry)."""
    if sys.platform != "win32":
        return False
    return bool(
        user32.SystemParametersInfoW(
            SPI_SETDESKWALLPAPER,
            0,
            image_path,
            SPIF_UPDATEINIFILE | SPIF_SENDCHANGE,
        )
    )
