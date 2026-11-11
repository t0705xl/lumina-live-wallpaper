#!/usr/bin/env python3
"""
monet-panel.py - Material You (M3) Monet Dynamic Color Engine for Fedora / GNOME
Synchronizes:
1. GNOME Shell Top Bar (Floating M3 Pills)
2. Activities Overview Background (Transparent/Tinted, Search Entry, Dash, Workspace cards)
3. Ptyxis Terminal (Background, Cursor, 16-color ANSI syntax palette, Opacity)
4. System-wide Libadwaita / GTK4 / GTK3 Applications (Nautilus, Settings, Text Editor translucent acrylic)
5. GNOME Native Accent Color (Folder icons, switches, selections)
"""

import sys
import os
import subprocess
import urllib.parse
import colorsys
import time
from PIL import Image

# 保证环境变量中存在 DBUS_SESSION_BUS_ADDRESS
if 'DBUS_SESSION_BUS_ADDRESS' not in os.environ:
    uid = os.getuid()
    bus_path = f"/run/user/{uid}/bus"
    if os.path.exists(bus_path):
        os.environ['DBUS_SESSION_BUS_ADDRESS'] = f"unix:path={bus_path}"

# Force unbuffered output so systemd journal catches logs immediately
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(line_buffering=True)

import gi
gi.require_version('Gio', '2.0')
gi.require_version('GLib', '2.0')
from gi.repository import Gio, GLib

EXTENSION_UUID = "avatar-quick-settings@github.leginreklaw"
CSS_PATH = os.path.expanduser(f"~/.local/share/gnome-shell/extensions/{EXTENSION_UUID}/stylesheet.css")
PTYXIS_PALETTES_DIR = os.path.expanduser("~/.local/share/org.gnome.Ptyxis/palettes")
PTYXIS_PALETTE_PATH = os.path.join(PTYXIS_PALETTES_DIR, "monet.palette")
GTK4_CSS_PATH = os.path.expanduser("~/.config/gtk-4.0/gtk.css")
GTK3_CSS_PATH = os.path.expanduser("~/.config/gtk-3.0/gtk.css")

_last_applied_state = None

