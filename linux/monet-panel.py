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
    """Extract M3 tonal palette from image (supports both Dark and Light color schemes)."""
    is_dark = (scheme == 'prefer-dark')
    try:
        img = Image.open(image_path).convert('RGB')
        img = img.resize((64, 64))
        
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
                scored.append((score, (r, g, b), (h, l, s)))

        if scored:
            scored.sort(key=lambda x: x[0], reverse=True)
            h, _, s = scored[0][2]
        else:
            h, s = 0.58, 0.35
    except Exception as e:
        print(f"[Monet] Error processing image: {e}", file=sys.stderr)
        h, s = 0.58, 0.35

    if is_dark:
        # Dark M3 Tonal Surface
        sr, sg, sb = colorsys.hls_to_rgb(h, 0.14, min(s, 0.22))
        bg_surface = f"rgba({int(sr*255)}, {int(sg*255)}, {int(sb*255)}, 0.82)"
        bg_solid = f"rgba({int(sr*255)}, {int(sg*255)}, {int(sb*255)}, 0.95)"
        bg_overview = f"rgba({int(sr*255*0.65)}, {int(sg*255*0.65)}, {int(sb*255*0.65)}, 0.40)"

        ar, ag, ab = colorsys.hls_to_rgb(h, 0.78, min(s * 1.1, 0.72))
        accent_rgb = f"{int(ar*255)}, {int(ag*255)}, {int(ab*255)}"

        tr, tg, tb = colorsys.hls_to_rgb(h, 0.94, min(s, 0.12))
        text_color = f"rgb({int(tr*255)}, {int(tg*255)}, {int(tb*255)})"
        hover_text = "#ffffff"
    else:
        # Light M3 Tonal Surface
        sr, sg, sb = colorsys.hls_to_rgb(h, 0.94, min(s, 0.25))
        bg_surface = f"rgba({int(sr*255)}, {int(sg*255)}, {int(sb*255)}, 0.85)"
        bg_solid = f"rgba({int(sr*255)}, {int(sg*255)}, {int(sb*255)}, 0.96)"
        bg_overview = f"rgba({int(sr*255)}, {int(sg*255)}, {int(sb*255)}, 0.35)"

        ar, ag, ab = colorsys.hls_to_rgb(h, 0.42, min(s * 1.15, 0.75))
        accent_rgb = f"{int(ar*255)}, {int(ag*255)}, {int(ab*255)}"

        tr, tg, tb = colorsys.hls_to_rgb(h, 0.14, min(s, 0.18))
        text_color = f"rgb({int(tr*255)}, {int(tg*255)}, {int(tb*255)})"
        hover_text = text_color

    return {
        'bg_surface': bg_surface,
        'bg_solid': bg_solid,
        'bg_overview': bg_overview,
        'accent_rgb': accent_rgb,
        'text_color': text_color,
        'hover_text': hover_text,
        'is_dark': is_dark,
        'hue': round(h * 360, 1),
        'h_val': h,
        's_val': s
    }

def generate_gnome_shell_css(palette):
    """Generate M3 stylesheet for GNOME Shell (Top bar + Overview)."""
    hover_text = palette.get('hover_text', '#ffffff')
    return f"""/* GNOME Shell Material Design 3 (M3 / Material You) Monet Dynamic Theme */

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
   1. Main Top Bar: Transparent & Floating
   ========================================================= */
#panel {{
  background-color: transparent !important;
  box-shadow: none !important;
  font-family: 'Google Sans', sans-serif !important;
  height: 2.5em !important;
  padding: 4px 8px !important;
  transition: background-color 280ms cubic-bezier(0.2, 0, 0, 1), box-shadow 280ms ease !important;
}}

#panel.solid {{
  background-color: {palette['bg_surface']} !important;
  box-shadow: 0 1px 8px rgba(0, 0, 0, 0.25) !important;
}}

/* 2. Floating Monet Capsule Pills */
#panel .panel-button {{
  background-color: {palette['bg_surface']} !important;
  border: 1px solid rgba({palette['accent_rgb']}, 0.16) !important;
  border-radius: 999px !important;
  color: {palette['text_color']} !important;
  font-family: 'Google Sans', sans-serif !important;
  font-weight: 500 !important;
  margin: 2px 4px !important;
  padding: 0 14px !important;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.25) !important;
  transition: background-color 260ms cubic-bezier(0.2, 0, 0, 1), border-color 260ms cubic-bezier(0.2, 0, 0, 1), color 260ms ease, box-shadow 260ms ease !important;
}}

/* 3. Pill Hover - Monet Tonal Surface Accent */
#panel .panel-button:focus,
#panel .panel-button:hover {{
  background-color: rgba({palette['accent_rgb']}, 0.22) !important;
  border-color: rgba({palette['accent_rgb']}, 0.55) !important;
  color: {hover_text} !important;
  box-shadow: 0 4px 12px rgba({palette['accent_rgb']}, 0.25) !important;
}}

/* 4. Pill Active / Clicked */
#panel .panel-button:active,
#panel .panel-button:checked {{
  background-color: rgba({palette['accent_rgb']}, 0.38) !important;
  border-color: rgba({palette['accent_rgb']}, 0.75) !important;
  color: {hover_text} !important;
}}

/* 5. Center Date / Time Indicator */
#panel .clock-display {{
  font-weight: 500 !important;
  letter-spacing: 0.3px !important;
}}

/* 6. M3 Popup Menus & Quick Settings Panel */
.popup-menu,
.popup-menu-boxpointer {{
  background-color: transparent !important;
  background: none !important;
  box-shadow: none !important;
  border: none !important;
}}

.popup-menu-content {{
  background-color: {palette['bg_solid']} !important;
  border: 1px solid rgba({palette['accent_rgb']}, 0.25) !important;
  border-radius: 26px !important;
  box-shadow: none !important;
  padding: 12px !important;
  color: {palette['text_color']} !important;
  font-family: 'Google Sans', sans-serif !important;
  transition: background-color 260ms ease, border-color 260ms ease !important;
}}

.quick-settings {{
  border-radius: 28px !important;
}}

.popup-menu-content .popup-menu-item {{
  border-radius: 14px !important;
  margin: 1px 0 !important;
  transition: background-color 150ms ease !important;
}}

.popup-menu-content .popup-menu-item:hover,
.popup-menu-content .popup-menu-item:focus {{
  background-color: rgba({palette['accent_rgb']}, 0.18) !important;
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
        if os.path.exists(os.path.join(runtime_dir, 'live-wallpaper-occluded')):
            return

        # Otherwise perform fast direct D-Bus toggle without subprocess overhead or artificial sleep
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
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
