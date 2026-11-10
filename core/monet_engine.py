#!/usr/bin/env python3
"""
core/monet_engine.py - Cross-Platform Material Design 3 (M3 / Monet) Color Engine
Works identically on Linux (GNOME / GTK4 / Ptyxis) and Windows 10/11 (DWM / Windows Terminal).
"""

import colorsys
from PIL import Image


def hex_color(h, l, s):
    r, g, b = colorsys.hls_to_rgb(h % 1.0, max(0.0, min(1.0, l)), max(0.0, min(1.0, s)))
    return f"#{int(r * 255):02X}{int(g * 255):02X}{int(b * 255):02X}"


def rgb_tuple(h, l, s):
    r, g, b = colorsys.hls_to_rgb(h % 1.0, max(0.0, min(1.0, l)), max(0.0, min(1.0, s)))
    return int(r * 255), int(g * 255), int(b * 255)


def rgba_color(h, l, s, a):
    r, g, b = rgb_tuple(h, l, s)
    return f"rgba({r}, {g}, {b}, {a})"


def extract_dominant_hls(image_path):
    """Extract dominant vibrant hue and saturation from an image file."""
    if not image_path:
        return 0.58, 0.35
    try:
        img = Image.open(image_path).convert("RGB").resize((64, 64))
        try:
            pixels = list(img.get_flattened_data())
        except AttributeError:
            pixels = list(img.getdata())

        scored = []
        for p in pixels:
            r, g, b = p[:3]
            h, l, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
            if 0.15 < l < 0.85 and s > 0.15:
                score = s * (1.0 - abs(l - 0.5))
                scored.append((score, (h, l, s)))

        if scored:
            scored.sort(key=lambda x: x[0], reverse=True)
            h, _, s = scored[0][1]
            return h, s
    except Exception:
        pass
    return 0.58, 0.35


def extract_palette(image_path, scheme="prefer-dark"):
    """
    Generate a complete cross-platform Material Design 3 tonal palette:
    - GNOME Shell / GTK4 surface & accent tokens
    - Windows 10/11 DWM ABGR DWORD & 8-shade Explorer AccentPalette binary
    - 16-color ANSI Terminal scheme (Ptyxis & Windows Terminal)
    """
    is_dark = scheme == "prefer-dark"
    h, s = extract_dominant_hls(image_path)

    if is_dark:
        sr, sg, sb = rgb_tuple(h, 0.14, min(s, 0.22))
        bg_surface = f"rgba({sr}, {sg}, {sb}, 0.82)"
        bg_solid = f"rgba({sr}, {sg}, {sb}, 0.95)"
        bg_overview = f"rgba({int(sr * 0.65)}, {int(sg * 0.65)}, {int(sb * 0.65)}, 0.40)"

        ar, ag, ab = rgb_tuple(h, 0.78, min(s * 1.1, 0.72))
        tr, tg, tb = rgb_tuple(h, 0.94, min(s, 0.12))
        text_color = f"rgb({tr}, {tg}, {tb})"
        hover_text = "#ffffff"
    else:
        sr, sg, sb = rgb_tuple(h, 0.94, min(s, 0.25))
        bg_surface = f"rgba({sr}, {sg}, {sb}, 0.85)"
        bg_solid = f"rgba({sr}, {sg}, {sb}, 0.96)"
        bg_overview = f"rgba({sr}, {sg}, {sb}, 0.35)"

        ar, ag, ab = rgb_tuple(h, 0.42, min(s * 1.15, 0.75))
        tr, tg, tb = rgb_tuple(h, 0.14, min(s, 0.18))
        text_color = f"rgb({tr}, {tg}, {tb})"
        hover_text = text_color

    accent_rgb = f"{ar}, {ag}, {ab}"
    accent_hex = f"#{ar:02X}{ag:02X}{ab:02X}"

    # Windows DWM uses 0xAABBGGRR DWORD format; pick a rich mid-tone accent for taskbar/borders
    wr, wg, wb = rgb_tuple(h, 0.48, min(s * 1.2, 0.78))
    dwm_abgr_dword = (0xFF << 24) | (wb << 16) | (wg << 8) | wr
    dwm_argb_dword = (0xC4 << 24) | (wr << 16) | (wg << 8) | wb

    # Windows Explorer 8-shade AccentPalette (lightest to darkest, 4 bytes RGBA each = 32 bytes)
    lightness_ramp = [0.88, 0.78, 0.68, 0.56, 0.48, 0.38, 0.26, 0.15]
    accent_palette_bytes = bytearray()
    for l_step in lightness_ramp:
        rr, rg, rb = rgb_tuple(h, l_step, min(s * 1.2, 0.78))
        accent_palette_bytes.extend([rr, rg, rb, 0x00])

    # 16-color ANSI Terminal Palette (shared by Linux Ptyxis & Windows Terminal)
    term_bg = hex_color(h, 0.11 if is_dark else 0.96, min(s * 1.1, 0.28))
    term_fg = hex_color(h, 0.90 if is_dark else 0.14, min(s, 0.12))
    term_cursor = hex_color(h, 0.78 if is_dark else 0.42, min(s * 1.1, 0.75))
    ansi_colors = [
        hex_color(h, 0.15, min(s, 0.15)),       # 0: Black
        "#FF897D",                              # 1: Red
        hex_color(0.32, 0.75, 0.45),            # 2: Green
        hex_color(h, 0.78, min(s * 1.2, 0.75)), # 3: Yellow / Primary Accent
        hex_color(0.58, 0.75, 0.55),            # 4: Blue
        hex_color(0.82, 0.75, 0.45),            # 5: Purple
        hex_color(0.48, 0.75, 0.45),            # 6: Cyan
        term_fg,                                # 7: White
        hex_color(h, 0.45, min(s, 0.15)),       # 8: Bright Black
        "#FFB4AB",                              # 9: Bright Red
        hex_color(0.32, 0.85, 0.45),            # 10: Bright Green
        hex_color(h, 0.86, min(s * 1.2, 0.80)), # 11: Bright Yellow
        hex_color(0.58, 0.85, 0.60),            # 12: Bright Blue
        hex_color(0.82, 0.85, 0.50),            # 13: Bright Purple
        hex_color(0.48, 0.85, 0.50),            # 14: Bright Cyan
        "#FFFFFF",                              # 15: Bright White
    ]

    return {
        "bg_surface": bg_surface,
        "bg_solid": bg_solid,
        "bg_overview": bg_overview,
        "accent_rgb": accent_rgb,
        "accent_hex": accent_hex,
        "text_color": text_color,
        "hover_text": hover_text,
        "is_dark": is_dark,
        "hue": round(h * 360, 1),
        "h_val": h,
        "s_val": s,
        "dwm_abgr_dword": dwm_abgr_dword,
        "dwm_argb_dword": dwm_argb_dword,
        "accent_palette_bytes": bytes(accent_palette_bytes),
        "terminal": {
            "background": term_bg,
            "foreground": term_fg,
            "cursor": term_cursor,
            "colors": ansi_colors,
        },
    }