def atomic_write(filepath, content):
    """Write content to file atomically to prevent partial-read race conditions."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    tmppath = f"{filepath}.tmp.{os.getpid()}"
    with open(tmppath, 'w', encoding='utf-8') as f:
        f.write(content)
    os.replace(tmppath, filepath)

def hex_color(h, l, s):
    r, g, b = colorsys.hls_to_rgb(h % 1.0, max(0.0, min(1.0, l)), max(0.0, min(1.0, s)))
    return f"#{int(r*255):02X}{int(g*255):02X}{int(b*255):02X}"

def rgba_color(h, l, s, a):
    r, g, b = colorsys.hls_to_rgb(h % 1.0, max(0.0, min(1.0, l)), max(0.0, min(1.0, s)))
    return f"rgba({int(r*255)}, {int(g*255)}, {int(b*255)}, {a})"

def get_current_color_scheme():
    """Retrieve active color scheme (prefer-dark vs default/prefer-light)."""
    try:
        iface = Gio.Settings.new('org.gnome.desktop.interface')
        return iface.get_string('color-scheme')
    except Exception:
        return 'prefer-dark'

def get_current_wallpaper():
    """Retrieve active wallpaper path from GNOME GSettings according to active color scheme."""
    try:
        bg = Gio.Settings.new('org.gnome.desktop.background')
        scheme = get_current_color_scheme()
        if scheme == 'prefer-dark':
            uri = bg.get_string('picture-uri-dark')
            if not uri or uri == 'none':
                uri = bg.get_string('picture-uri')
        else:
            uri = bg.get_string('picture-uri')
            if not uri or uri == 'none':
                uri = bg.get_string('picture-uri-dark')

        parsed = urllib.parse.urlparse(uri)
        path = urllib.parse.unquote(parsed.path)
        if os.path.isfile(path):
            return path
    except Exception as e:
        print(f"[Monet] Failed to query wallpaper: {e}", file=sys.stderr)
    return None

def extract_palette(image_path, scheme='prefer-dark'):
    """
    Extract M3 Monet Glass tonal palette using 36-bin circular Hue Histogram
    + Spatial Center/Top-Bar Weighting + Area-Chroma Clustering.
    Prevents small high-saturation noise pixels from hijacking the dominant wallpaper theme,
    and extracts both a Primary Hue (h) and a Secondary Specular Hue (h2) for iridescent glass.
    """
    import math
    is_dark = (scheme == 'prefer-dark')
    h, s, l_avg = 0.58, 0.42, 0.45
    h2, s2 = 0.64, 0.38

    if image_path and os.path.isfile(image_path):
        try:
            img = Image.open(image_path).convert('RGB')
            w_size, h_size = 96, 96
            img = img.resize((w_size, h_size), Image.Resampling.BILINEAR)
            try:
                pixels = list(img.get_flattened_data())
            except AttributeError:
                pixels = list(img.getdata())

            num_bins = 36  # 10 degrees per bin
            bin_weights = [0.0] * num_bins
            bin_samples = [[] for _ in range(num_bins)]

            for idx, p in enumerate(pixels):
                r, g, b = p[:3]
                ph, pl, ps = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
                # Filter out near-black, near-white, and achromatic grey pixels
                if 0.10 < pl < 0.90 and ps > 0.10:
                    y_norm = (idx // w_size) / float(h_size)
                    x_norm = (idx % w_size) / float(w_size)
                    # Gentle visual salience bias: center subject + top bar contact region
                    center_bias = 1.0 + 0.18 * (1.0 - abs(x_norm - 0.5) * 2.0)
                    top_bias = 1.12 if y_norm < 0.20 else 1.0
                    # Area-accumulated perceptual weight (sub-linear saturation prevents 1-pixel neon hijack)
                    chroma_score = (ps ** 0.72) * (1.0 - 0.65 * abs(pl - 0.50))
                    w = chroma_score * center_bias * top_bias

                    b_idx = int(ph * num_bins) % num_bins
                    bin_weights[b_idx] += w
                    bin_samples[b_idx].append((ph, pl, ps, w))

            total_weight = sum(bin_weights)
            if total_weight > 0:
                # Circular 5-tap Gaussian smoothing across adjacent 10-deg hue bins
                smoothed = [0.0] * num_bins
                kernel = [(-2, 0.12), (-1, 0.24), (0, 0.38), (1, 0.24), (2, 0.12)]
                for i in range(num_bins):
                    smoothed[i] = sum(bin_weights[(i + offset) % num_bins] * kw for offset, kw in kernel)

                peak_bin = max(range(num_bins), key=lambda i: smoothed[i])

                # Gather cluster samples within +-2 bins (+-20 deg) of the winning peak
                cluster_samples = []
                for offset in (-2, -1, 0, 1, 2):
                    cluster_samples.extend(bin_samples[(peak_bin + offset) % num_bins])

                if cluster_samples:
                    cw_sum = sum(item[3] for item in cluster_samples)
                    sin_sum = sum(math.sin(2.0 * math.pi * item[0]) * item[3] for item in cluster_samples)
                    cos_sum = sum(math.cos(2.0 * math.pi * item[0]) * item[3] for item in cluster_samples)
                    h = (math.atan2(sin_sum, cos_sum) / (2.0 * math.pi)) % 1.0
                    s = sum(item[2] * item[3] for item in cluster_samples) / cw_sum
                    l_avg = sum(item[1] * item[3] for item in cluster_samples) / cw_sum
                    # Boost saturation moderately so dark/muted wallpapers still produce lively Monet glass
                    s = max(0.28, min(0.82, s * 1.15))

                # Find a secondary harmonic/contrast hue peak (>= 35 deg away) for glass specular iridescence
                secondary_candidates = []
                for i in range(num_bins):
                    dist = min((i - peak_bin) % num_bins, (peak_bin - i) % num_bins)
                    if dist >= 4 and smoothed[i] > smoothed[peak_bin] * 0.14:
                        secondary_candidates.append((smoothed[i], i))
                if secondary_candidates:
                    secondary_candidates.sort(reverse=True)
                    sec_bin = secondary_candidates[0][1]
                    sec_samples = []
                    for offset in (-1, 0, 1):
                        sec_samples.extend(bin_samples[(sec_bin + offset) % num_bins])
                    if sec_samples:
                        sw_sum = sum(item[3] for item in sec_samples)
                        s_sin = sum(math.sin(2.0 * math.pi * item[0]) * item[3] for item in sec_samples)
                        s_cos = sum(math.cos(2.0 * math.pi * item[0]) * item[3] for item in sec_samples)
                        h2 = (math.atan2(s_sin, s_cos) / (2.0 * math.pi)) % 1.0
                        s2 = max(0.30, min(0.78, sum(item[2] * item[3] for item in sec_samples) / sw_sum))
                    else:
                        h2, s2 = (h + 0.07) % 1.0, s
                else:
                    h2, s2 = (h + 0.07) % 1.0, s
        except Exception as e:
            print(f"[Monet] Error processing image: {e}", file=sys.stderr)

    def rgb_tuple(hv, lv, sv):
        rr, gg, bb = colorsys.hls_to_rgb(hv % 1.0, max(0.0, min(1.0, lv)), max(0.0, min(1.0, sv)))
        return int(round(rr * 255)), int(round(gg * 255)), int(round(bb * 255))

    def rgb_str(hv, lv, sv):
        rr, gg, bb = rgb_tuple(hv, lv, sv)
        return f"{rr}, {gg}, {bb}"

    if is_dark:
        # Dark Mode Liquid / Frosted Glass Palette
        # Top of glass catches overhead light (brighter, slightly higher saturation & secondary hue blend)
        glass_top_rgb = rgb_str(h, 0.24, min(s * 0.85, 0.52))
        glass_bot_rgb = rgb_str(h, 0.12, min(s * 0.70, 0.38))
        glass_top = f"rgba({glass_top_rgb}, 0.56)"
        glass_bottom = f"rgba({glass_bot_rgb}, 0.38)"

        # Maximized panel (#panel.solid) smoked glass gradient
        panel_solid_top = f"rgba({rgb_str(h, 0.16, min(s * 0.65, 0.35))}, 0.76)"
        panel_solid_bot = f"rgba({rgb_str(h, 0.10, min(s * 0.55, 0.28))}, 0.62)"

        # Specular rim & inner reflection highlight
        rim_rgb = rgb_str(h, 0.82, min(s * 1.15, 0.78))
        specular_rgb = rgb_str(h2, 0.92, min(s2 * 0.90, 0.65))
        glass_border = f"rgba({rim_rgb}, 0.38)"
        glass_inner_shadow = f"inset 0 1px 2px rgba({specular_rgb}, 0.34)"

        # Hover & Active glass states
        hover_top = f"rgba({rgb_str(h, 0.36, min(s * 1.05, 0.68))}, 0.68)"
        hover_bot = f"rgba({rgb_str(h2, 0.22, min(s2 * 0.95, 0.58))}, 0.48)"
        active_top = f"rgba({rgb_str(h, 0.46, min(s * 1.15, 0.76))}, 0.78)"
        active_bot = f"rgba({rgb_str(h2, 0.30, min(s2 * 1.05, 0.68))}, 0.58)"

        # Popup menu & Quick Settings frosted glass
        popup_top = f"rgba({rgb_str(h, 0.19, min(s * 0.75, 0.42))}, 0.84)"
        popup_bot = f"rgba({rgb_str(h, 0.11, min(s * 0.65, 0.32))}, 0.74)"
        card_glass_top = f"rgba({rgb_str(h, 0.26, min(s * 0.70, 0.40))}, 0.42)"
        card_glass_bot = f"rgba({rgb_str(h, 0.17, min(s * 0.60, 0.32))}, 0.28)"

        bg_surface = f"rgba({glass_top_rgb}, 0.54)"
        bg_solid = popup_top
        bg_overview = f"rgba({rgb_str(h, 0.10, min(s * 0.5, 0.25))}, 0.38)"

        accent_rgb = rgb_str(h, 0.78, min(s * 1.15, 0.76))
        text_color = f"rgb({rgb_str(h, 0.96, min(s, 0.16))})"
        hover_text = "#ffffff"
        text_shadow = "0 1px 3px rgba(0, 0, 0, 0.48)"
        icon_shadow = "0 1px 2px rgba(0, 0, 0, 0.42)"
    else:
        # Light Mode Crystal Pearl Glass Palette
        glass_top_rgb = rgb_str(h, 0.98, min(s * 0.55, 0.35))
        glass_bot_rgb = rgb_str(h, 0.90, min(s * 0.70, 0.42))
        glass_top = f"rgba({glass_top_rgb}, 0.72)"
        glass_bottom = f"rgba({glass_bot_rgb}, 0.52)"

        panel_solid_top = f"rgba({rgb_str(h, 0.96, min(s * 0.50, 0.30))}, 0.84)"
        panel_solid_bot = f"rgba({rgb_str(h, 0.90, min(s * 0.60, 0.35))}, 0.72)"

        rim_rgb = rgb_str(h, 0.52, min(s * 1.10, 0.72))
        specular_rgb = "255, 255, 255"
        glass_border = f"rgba(255, 255, 255, 0.68)"
        glass_inner_shadow = f"inset 0 1px 2px rgba(255, 255, 255, 0.80)"

        hover_top = f"rgba({rgb_str(h, 0.92, min(s * 0.85, 0.55))}, 0.82)"
        hover_bot = f"rgba({rgb_str(h2, 0.84, min(s2 * 0.85, 0.55))}, 0.66)"
        active_top = f"rgba({rgb_str(h, 0.85, min(s * 1.0, 0.68))}, 0.88)"
        active_bot = f"rgba({rgb_str(h2, 0.76, min(s2 * 0.95, 0.62))}, 0.74)"

        popup_top = f"rgba({rgb_str(h, 0.97, min(s * 0.50, 0.32))}, 0.88)"
        popup_bot = f"rgba({rgb_str(h, 0.91, min(s * 0.60, 0.38))}, 0.78)"
        card_glass_top = f"rgba(255, 255, 255, 0.62)"
        card_glass_bot = f"rgba({rgb_str(h, 0.92, min(s * 0.55, 0.35))}, 0.44)"

        bg_surface = f"rgba({glass_top_rgb}, 0.68)"
        bg_solid = popup_top
        bg_overview = f"rgba({rgb_str(h, 0.94, min(s * 0.4, 0.25))}, 0.32)"

        accent_rgb = rgb_str(h, 0.42, min(s * 1.15, 0.78))
        text_color = f"rgb({rgb_str(h, 0.14, min(s, 0.22))})"
        hover_text = text_color
        text_shadow = "0 1px 2px rgba(255, 255, 255, 0.55)"
        icon_shadow = "0 1px 2px rgba(255, 255, 255, 0.45)"

    return {
        'bg_surface': bg_surface,
        'bg_solid': bg_solid,
        'bg_overview': bg_overview,
        'glass_top': glass_top,
        'glass_bottom': glass_bottom,
        'panel_solid_top': panel_solid_top,
        'panel_solid_bot': panel_solid_bot,
        'rim_rgb': rim_rgb,
        'specular_rgb': specular_rgb,
        'glass_border': glass_border,
        'glass_inner_shadow': glass_inner_shadow,
        'hover_top': hover_top,
        'hover_bot': hover_bot,
        'active_top': active_top,
        'active_bot': active_bot,
        'popup_top': popup_top,
        'popup_bot': popup_bot,
        'card_glass_top': card_glass_top,
        'card_glass_bot': card_glass_bot,
        'accent_rgb': accent_rgb,
        'text_color': text_color,
        'hover_text': hover_text,
        'text_shadow': text_shadow,
        'icon_shadow': icon_shadow,
        'is_dark': is_dark,
        'hue': round(h * 360, 1),
        'hue2': round(h2 * 360, 1),
        'h_val': h,
        's_val': s,
        'l_val': l_avg,
    }

def generate_gnome_shell_css(palette):
    """Generate M3 Monet Liquid/Frosted Glass stylesheet for GNOME Shell (Top bar + Quick Settings + Popups)."""
    hover_text = palette.get('hover_text', '#ffffff')
    return f"""/* GNOME Shell Material Design 3 (M3) Monet Liquid & Frosted Glass Theme */

