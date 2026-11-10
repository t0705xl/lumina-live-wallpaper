#!/usr/bin/env python3
"""
windows/win_occlusion.py - Windows 10 / 11 Zero-Power Smart Auto-Pause Detector
Detects Fullscreen D3D/OpenGL games, fullscreen videos, Lock Screen, Display Sleep, and Battery Saver.
"""

import sys

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    shell32 = ctypes.windll.shell32
    kernel32 = ctypes.windll.kernel32

    # QUERY_USER_NOTIFICATION_STATE enum values
    QUNS_NOT_PRESENT = 1             # Screen locked, screensaver, or display asleep
    QUNS_BUSY = 2                    # Fullscreen app (F11 browser, maximized video, etc.)
    QUNS_RUNNING_D3D_FULL_SCREEN = 3 # Exclusive D3D fullscreen game
    QUNS_PRESENTATION_MODE = 4       # Presentation mode

    class SYSTEM_POWER_STATUS(ctypes.Structure):
        _fields_ = [
            ("ACLineStatus", wintypes.BYTE),
            ("BatteryFlag", wintypes.BYTE),
            ("BatteryLifePercent", wintypes.BYTE),
            ("SystemStatusFlag", wintypes.BYTE),  # 1 = Windows Battery Saver ON
            ("BatteryLifeTime", wintypes.DWORD),
            ("BatteryFullLifeTime", wintypes.DWORD),
        ]


def should_pause_playback():
    """
    Return (paused: bool, reason: str) for Windows 10/11.
    Mirrors Linux's 4-way zero-power auto-pause (Fullscreen, Lock Screen, Display Sleep, Power Saver).
    """
    if sys.platform != "win32":
        return False, "active"

    # 1. Check Fullscreen / Lock Screen / Display Sleep via SHQueryUserNotificationState
    state = ctypes.c_int(0)
    hr = shell32.SHQueryUserNotificationState(ctypes.byref(state))
    if hr == 0:
        val = state.value
        if val == QUNS_NOT_PRESENT:
            return True, "screen locked or display asleep"
        if val == QUNS_RUNNING_D3D_FULL_SCREEN:
            return True, "fullscreen D3D game"
        if val in (QUNS_BUSY, QUNS_PRESENTATION_MODE):
            return True, "fullscreen application"

    # 2. Check Windows Battery Saver (Energy Saver) status
    sps = SYSTEM_POWER_STATUS()
    if kernel32.GetSystemPowerStatus(ctypes.byref(sps)):
        if sps.SystemStatusFlag == 1:
            return True, "Windows battery saver enabled"

    return False, "desktop visible"