.quick-settings .user-icon {{
  icon-size: 5em;
}}

.quick-settings .user-widget {{
  spacing: 36px;
  padding-bottom: 12px;
}}

.quick-settings .user-widget-label {{
  font-size: x-large;
  font-weight: normal;
}}

/* =========================================================
   1. Main Top Bar: Floating Crystal Container
   ========================================================= */
#panel {{
  background-color: transparent !important;
  background-gradient-direction: none !important;
  box-shadow: none !important;
  border: none !important;
  font-family: 'Google Sans', sans-serif !important;
  height: 2.55em !important;
  padding: 4px 8px !important;
  transition: background-color 260ms cubic-bezier(0.2, 0, 0, 1), box-shadow 260ms ease !important;
}}

/* Maximized window state: Smoked Monet Glass Top Bar */
#panel.solid {{
  background-color: {palette['panel_solid_bot']} !important;
  background-gradient-direction: vertical !important;
  background-gradient-start: {palette['panel_solid_top']} !important;
  background-gradient-end: {palette['panel_solid_bot']} !important;
  border-bottom: 1px solid rgba({palette['rim_rgb']}, 0.24) !important;
  box-shadow: inset 0 1px 1px rgba({palette['specular_rgb']}, 0.22) !important;
}}

/* =========================================================
   2. Floating Monet Glass Capsule Pills (Dual-Stop Specular Refraction)
   ========================================================= */
#panel .panel-button {{
  background-color: {palette['bg_surface']} !important;
  background-gradient-direction: vertical !important;
  background-gradient-start: {palette['glass_top']} !important;
  background-gradient-end: {palette['glass_bottom']} !important;
  border: 1px solid {palette['glass_border']} !important;
  border-radius: 999px !important;
  box-shadow: {palette['glass_inner_shadow']} !important;
  color: {palette['text_color']} !important;
  text-shadow: {palette['text_shadow']} !important;
  icon-shadow: {palette['icon_shadow']} !important;
  font-family: 'Google Sans', sans-serif !important;
  font-weight: 600 !important;
  margin: 2px 4px !important;
  padding: 0 15px !important;
  transition: background-color 240ms cubic-bezier(0.2, 0, 0, 1), border-color 240ms cubic-bezier(0.2, 0, 0, 1), color 240ms ease, box-shadow 240ms ease !important;
}}

/* 3. Pill Hover - Iridescent Specular Glass Glow */
#panel .panel-button:focus,
#panel .panel-button:hover {{
  background-color: {palette['hover_top']} !important;
  background-gradient-direction: vertical !important;
  background-gradient-start: {palette['hover_top']} !important;
  background-gradient-end: {palette['hover_bot']} !important;
  border-color: rgba({palette['rim_rgb']}, 0.68) !important;
  box-shadow: inset 0 1px 3px rgba({palette['specular_rgb']}, 0.52) !important;
  color: {hover_text} !important;
}}

/* 4. Pill Active / Checked - Deep Refractive Monet Glass */
#panel .panel-button:active,
#panel .panel-button:checked,
#panel .panel-button:overview {{
  background-color: {palette['active_top']} !important;
  background-gradient-direction: vertical !important;
  background-gradient-start: {palette['active_top']} !important;
  background-gradient-end: {palette['active_bot']} !important;
  border-color: rgba({palette['rim_rgb']}, 0.85) !important;
  box-shadow: inset 0 1px 3px rgba(255, 255, 255, 0.55) !important;
  color: {hover_text} !important;
}}

/* 5. Center Date / Time & System Status Icons */
#panel .clock-display {{
  font-weight: 600 !important;
  letter-spacing: 0.35px !important;
}}

#panel .system-status-icon {{
  icon-shadow: {palette['icon_shadow']} !important;
}}

/* =========================================================
   6. M3 Frosted Glass Popups, Quick Settings & Calendar Cards
   ========================================================= */
.popup-menu,
.popup-menu-boxpointer {{
  background-color: transparent !important;
  background: none !important;
  box-shadow: none !important;
  border: none !important;
}}

.popup-menu-content {{
  background-color: {palette['popup_bot']} !important;
  background-gradient-direction: vertical !important;
  background-gradient-start: {palette['popup_top']} !important;
  background-gradient-end: {palette['popup_bot']} !important;
  border: 1px solid rgba({palette['rim_rgb']}, 0.38) !important;
  border-radius: 26px !important;
  box-shadow: inset 0 1px 2px rgba({palette['specular_rgb']}, 0.30) !important;
  padding: 14px !important;
  color: {palette['text_color']} !important;
  font-family: 'Google Sans', sans-serif !important;
  transition: background-color 240ms ease, border-color 240ms ease !important;
}}

.quick-settings {{
  border-radius: 28px !important;
}}

/* Quick Settings Toggles & Calendar Cards as Inner Glass Tiles */
.quick-toggle,
.quick-menu-toggle .quick-toggle,
.events-button,
.world-clocks-button,
.weather-button,
.message {{
  background-color: {palette['card_glass_bot']} !important;
  background-gradient-direction: vertical !important;
  background-gradient-start: {palette['card_glass_top']} !important;
  background-gradient-end: {palette['card_glass_bot']} !important;
  border: 1px solid rgba({palette['rim_rgb']}, 0.22) !important;
  box-shadow: inset 0 1px 1px rgba({palette['specular_rgb']}, 0.18) !important;
  border-radius: 18px !important;
}}

.quick-toggle:hover,
.quick-menu-toggle .quick-toggle:hover,
.events-button:hover,
.world-clocks-button:hover,
.weather-button:hover,
.message:hover {{
  background-gradient-start: {palette['hover_top']} !important;
  background-gradient-end: {palette['hover_bot']} !important;
  border-color: rgba({palette['rim_rgb']}, 0.45) !important;
}}

.quick-toggle:checked,
.quick-menu-toggle .quick-toggle:checked {{
  background-color: {palette['active_top']} !important;
  background-gradient-direction: vertical !important;
  background-gradient-start: {palette['active_top']} !important;
  background-gradient-end: {palette['active_bot']} !important;
  border: 1px solid rgba({palette['rim_rgb']}, 0.72) !important;
  box-shadow: inset 0 1px 2px rgba(255, 255, 255, 0.42) !important;
  color: {hover_text} !important;
}}

.popup-menu-content .popup-menu-item {{
  border-radius: 14px !important;
  margin: 1px 0 !important;
  transition: background-color 150ms ease !important;
}}

.popup-menu-content .popup-menu-item:hover,
.popup-menu-content .popup-menu-item:focus {{
  background-color: rgba({palette['accent_rgb']}, 0.22) !important;
  color: {hover_text} !important;
}}
"""

def apply_ptyxis_palette(palette):
    """Generate and apply Monet palette for Ptyxis terminal."""
    try:
        h = palette['h_val']
        s = palette['s_val']

        bg = hex_color(h, 0.11, min(s * 1.1, 0.28))
        fg = hex_color(h, 0.90, min(s, 0.10))
        cursor = hex_color(h, 0.78, min(s * 1.1, 0.75))

        c0 = hex_color(h, 0.15, min(s, 0.15))
        c1 = "#FF897D"
        c2 = hex_color(0.32, 0.75, 0.45)
        c3 = hex_color(h, 0.78, min(s * 1.2, 0.75))
        c4 = hex_color(0.58, 0.75, 0.55)
        c5 = hex_color(0.82, 0.75, 0.45)
        c6 = hex_color(0.48, 0.75, 0.45)
        c7 = fg

        c8  = hex_color(h, 0.45, min(s, 0.15))
        c9  = "#FFB4AB"
        c10 = hex_color(0.32, 0.85, 0.45)
        c11 = hex_color(h, 0.86, min(s * 1.2, 0.80))
        c12 = hex_color(0.58, 0.85, 0.60)
        c13 = hex_color(0.82, 0.85, 0.50)
        c14 = hex_color(0.48, 0.85, 0.50)
        c15 = "#FFFFFF"

        palette_content = f"""[Palette]
Name=Monet
Background={bg}
Foreground={fg}
Cursor={cursor}
Color0={c0}
Color1={c1}
Color2={c2}
Color3={c3}
Color4={c4}
Color5={c5}
Color6={c6}
Color7={c7}
Color8={c8}
Color9={c9}
Color10={c10}
Color11={c11}
Color12={c12}
Color13={c13}
Color14={c14}
Color15={c15}
"""
        atomic_write(PTYXIS_PALETTE_PATH, palette_content)

        prof_cmd = ['gsettings', 'get', 'org.gnome.Ptyxis', 'default-profile-uuid']
        prof_uuid = subprocess.check_output(prof_cmd, stderr=subprocess.DEVNULL).decode().strip().strip("'")
        if prof_uuid:
            key_path = f"org.gnome.Ptyxis.Profile:/org/gnome/Ptyxis/Profiles/{prof_uuid}/"
            subprocess.run(['gsettings', 'set', key_path, 'palette', 'monet'], stderr=subprocess.DEVNULL)
            subprocess.run(['gsettings', 'set', key_path, 'opacity', '0.94'], stderr=subprocess.DEVNULL)
            print(f"[Monet] Configured Ptyxis terminal profile (Opacity: 0.94, Palette: Monet)")
    except Exception as e:
        print(f"[Monet] Failed to apply Ptyxis palette: {e}", file=sys.stderr)

def get_gnome_accent_enum(hue_deg):
    """Map hue to closest GNOME native accent color."""
    if 345 <= hue_deg or hue_deg < 15:
        return 'red'
    elif 15 <= hue_deg < 42:
        return 'orange'
    elif 42 <= hue_deg < 68:
        return 'yellow'
    elif 68 <= hue_deg < 155:
        return 'green'
    elif 155 <= hue_deg < 195:
        return 'teal'
    elif 195 <= hue_deg < 250:
        return 'blue'
    elif 250 <= hue_deg < 290:
        return 'purple'
    elif 290 <= hue_deg < 345:
        return 'pink'
    return 'blue'

def apply_gtk_theme(palette):
    """Generate and apply Monet colors for all Libadwaita / GTK4 & GTK3 apps with 0.92 Acrylic translucency."""
    try:
        h = palette['h_val']
        s = palette['s_val']
        hue_deg = palette['hue']
        is_dark = palette.get('is_dark', True)

        # 1. Update native GNOME Accent Color (Folder icons, switches) directly via Gio.Settings
        accent_enum = get_gnome_accent_enum(hue_deg)
        try:
            iface = Gio.Settings.new('org.gnome.desktop.interface')
            iface.set_string('accent-color', accent_enum)
        except Exception:
            subprocess.run(['gsettings', 'set', 'org.gnome.desktop.interface', 'accent-color', accent_enum], stderr=subprocess.DEVNULL)

        # 2. Derive pixel-perfect Libadwaita named colors with translucent alpha (0.92)
        if is_dark:
            accent_color = hex_color(h, 0.76, min(s * 1.25, 0.82))
            accent_fg = hex_color(h, 0.12, 0.20)
            window_bg = rgba_color(h, 0.12, min(s * 1.1, 0.28), 0.92)
            window_fg = hex_color(h, 0.90, min(s, 0.10))
            view_bg = rgba_color(h, 0.09, min(s * 1.1, 0.28), 0.92)
            card_bg = rgba_color(h, 0.16, min(s * 1.0, 0.25), 0.92)
            header_bg = rgba_color(h, 0.12, min(s * 1.1, 0.28), 0.92)
            sidebar_bg = rgba_color(h, 0.10, min(s * 1.1, 0.28), 0.92)
            secondary_sidebar_bg = rgba_color(h, 0.08, min(s * 1.1, 0.28), 0.92)
        else:
            accent_color = hex_color(h, 0.44, min(s * 1.25, 0.80))
            accent_fg = "#FFFFFF"
            window_bg = rgba_color(h, 0.95, min(s * 0.9, 0.25), 0.92)
            window_fg = hex_color(h, 0.13, min(s, 0.18))
            view_bg = rgba_color(h, 0.98, min(s * 0.8, 0.20), 0.92)
            card_bg = rgba_color(h, 0.99, min(s * 0.7, 0.18), 0.94)
            header_bg = rgba_color(h, 0.94, min(s * 0.9, 0.25), 0.92)
            sidebar_bg = rgba_color(h, 0.92, min(s * 0.9, 0.25), 0.92)
            secondary_sidebar_bg = rgba_color(h, 0.90, min(s * 0.9, 0.25), 0.92)

        gtk_css = f"""/* Libadwaita GTK4 / GTK3 Material You (M3) Monet Dynamic Theme with Translucency */

@define-color accent_color {accent_color};
@define-color accent_bg_color {accent_color};
@define-color accent_fg_color {accent_fg};

@define-color window_bg_color {window_bg};
@define-color window_fg_color {window_fg};

@define-color view_bg_color {view_bg};
@define-color view_fg_color {window_fg};

@define-color headerbar_bg_color {header_bg};
@define-color headerbar_fg_color {window_fg};
@define-color headerbar_border_color rgba({palette['accent_rgb']}, 0.15);
@define-color headerbar_backdrop_color {header_bg};

@define-color sidebar_bg_color {sidebar_bg};
@define-color sidebar_fg_color {window_fg};
@define-color sidebar_backdrop_color {sidebar_bg};
@define-color sidebar_border_color rgba({palette['accent_rgb']}, 0.15);

@define-color secondary_sidebar_bg_color {secondary_sidebar_bg};
@define-color secondary_sidebar_fg_color {window_fg};
@define-color secondary_sidebar_backdrop_color {secondary_sidebar_bg};
@define-color secondary_sidebar_border_color rgba({palette['accent_rgb']}, 0.15);

@define-color card_bg_color {card_bg};
@define-color card_fg_color {window_fg};
@define-color card_border_color rgba({palette['accent_rgb']}, 0.12);

@define-color popover_bg_color {card_bg};
@define-color popover_fg_color {window_fg};

@define-color dialog_bg_color {card_bg};
@define-color dialog_fg_color {window_fg};

/* 1. Window Background: 0.92 Translucent Acrylic Tint */
window.background {{
  background-color: @window_bg_color;
}}

/* 2. Headerbars: Translucent matching window */
headerbar,
.titlebar {{
  background-color: @headerbar_bg_color;
}}

/* 3. Eliminate Popover / Context Menu Rectangular Ghost Box */
popover,
popover.background {{
  background-color: transparent;
  box-shadow: none;
}}

popover > contents {{
  background-color: @popover_bg_color;
  border-radius: 14px;
  border: 1px solid rgba({palette['accent_rgb']}, 0.18);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.45);
}}

/* 4. Nautilus & Libadwaita Sidebars: Translucent Monet Tint */
.sidebar-pane,
.sidebar,
placessidebar,
navigation-sidebar,
.navigation-sidebar {{
  background-color: @sidebar_bg_color;
  color: @sidebar_fg_color;
}}

.navigation-sidebar row:hover,
placessidebar row:hover {{
  background-color: rgba({palette['accent_rgb']}, 0.14);
  border-radius: 10px;
}}

.navigation-sidebar row:selected,
placessidebar row:selected {{
  background-color: rgba({palette['accent_rgb']}, 0.25);
  color: @accent_color;
  border-radius: 10px;
}}

/* 5. Text Editor, Terminal & Views: Allow translucent window background to shine through */
textview,
textview text,
.view {{
  background-color: transparent;
  color: @window_fg_color;
}}

/* 6. Nautilus / File Manager views */
.nautilus-window .view,
.nautilus-window gridview,
.nautilus-window columnview,
.nautilus-window listview,
.nautilus-window scrolledwindow {{
  background-color: transparent;
}}
"""
        # Write atomically to GTK4 & GTK3
        atomic_write(GTK4_CSS_PATH, gtk_css)
        atomic_write(GTK3_CSS_PATH, gtk_css)

        print(f"[Monet] Applied GTK/Libadwaita theme (Accent: {accent_enum} / {accent_color})")
    except Exception as e:
        print(f"[Monet] Failed to apply GTK theme: {e}", file=sys.stderr)

def reload_shell_stylesheet():
    """Reload GNOME Shell extension stylesheet with minimal latency (or zero-flicker hot reload)."""
    try:
        shell_settings = Gio.Settings.new('org.gnome.shell')
        if shell_settings.get_boolean('disable-user-extensions'):
            shell_settings.set_boolean('disable-user-extensions', False)

        # If in-process St.Theme hot-reload monitor is active in extension.js, no D-Bus toggle needed
        runtime_dir = os.environ.get('XDG_RUNTIME_DIR') or f"/run/user/{os.getuid()}"
        if (
            os.path.exists(os.path.join(runtime_dir, 'monet-hot-reload-active'))
            or os.path.exists(os.path.join(runtime_dir, 'live-wallpaper-occluded'))
        ):
            return

        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        # Check if GNOME Shell is actually running on the session bus before calling Extensions D-Bus
        has_owner = bus.call_sync(
            'org.freedesktop.DBus',
            '/org/freedesktop/DBus',
            'org.freedesktop.DBus',
            'NameHasOwner',
            GLib.Variant('(s)', ('org.gnome.Shell',)),
            GLib.VariantType.new('(b)'),
            Gio.DBusCallFlags.NONE,
            500,
            None,
        )
        if not has_owner or not has_owner.unpack()[0]:
            # GNOME Shell is still starting up; it will load stylesheet.css automatically upon extension init
            return

        bus.call_sync(
            'org.gnome.Shell.Extensions',
            '/org/gnome/Shell/Extensions',
            'org.gnome.Shell.Extensions',
            'DisableExtension',
            GLib.Variant('(s)', (EXTENSION_UUID,)),
            None,
            Gio.DBusCallFlags.NONE,
            1000,
            None,
        )
        bus.call_sync(
            'org.gnome.Shell.Extensions',
            '/org/gnome/Shell/Extensions',
            'org.gnome.Shell.Extensions',
            'EnableExtension',
            GLib.Variant('(s)', (EXTENSION_UUID,)),
            None,
            Gio.DBusCallFlags.NONE,
            1000,
            None,
        )
    except Exception as e:
        print(f"[Monet] Fallback extension reload: {e}", file=sys.stderr)
        subprocess.run(['gnome-extensions', 'enable', EXTENSION_UUID], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def apply_all(force=False):
    """Extract and distribute Monet palette everywhere across the system."""
    global _last_applied_state
    wp = get_current_wallpaper()
    scheme = get_current_color_scheme()
    current_state = (wp, scheme)

    if not force and _last_applied_state == current_state:
        print(f"[Monet] Wallpaper and color scheme unchanged ({wp}, {scheme}). Skipping reload.")
        return

    if not wp:
        print("[Monet] No wallpaper found, using default palette.")
        palette = extract_palette(None, scheme)
    else:
        print(f"[Monet] Extracting colors from: {wp} (Scheme: {scheme})")
        palette = extract_palette(wp, scheme)

    # 1. GNOME Shell Top Bar + Overview
    css = generate_gnome_shell_css(palette)
    atomic_write(CSS_PATH, css)
    reload_shell_stylesheet()

    # 2. Terminal
    apply_ptyxis_palette(palette)

    # 3. GTK / Libadwaita Applications (Translucency + Monet theme)
    apply_gtk_theme(palette)

    _last_applied_state = current_state
    print(f"[Monet] Successfully synchronized entire system to Monet palette (Hue: {palette['hue']}deg)!")

def watch_wallpaper():
    """Watch for wallpaper changes using native Gio.Settings signals."""
    print("[Monet] Starting wallpaper monitor daemon with native Gio.Settings signals...")
    apply_all(force=True)

    bg_settings = Gio.Settings.new('org.gnome.desktop.background')
    iface_settings = Gio.Settings.new('org.gnome.desktop.interface')

    state = {'timer_id': 0}

    def on_change(settings, key):
        print(f"[Monet] Detected change on setting '{key}', debouncing...")
        if state['timer_id'] != 0:
            GLib.source_remove(state['timer_id'])
            state['timer_id'] = 0

        def do_reload():
            state['timer_id'] = 0
            apply_all(force=False)
            return False

        state['timer_id'] = GLib.timeout_add(300, do_reload)

    bg_settings.connect('changed::picture-uri-dark', on_change)
    bg_settings.connect('changed::picture-uri', on_change)
    iface_settings.connect('changed::color-scheme', on_change)

    loop = GLib.MainLoop()
    try:
        loop.run()
    except (KeyboardInterrupt, SystemExit):
        loop.quit()

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] in ('--watch', '-w', '--daemon'):
        watch_wallpaper()
    else:
        apply_all(force=True)
