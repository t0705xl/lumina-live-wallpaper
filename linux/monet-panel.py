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
    """Write content to file directly to trigger inotify CHANGED / CHANGES_DONE_HINT events."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

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


# =====================================================================
#  Colour science: sRGB <-> linear <-> OKLab / OKLCH, WCAG luminance
# =====================================================================
import math


def _srgb_to_lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _lin_to_srgb(c):
    c = min(1.0, max(0.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def _cbrt(v):
    return math.copysign(abs(v) ** (1.0 / 3.0), v)


def _lin_to_oklab(r, g, b):
    l = _cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
    m = _cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
    s = _cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s)


def _oklab_to_lin(L, a, b):
    l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
            -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
            -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)


def rgb255_to_oklch(r, g, b):
    L, a, bb = _lin_to_oklab(_srgb_to_lin(r / 255.0), _srgb_to_lin(g / 255.0), _srgb_to_lin(b / 255.0))
    return L, math.hypot(a, bb), math.degrees(math.atan2(bb, a)) % 360.0


def rel_luminance(rgb):
    r, g, b = (_srgb_to_lin(v / 255.0) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(y1, y2):
    hi, lo = max(y1, y2), min(y1, y2)
    return (hi + 0.05) / (lo + 0.05)


class Tone:
    """An sRGB colour built from OKLCH, chroma-reduced into the sRGB gamut."""

    def __init__(self, L, C, H):
        self.L, self.H = L, H

        def conv(c):
            return _oklab_to_lin(L, c * math.cos(math.radians(H)), c * math.sin(math.radians(H)))

        def ok(v):
            return all(-1e-5 <= x <= 1 + 1e-5 for x in v)

        lin = conv(C)
        if not ok(lin):
            lo, hi = 0.0, C
            for _ in range(20):
                mid = (lo + hi) / 2
                if ok(conv(mid)):
                    lo = mid
                else:
                    hi = mid
            C = lo
            lin = conv(C)
        self.C = C
        self.rgb = tuple(int(round(_lin_to_srgb(x) * 255)) for x in lin)
        self.Y = rel_luminance(self.rgb)

    def hex(self):
        return '#{:02X}{:02X}{:02X}'.format(*self.rgb)

    def rgb_str(self):
        return '{}, {}, {}'.format(*self.rgb)

    def a(self, alpha):
        return f'rgba({self.rgb_str()}, {alpha:.2f})'


def hex_color(h, l, s):
    r, g, b = colorsys.hls_to_rgb(h % 1.0, max(0.0, min(1.0, l)), max(0.0, min(1.0, s)))
    return f"#{int(r*255):02X}{int(g*255):02X}{int(b*255):02X}"


def rgba_color(h, l, s, a):
    r, g, b = colorsys.hls_to_rgb(h % 1.0, max(0.0, min(1.0, l)), max(0.0, min(1.0, s)))
    return f"rgba({int(r*255)}, {int(g*255)}, {int(b*255)}, {a})"


# =====================================================================
#  Wallpaper analysis
# =====================================================================

# Screen regions (fractions of the primary monitor) that sit behind Shell UI.
REGION_TOP_BAR = (0.0, 0.0, 1.0, 0.05)
REGION_POPUPS = (0.25, 0.04, 1.0, 0.70)   # date menu (centre) .. quick settings (right)
REGION_DOCK = (0.28, 0.86, 0.72, 0.99)     # overview dash
REGION_GRID = (0.08, 0.25, 0.92, 0.85)     # app grid icons and labels

# WCAG contrast targets
PILL_TEXT_CONTRAST = 4.5
POPUP_TEXT_CONTRAST = 4.5


def get_screen_aspect():
    """Aspect ratio of the primary monitor from Mutter's DisplayConfig; 3:2 fallback (Surface)."""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        res = bus.call_sync('org.gnome.Mutter.DisplayConfig', '/org/gnome/Mutter/DisplayConfig',
                            'org.gnome.Mutter.DisplayConfig', 'GetCurrentState', None, None,
                            Gio.DBusCallFlags.NONE, 800, None).unpack()
        _serial, monitors, logical, _props = res
        primary = next((lm for lm in logical if lm[4]), logical[0] if logical else None)
        if primary:
            transform = primary[3]
            spec = primary[5][0]
            for mon in monitors:
                if tuple(mon[0]) == tuple(spec):
                    for mode in mon[1]:
                        if mode[6].get('is-current'):
                            w, h = mode[1], mode[2]
                            if transform in (1, 3, 5, 7):
                                w, h = h, w
                            return w / float(h)
    except Exception:
        pass
    return 1.5


def _picture_option():
    try:
        return Gio.Settings.new('org.gnome.desktop.background').get_string('picture-options')
    except Exception:
        return 'zoom'


def _fit_to_screen(img, aspect):
    """Crop the image the way GNOME's 'zoom' mode shows it, so regions map to the screen."""
    if _picture_option() in ('stretched', 'scaled', 'centered', 'wallpaper', 'none'):
        return img
    w, h = img.size
    if w / h > aspect:
        nw = int(round(h * aspect))
        x0 = (w - nw) // 2
        return img.crop((x0, 0, x0 + nw, h))
    nh = int(round(w / aspect))
    y0 = (h - nh) // 2
    return img.crop((0, y0, w, y0 + nh))


def _percentile(values, p):
    if not values:
        return 0.5
    v = sorted(values)
    return v[min(len(v) - 1, max(0, int(round(p * (len(v) - 1)))))]


def _region_luminance(img_small, region):
    """Luminance samples of a region. img_small is a heavily box-downsampled image, which
    approximates what the eye sees behind a glass surface (local averaging ~ blur)."""
    w, h = img_small.size
    x0, y0, x1, y1 = region
    xs = range(int(x0 * w), max(int(x0 * w) + 1, int(math.ceil(x1 * w))))
    ys = range(int(y0 * h), max(int(y0 * h) + 1, int(math.ceil(y1 * h))))
    px = img_small.load()
    return [rel_luminance(px[x, y][:3]) for y in ys for x in xs]


# GNOME 47+ accent colours (org.gnome.desktop.interface accent-color)
GNOME_ACCENTS = {
    'blue': (0x35, 0x84, 0xE4), 'teal': (0x21, 0x90, 0xA4), 'green': (0x3A, 0x94, 0x4A),
    'yellow': (0xC8, 0x88, 0x00), 'orange': (0xED, 0x5B, 0x00), 'red': (0xE6, 0x2D, 0x42),
    'pink': (0xD5, 0x61, 0x99), 'purple': (0x91, 0x41, 0xAC), 'slate': (0x6F, 0x83, 0x96),
}


def nearest_gnome_accent(hue, chroma):
    if chroma < 0.035:
        return 'slate'
    best, best_d = 'blue', 999.0
    for name, rgb in GNOME_ACCENTS.items():
        if name == 'slate':
            continue
        _L, _C, H = rgb255_to_oklch(*rgb)
        d = abs((hue - H + 180) % 360 - 180)
        if d < best_d:
            best, best_d = name, d
    return best


def extract_source_color(img):
    """Pick the wallpaper's theme colour, Material-You style.

    The image is quantised (median cut, 32 colours) and each chromatic cluster is scored by
    how much of the image shares its hue (+-15 deg) and by its chroma. Achromatic, near-black and
    near-white clusters are ignored, so skies/snow/shadows do not wash the theme out, and a small
    saturated object cannot win against a large coloured area.
    Returns (hue_deg, chroma, info) or (None, 0, info) when the image has no usable colour.
    """
    small = img.resize((128, max(1, int(round(128 * img.size[1] / img.size[0])))), Image.Resampling.BILINEAR)
    q = small.quantize(colors=32, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()
    counts = q.getcolors(4096) or []
    total = float(sum(c for c, _ in counts)) or 1.0

    clusters = []
    for count, idx in counts:
        rgb = tuple(pal[idx * 3: idx * 3 + 3])
        L, C, H = rgb255_to_oklch(*rgb)
        clusters.append({'rgb': rgb, 'L': L, 'C': C, 'H': H, 'p': count / total})

    usable = [c for c in clusters if c['C'] >= 0.03 and 0.25 <= c['L'] <= 0.94]
    best, best_score = None, -1e9
    for c in usable:
        neighbourhood = sum(o['p'] for o in usable if abs((o['H'] - c['H'] + 180) % 360 - 180) <= 15)
        if neighbourhood < 0.02:
            continue
        cam = c['C'] * 300.0   # OKLCH chroma -> roughly CAM16 chroma scale
        chroma_score = (cam - 48.0) * (0.1 if cam < 48.0 else 0.3)
        score = neighbourhood * 100.0 * 0.7 + chroma_score
        if score > best_score:
            best, best_score = c, score

    chromatic_share = sum(c['p'] for c in usable)
    if not best:
        return None, 0.0, {'chromatic_share': chromatic_share}

    # Refine hue/chroma as the population-weighted circular mean of the winning hue family
    fam = [o for o in usable if abs((o['H'] - best['H'] + 180) % 360 - 180) <= 15]
    wsum = sum(o['p'] for o in fam)
    sx = sum(math.cos(math.radians(o['H'])) * o['p'] for o in fam)
    sy = sum(math.sin(math.radians(o['H'])) * o['p'] for o in fam)
    hue = math.degrees(math.atan2(sy, sx)) % 360.0
    chroma = sum(o['C'] * o['p'] for o in fam) / wsum
    return hue, chroma, {'chromatic_share': chromatic_share, 'family_share': wsum,
                         'winner_rgb': best['rgb']}


def analyse_wallpaper(image_path):
    """Returns dict(hue, chroma, bar_y_hi, bar_y_lo, popup_y_hi, popup_y_lo, info)."""
    out = {'hue': None, 'chroma': 0.0, 'bar_y_hi': 0.5, 'bar_y_lo': 0.2, 'bar_y_mid': 0.35,
           'popup_y_hi': 0.5, 'popup_y_lo': 0.2, 'popup_y_mid': 0.35,
           'dock_y_lo': 0.2, 'dock_y_mid': 0.35, 'dock_y_hi': 0.5, 'grid_y_p75': 0.4, 'info': {}}
    if not image_path or not os.path.isfile(image_path):
        return out
    try:
        img = Image.open(image_path).convert('RGB')
        img.draft('RGB', (640, 640))
        img = _fit_to_screen(img, get_screen_aspect())
        hue, chroma, info = extract_source_color(img)
        out.update(hue=hue, chroma=chroma, info=info)

        # ~1/40 of the screen width per sample: a stand-in for what shows through frosted glass
        sw = 40
        small = img.resize((sw, max(1, int(round(sw * img.size[1] / img.size[0])))), Image.Resampling.BOX)
        bar = _region_luminance(small, REGION_TOP_BAR)
        pop = _region_luminance(small, REGION_POPUPS)
        out.update(bar_y_mid=_percentile(bar, 0.50), popup_y_mid=_percentile(pop, 0.50))
        dock = _region_luminance(small, REGION_DOCK)
        grid = _region_luminance(small, REGION_GRID)
        out.update(dock_y_lo=_percentile(dock, 0.10), dock_y_mid=_percentile(dock, 0.50),
                   dock_y_hi=_percentile(dock, 0.90), grid_y_p75=_percentile(grid, 0.75))
        out.update(bar_y_hi=_percentile(bar, 0.90), bar_y_lo=_percentile(bar, 0.10),
                   popup_y_hi=_percentile(pop, 0.90), popup_y_lo=_percentile(pop, 0.10))
    except Exception as e:
        print(f"[Monet] Error analysing wallpaper: {e}", file=sys.stderr)
    return out


def _enc(y):
    """Linear luminance -> sRGB-encoded value (GNOME Shell blends in encoded space)."""
    return _lin_to_srgb(max(0.0, min(1.0, y)))


def _need_y(text_y, glass_y, target):
    """Luminance the composited background must stay below (light text) or above (dark text)."""
    if text_y > glass_y:
        return (text_y + 0.05) / target - 0.05
    return target * (text_y + 0.05) - 0.05


def solve_glass_alpha(glass_y, text_y, behind_enc, target, lo, hi):
    """Smallest tint opacity so text over (tint blended onto the backdrop) meets the target.
    Blending is done the way the Shell does it: on sRGB-encoded values, not in linear light.
    behind_enc is the backdrop's encoded value (after any shader brightness)."""
    g = _enc(glass_y)
    need = _enc(max(0.0, _need_y(text_y, glass_y, target)))
    if text_y > glass_y:          # background must get dark enough
        if behind_enc <= need:
            return lo
        a = (behind_enc - need) / max(1e-6, behind_enc - g)
    else:                         # background must get bright enough
        if behind_enc >= need:
            return lo
        a = (need - behind_enc) / max(1e-6, g - behind_enc)
    return max(lo, min(hi, a))


def solve_glass(glass_y, text_y, behind_y, target, alpha_pref, alpha_cap, bright_range):
    """Thin tint first: pick the shader brightness (it scales encoded backdrop values) that brings
    the backdrop to the contrast target with the preferred tint, then raise the tint only as far as
    still needed, never past alpha_cap. Returns (alpha, brightness)."""
    bmin, bmax = bright_range
    g = _enc(glass_y)
    be = _enc(behind_y)
    need = _enc(max(0.0, _need_y(text_y, glass_y, target)))
    a = alpha_pref
    b = bmin
    if bmax != bmin and be > 1e-4:
        want = (need - a * g) / max(1e-6, 1 - a)       # encoded backdrop value we need
        b = max(bmin, min(bmax, want / be))
        if text_y < glass_y and want <= be:            # dark text and already bright enough
            b = bmin
    alpha = solve_glass_alpha(glass_y, text_y, min(1.0, be * b), target, alpha_pref, alpha_cap)
    return alpha, b


# =====================================================================
#  Palette
# =====================================================================

GLASS_MARKER = 'lumina-glass-active'


def glass_blur_active():
    """True when the Shell extension's backdrop blur is running (it drops a runtime marker).
    LUMINA_GLASS=0/1 overrides, for previews."""
    env = os.environ.get('LUMINA_GLASS')
    if env in ('0', '1'):
        return env == '1'
    runtime_dir = os.environ.get('XDG_RUNTIME_DIR') or f"/run/user/{os.getuid()}"
    return os.path.exists(os.path.join(runtime_dir, GLASS_MARKER))


def extract_palette(image_path, scheme='prefer-dark'):
    is_dark = (scheme == 'prefer-dark')
    an = analyse_wallpaper(image_path)
    blur = glass_blur_active()

    if an['hue'] is None:
        hue, src_c = 255.0, 0.02          # neutral slate-blue fallback
    else:
        hue, src_c = an['hue'], an['chroma']

    muted = src_c < 0.045
    # accent chroma: Material keeps primary at >= ~48 CAM16 chroma (~0.13 OKLCH) so it never turns muddy
    cp = 0.06 if muted else max(0.13, min(0.17, src_c * 1.5))
    cn = max(0.006, min(0.020, src_c * 0.16))                # neutral chroma (tinted greys)

    # Material's "dislike" rule: dark yellow-greens (olive/bile) read as muddy as an accent.
    # Accents in that band are pushed toward leaf green; neutrals keep the wallpaper hue.
    accent_hue = hue
    if 95.0 <= hue < 134.0:
        accent_hue = 134.0 + (hue - 95.0) * 0.15

    def P(L, C=None):
        return Tone(L, cp if C is None else C, accent_hue)

    def N(L, k=1.0):
        return Tone(L, cn * k, hue)

    def ink_set(light_ink):
        """Token set for a glass surface. light_ink: white text on smoky glass (dark look);
        otherwise dark text on clear/milky glass (light look)."""
        if light_ink:
            t = dict(text=N(0.975, 0.4), glass=N(0.25, 1.6), popup_glass=N(0.22, 1.6),
                     accent=P(0.83), accent_hover=P(0.87), accent_chip=P(0.74), accent_chip_hover=P(0.69),
                     on_accent=P(0.24, cp * 0.7),
                     rim='rgba(255, 255, 255, 0.22)', rim_strong='rgba(255, 255, 255, 0.34)',
                     border='rgba(255, 255, 255, 0.18)', border_strong='rgba(255, 255, 255, 0.30)',
                     card='rgba(255, 255, 255, 0.08)', card_hover='rgba(255, 255, 255, 0.14)',
                     chip='rgba(255, 255, 255, 0.10)', chip_hover='rgba(255, 255, 255, 0.22)',
                     worst_behind=1.0)
            if blur:
                t.update(sat=1.45, bright_range=(1.0, 1.0), pill=(0.03, 0.03), pop=(0.06, 0.06),
                         dock=(0.06, 0.06))
            else:
                t.update(sat=1.0, bright_range=(1.0, 1.0), pill=(0.06, 0.38), pop=(0.26, 0.52),
                         dock=(0.22, 0.45))
        else:
            ink = N(0.30).rgb_str()
            t = dict(text=N(0.17, 1.2), glass=N(0.985, 0.5), popup_glass=N(0.975, 0.6),
                     accent=P(0.52), accent_hover=P(0.48), accent_chip=P(0.44), accent_chip_hover=P(0.40),
                     on_accent=Tone(0.99, 0.0, hue),
                     rim='rgba(255, 255, 255, 0.85)', rim_strong='rgba(255, 255, 255, 0.95)',
                     border='rgba(255, 255, 255, 0.42)', border_strong='rgba(255, 255, 255, 0.60)',
                     card=f'rgba({ink}, 0.06)', card_hover=f'rgba({ink}, 0.11)',
                     chip=f'rgba({ink}, 0.07)', chip_hover=f'rgba({ink}, 0.15)',
                     worst_behind=0.0)
            if blur:
                t.update(sat=1.35, bright_range=(1.0, 1.0), pill=(0.03, 0.03), pop=(0.06, 0.06),
                         dock=(0.06, 0.06))
            else:
                t.update(sat=1.0, bright_range=(1.0, 1.0), pill=(0.04, 0.40), pop=(0.26, 0.55),
                         dock=(0.22, 0.45))
        # text on the filled accent must read (WCAG 4.5)
        for _ in range(12):
            if contrast(t['accent'].Y, t['on_accent'].Y) >= 4.5:
                break
            t['accent'] = P(t['accent'].L + (0.02 if light_ink else -0.02))
        return t

    def luma_limit(t, kind, target):
        """Encoded backdrop luma the shader must clamp to (max for light text, min for dark text)
        so text over (tint + backdrop) meets the target at every pixel."""
        glass_tone = t['glass'] if kind == 'pill' else t['popup_glass']
        a = t[kind][0]
        g = _enc(glass_tone.Y)
        need = _enc(max(0.0, _need_y(t['text'].Y, glass_tone.Y, target)))
        return max(0.05, min(1.0, (need - a * g) / max(1e-6, 1 - a)))

    def solve_surface(t, light_ink, y_hi, y_lo, target, kind, y_mid=None):
        glass_tone = t['glass'] if kind == 'pill' else t['popup_glass']
        pref, cap = t[kind]
        if blur:
            # Live per-pixel adaptation in the shader; the cost is how much of the backdrop it
            # has to bend (darken for light text, lift for dark text) across the region.
            lim = luma_limit(t, kind, target)
            samples = [_enc(y) for y in (y_lo, y_mid if y_mid is not None else (y_lo + y_hi) / 2, y_hi)]
            if light_ink:
                cost = sum(max(0.0, v - lim) for v in samples) / 3
            else:
                cost = sum(max(0.0, lim - v) for v in samples) / 3
            return pref, 1.0, cost, lim
        behind = y_hi if light_ink else y_lo
        alpha, bright = solve_glass(glass_tone.Y, t['text'].Y, behind, target, pref, cap, t['bright_range'])
        if kind == 'pop':
            # popups can also sit over application windows: stay legible (3:1) over pure white / black
            wa, wb = solve_glass(glass_tone.Y, t['text'].Y, t['worst_behind'], 3.0, pref, cap, t['bright_range'])
            if light_ink:
                bright = min(bright, wb)
                wa = solve_glass_alpha(glass_tone.Y, t['text'].Y, min(1.0, _enc(1.0) * bright), 3.0, pref, cap)
            alpha = max(alpha, wa)
        # how far the glass is from clear: tint + darkening (lifting costs less than darkening)
        cost = alpha + (1.0 - bright if bright < 1.0 else (bright - 1.0) * 0.3)
        return alpha, bright, cost, None

    def choose(y_hi, y_lo, target, kind, margin, y_mid=None):
        """Glass follows what is behind it, like Liquid Glass: over a bright wallpaper the text
        turns dark so the glass can stay clear; over a dark one it turns light. The system scheme
        wins unless the other ink is clearly more transparent."""
        cands = {}
        for light_ink in (True, False):
            t = ink_set(light_ink)
            cands[light_ink] = (t,) + solve_surface(t, light_ink, y_hi, y_lo, target, kind, y_mid)
        pref_ink = is_dark
        other = not pref_ink
        pick = other if cands[other][3] < cands[pref_ink][3] - margin else pref_ink
        t, alpha, bright, _cost, lim = cands[pick]
        glass_tone = t['glass'] if kind == 'pill' else t['popup_glass']
        limits = {
            'lmax': round(lim, 3) if (lim is not None and pick) else 1.0,
            'lmin': round(lim, 3) if (lim is not None and not pick) else 0.0,
            'lift': [round(v / 255.0, 3) for v in glass_tone.rgb],
        }
        return pick, t, alpha, bright, limits

    pill_light_ink, pt, pill_alpha, pill_bright, pill_lim = choose(
        an['bar_y_hi'], an['bar_y_lo'], PILL_TEXT_CONTRAST, 'pill', 0.05 if blur else 0.08, an.get('bar_y_mid'))
    pop_light_ink, ot, pop_alpha, pop_bright, pop_lim = choose(
        an['popup_y_hi'], an['popup_y_lo'], POPUP_TEXT_CONTRAST + 0.5, 'pop', 0.08 if blur else 0.25,
        an.get('popup_y_mid'))
    # Overview dash: icons only, so a lower target; glass decides its own look from the backdrop
    dock_light_ink, dt, dock_alpha, dock_bright, dock_lim = choose(
        an['dock_y_hi'], an['dock_y_lo'], 3.0, 'dock', 0.05 if blur else 0.15, an.get('dock_y_mid'))
    dock_tokens = {
        'bg': dt['popup_glass'].a(dock_alpha),
        'border': dt['border'],
        'bright': round(dock_bright, 3),
        'sat': dt['sat'],
        'lim': dock_lim,
        'gloss': 0.8 if dock_light_ink else 0.65,
        'alpha': round(dock_alpha, 2),
    }
    # Scrim over the drawer wallpaper: white icon labels need >= 3:1 against the brighter parts
    grid_enc = _enc(an['grid_y_p75'])
    need_enc = _enc((1.05 / 3.0) - 0.05)
    # (capped low: the wallpaper should stay the wallpaper; the label shadow carries the rest)
    scrim = 0.0 if grid_enc <= need_enc else min(0.22, 1.0 - need_enc / grid_enc)

    glass_bright = pill_bright
    glass_sat = ot['sat']

    # The popup set provides the base tokens (quick settings, menus, calendar)
    text, glass, popup_glass = ot['text'], pt['glass'], ot['popup_glass']
    accent, accent_hover = ot['accent'], ot['accent_hover']
    accent_chip, accent_chip_hover = ot['accent_chip'], ot['accent_chip_hover']
    on_accent = ot['on_accent']
    rim, rim_strong = ot['rim'], ot['rim_strong']
    border, border_strong = ot['border'], ot['border_strong']
    card, card_hover, chip, chip_hover = ot['card'], ot['card_hover'], ot['chip'], ot['chip_hover']
    pop_cap = ot['pop'][1]

    pill_tokens = {
        'text': pt['text'].hex(),
        'pill_bg': pt['glass'].a(pill_alpha),
        'pill_hover_bg': pt['glass'].a(min(pt['pill'][1] + 0.08, pill_alpha + 0.10)),
        'pill_active_bg': pt['accent'].a(0.62 if blur else 0.70),
        'pill_active_fg': pt['on_accent'].hex(),
        'border': pt['border'], 'border_strong': pt['border_strong'],
        'rim': pt['rim'], 'rim_strong': pt['rim_strong'],
        # light ink: soft drop shadow lifts the clear pill off the wallpaper; dark glass: inner rim
        'pill_shadow': ('none' if pill_light_ink
                        else f'0 1px 3px 0 rgba({N(0.20).rgb_str()}, 0.14)'),
        'bright': round(pill_bright, 3),
        'sat': pt['sat'],
        'lim': pill_lim,
        'gloss': 0.9 if pill_light_ink else 0.75,
    }

    # Legacy HLS hue/sat so the terminal / GTK helpers keep a consistent family
    rr, gg, bb = (v / 255.0 for v in P(0.65).rgb)
    h_hls, _l, s_hls = colorsys.rgb_to_hls(rr, gg, bb)

    return {
        'is_dark': is_dark,
        'hue': round(hue, 1),
        'chroma': round(src_c, 4),
        'muted': muted,
        'accent_enum': 'slate' if muted else nearest_gnome_accent(accent_hue, src_c),
        'blur': blur,
        'glass_bright': glass_bright,
        'pill_bright': round(pill_bright, 3),
        'popup_bright': round(pop_bright, 3),
        'popup_lim': pop_lim,
        'dock': dock_tokens,
        'scrim': round(scrim, 2),
        'glass_sat': glass_sat,
        'pill_alpha': round(pill_alpha, 2),
        'popup_alpha': round(pop_alpha, 2),
        'pill_ink': 'light' if pill_light_ink else 'dark',
        'popup_ink': 'light' if pop_light_ink else 'dark',
        'pill': pill_tokens,
        'popup_gloss': 0.8 if pop_light_ink else 0.65,
        'analysis': an,
        # tones (objects) for other generators
        'T': {'text': text, 'glass': glass, 'popup_glass': popup_glass, 'accent': accent,
              'on_accent': on_accent, 'P': P, 'N': N},
        # CSS tokens
        'text': text.hex(),
        'text_dim': text.a(0.72),
        'text_faint': text.a(0.50),
        'popup_bg': popup_glass.a(pop_alpha),
        'submenu_bg': popup_glass.a(min(pop_cap + 0.15, pop_alpha + 0.15)),
        'rim': rim, 'rim_strong': rim_strong,
        'border': border, 'border_strong': border_strong,
        'card': card, 'card_hover': card_hover,
        'chip': chip, 'chip_hover': chip_hover,
        'accent': accent.hex(), 'accent_hover': accent_hover.hex(),
        'accent_chip': accent_chip.hex(), 'accent_chip_hover': accent_chip_hover.hex(),
        'on_accent': on_accent.hex(), 'on_accent_dim': on_accent.a(0.78),
        'accent_tint': accent.a(0.22 if pop_light_ink else 0.16),
        'accent_tint_strong': accent.a(0.32 if pop_light_ink else 0.24),
        'focus': accent.a(0.85),
        # legacy keys
        'h_val': h_hls, 's_val': max(0.2, min(0.8, s_hls)),
        'accent_rgb': accent.rgb_str(),
    }


def generate_gnome_shell_css(p):
    """GNOME Shell stylesheet: liquid-glass top bar, quick settings and popups.
    Every colour comes from the palette; nothing is hard-coded white/black, so it holds in
    both light and dark schemes. The top bar uses its own token set (p['pill']) because its
    text colour adapts to the wallpaper behind it independently of the popups."""
    q = p['pill']
    return f"""/* Lumina Monet liquid glass - generated by monet-panel.py, do not edit by hand.
   scheme={'dark' if p['is_dark'] else 'light'} hue={p['hue']} chroma={p['chroma']} blur={p['blur']}
   pill_alpha={p['pill_alpha']} ({p['pill_ink']} text) popup_alpha={p['popup_alpha']} ({p['popup_ink']} text) */

.quick-settings .user-icon {{ icon-size: 5em; }}
.quick-settings .user-widget {{ spacing: 36px; padding-bottom: 12px; }}
.quick-settings .user-widget-label {{ font-size: x-large; font-weight: normal; }}

/* ---------- 1. Top bar: transparent strip carrying floating glass pills ---------- */
#panel {{
  background-color: transparent !important;
  background-gradient-direction: none !important;
  box-shadow: none !important;
  border: none !important;
  font-family: "Google Sans Flex", sans-serif !important;
  height: 2.55em !important;
  padding: 4px 8px !important;
}}

#panel .panel-button {{
  background-color: {q['pill_bg']} !important;
  background-gradient-direction: none !important;
  border: 1px solid {q['border']} !important;
  border-radius: 999px !important;
  box-shadow: {q['pill_shadow']} !important;
  color: {q['text']} !important;
  text-shadow: none !important;
  icon-shadow: none !important;
  font-weight: 600 !important;
  margin: 2px 4px !important;
  padding: 0 15px !important;
  transition-duration: 160ms !important;
  -lumina-blur: 7;
  -lumina-brightness: {q['bright']};
  -lumina-saturation: {q['sat']};
  -lumina-refraction: 9;
  -lumina-gloss: {q['gloss']};
  -lumina-max-luma: {q['lim']['lmax']};
  -lumina-min-luma: {q['lim']['lmin']};
  -lumina-lift-r: {q['lim']['lift'][0]};
  -lumina-lift-g: {q['lim']['lift'][1]};
  -lumina-lift-b: {q['lim']['lift'][2]};
}}

#panel .panel-button:hover,
#panel .panel-button:focus {{
  background-color: {q['pill_hover_bg']} !important;
  border-color: {q['border_strong']} !important;
  color: {q['text']} !important;
}}

#panel .panel-button:active,
#panel .panel-button:checked,
#panel .panel-button:overview {{
  background-color: {q['pill_active_bg']} !important;
  border-color: transparent !important;
  box-shadow: {q['pill_shadow']} !important;
  color: {q['pill_active_fg']} !important;
}}

#panel .clock-display {{
  font-weight: 600 !important;
  letter-spacing: 0.3px !important;
  text-shadow: none !important;
}}
/* Explicit colours: nested labels/icons in the base theme do not reliably inherit */
#panel .panel-button StLabel,
#panel .panel-button StIcon,
#panel .panel-button .clock,
#panel .panel-button .clock-display,
#panel .system-status-icon {{
  color: {q['text']} !important;
  icon-shadow: none !important;
  text-shadow: none !important;
}}
#panel .panel-button:checked StLabel,
#panel .panel-button:checked StIcon,
#panel .panel-button:checked .clock,
#panel .panel-button:checked .clock-display,
#panel .panel-button:checked .system-status-icon,
#panel .panel-button:active StLabel,
#panel .panel-button:active StIcon,
#panel .panel-button:overview StLabel,
#panel .panel-button:overview StIcon {{
  color: {q['pill_active_fg']} !important;
}}

/* Activities workspace dots follow the text colour */
#panel .workspace-dot {{ background-color: {q['text']} !important; }}

/* Vitals draws its own inner pill; flatten it so there is one glass layer */
#panel .vitals-panel-menu,
#panel .vitals-panel-menu:hover {{
  background-color: transparent !important;
  margin: 0 !important;
  padding: 0 !important;
}}

/* ---------- 2. Popups: one rounded glass sheet, no box-pointer rectangle ---------- */
.popup-menu,
.popup-menu-boxpointer,
.candidate-popup-boxpointer {{
  background-color: transparent !important;
  box-shadow: none !important;
  border: none !important;
  -arrow-rise: 0px !important;
  -arrow-border-width: 0px !important;
  -arrow-border-radius: 0px !important;
  -arrow-base: 0px !important;
  -arrow-background-color: transparent !important;
  -arrow-border-color: transparent !important;
  -boxpointer-gap: 4px !important;
}}

.popup-menu-content,
.candidate-popup-content {{
  background-color: {p['popup_bg']} !important;
  background-gradient-direction: none !important;
  border: 1px solid {p['border_strong']} !important;
  border-radius: 28px !important;
  box-shadow: none !important;
  padding: 14px !important;
  color: {p['text']} !important;
  -lumina-blur: 14;
  -lumina-brightness: {p['popup_bright']};
  -lumina-saturation: {p['glass_sat']};
  -lumina-refraction: 12;
  -lumina-gloss: {p['popup_gloss']};
  -lumina-max-luma: {p['popup_lim']['lmax']};
  -lumina-min-luma: {p['popup_lim']['lmin']};
  -lumina-lift-r: {p['popup_lim']['lift'][0]};
  -lumina-lift-g: {p['popup_lim']['lift'][1]};
  -lumina-lift-b: {p['popup_lim']['lift'][2]};
}}

.popup-menu-content .popup-menu-item,
.popup-menu .popup-menu-item {{
  color: {p['text']} !important;
  border-radius: 14px !important;
  transition-duration: 140ms !important;
}}
.popup-menu-content .popup-menu-item:hover,
.popup-menu-content .popup-menu-item:focus,
.popup-menu-content .popup-menu-item:selected {{
  background-color: {p['accent_tint']} !important;
  color: {p['text']} !important;
}}
.popup-menu-content .popup-menu-item:active,
.popup-menu-content .popup-menu-item:checked {{
  background-color: {p['accent_tint_strong']} !important;
}}
.popup-separator-menu-item .popup-separator-menu-item-separator,
.popup-separator-menu-item-separator {{
  background-color: {p['border_strong']} !important;
}}
.popup-sub-menu {{
  background-color: {p['card']} !important;
  border-radius: 14px !important;
  box-shadow: none !important;
}}

.quick-settings, .quick-settings-menu, .quick-settings-grid, .datemenu-popover {{
  box-shadow: none !important;
}}
.quick-settings {{ border-radius: 28px !important; }}

/* ---------- 3. Quick settings: system row (battery, screenshot, settings, lock, power) ---------- */
.quick-settings-system-item .icon-button,
.quick-settings-system-item .power-item,
.quick-settings .icon-button {{
  background-color: {p['card']} !important;
  border: 1px solid {p['border']} !important;
  color: {p['text']} !important;
  box-shadow: none !important;
  transition-duration: 140ms !important;
}}
.quick-settings-system-item .icon-button:hover,
.quick-settings-system-item .icon-button:focus,
.quick-settings .icon-button:hover,
.quick-settings .icon-button:focus {{
  background-color: {p['card_hover']} !important;
  border-color: {p['border_strong']} !important;
}}
.quick-settings-system-item .icon-button:active,
.quick-settings .icon-button:checked {{
  background-color: {p['accent']} !important;
  color: {p['on_accent']} !important;
}}

/* ---------- 4. Quick toggles ----------
   off: quiet glass card.   on: filled accent - unmistakable at a glance.
   Toggles with a menu get a separate, softly rounded arrow capsule (no hard divider line):
   off -> faint capsule, on -> deeper accent capsule; hover brightens it. */
.quick-toggle {{
  background-color: {p['card']} !important;
  background-gradient-direction: none !important;
  border: 1px solid {p['border']} !important;
  border-radius: 999px !important;
  box-shadow: none !important;
  color: {p['text']} !important;
  transition-duration: 180ms !important;
}}
.quick-toggle:hover {{
  background-color: {p['card_hover']} !important;
  border-color: {p['border_strong']} !important;
}}
.quick-toggle:checked {{
  background-color: {p['accent']} !important;
  border-color: transparent !important;
  color: {p['on_accent']} !important;
}}
.quick-toggle:checked:hover {{
  background-color: {p['accent_hover']} !important;
}}

/* Compound toggle (Wi-Fi, Bluetooth, Power mode...): the outer shell paints the pill,
   the left part is a transparent hit area, the arrow is an inset capsule. */
.quick-toggle-has-menu {{
  background-color: {p['card']} !important;
  border: 1px solid {p['border']} !important;
  border-radius: 999px !important;
  box-shadow: none !important;
  padding: 0 !important;
  transition-duration: 180ms !important;
}}
.quick-toggle-has-menu:checked {{
  background-color: {p['accent']} !important;
  border-color: transparent !important;
}}

.quick-toggle-has-menu .quick-toggle {{
  background-color: transparent !important;
  border: none !important;
  border-radius: 999px 0 0 999px !important;
  color: {p['text']} !important;
}}
.quick-toggle-has-menu .quick-toggle:rtl {{ border-radius: 0 999px 999px 0 !important; }}
.quick-toggle-has-menu .quick-toggle:hover {{ background-color: {p['card_hover']} !important; }}
.quick-toggle-has-menu .quick-toggle:checked {{
  background-color: transparent !important;
  color: {p['on_accent']} !important;
}}
.quick-toggle-has-menu .quick-toggle:checked:hover {{
  background-color: {p['accent_hover']} !important;
}}

.quick-toggle-has-menu .quick-toggle-separator {{
  width: 0 !important;
  background-color: transparent !important;
}}

.quick-toggle-has-menu .quick-toggle-menu-button {{
  background-color: {p['chip']} !important;
  border: none !important;
  border-radius: 999px !important;
  box-shadow: none !important;
  color: {p['text']} !important;
  margin: 5px 5px 5px 0 !important;
  padding: 0 10px !important;
  transition-duration: 160ms !important;
}}
.quick-toggle-has-menu .quick-toggle-menu-button:rtl {{ margin: 5px 0 5px 5px !important; }}
.quick-toggle-has-menu .quick-toggle-menu-button:hover,
.quick-toggle-has-menu .quick-toggle-menu-button:focus {{
  background-color: {p['chip_hover']} !important;
  color: {p['text']} !important;
}}
.quick-toggle-has-menu .quick-toggle-menu-button:checked {{
  background-color: {p['accent_chip']} !important;
  color: {p['on_accent']} !important;
}}
.quick-toggle-has-menu .quick-toggle-menu-button:checked:hover,
.quick-toggle-has-menu .quick-toggle-menu-button:checked:focus {{
  background-color: {p['accent_chip_hover']} !important;
  color: {p['on_accent']} !important;
}}

.quick-toggle .quick-toggle-title {{ font-weight: 600 !important; color: inherit !important; }}
.quick-toggle .quick-toggle-subtitle {{ font-weight: 400 !important; color: {p['text_dim']} !important; }}
.quick-toggle .quick-toggle-icon {{ color: inherit !important; }}
.quick-toggle:checked .quick-toggle-subtitle {{ color: {p['on_accent_dim']} !important; }}

/* ---------- 5. Expanded toggle menu (Wi-Fi networks, power modes...) ----------
   It slides over the dimmed toggle grid, so it gets its own, denser glass sheet. */
.quick-toggle-menu {{
  background-color: {p['submenu_bg']} !important;
  border: 1px solid {p['border_strong']} !important;
  -lumina-blur: 14;
  -lumina-brightness: {p['popup_bright']};
  -lumina-saturation: {p['glass_sat']};
  -lumina-refraction: 5;
  -lumina-gloss: {p['popup_gloss']};
  -lumina-max-luma: {p['popup_lim']['lmax']};
  -lumina-min-luma: {p['popup_lim']['lmin']};
  -lumina-lift-r: {p['popup_lim']['lift'][0]};
  -lumina-lift-g: {p['popup_lim']['lift'][1]};
  -lumina-lift-b: {p['popup_lim']['lift'][2]};
  border-radius: 24px !important;
  box-shadow: none !important;
  margin: 10px 4px 6px !important;
  padding: 14px 16px !important;
  color: {p['text']} !important;
}}
.quick-toggle-menu .header {{ padding-bottom: 12px !important; spacing-rows: 4px !important; spacing-columns: 12px !important; }}
.quick-toggle-menu .header .title {{ font-weight: 700 !important; color: {p['text']} !important; }}
.quick-toggle-menu .header .subtitle {{ color: {p['text_dim']} !important; }}
.quick-toggle-menu .header .icon {{
  border-radius: 999px !important;
  padding: 8px !important;
  background-color: {p['card_hover']} !important;
  color: {p['text']} !important;
}}
.quick-toggle-menu .header .icon.active {{
  background-color: {p['accent']} !important;
  color: {p['on_accent']} !important;
}}
.quick-toggle-menu .popup-menu-item {{ border-radius: 14px !important; padding: 8px 12px !important; margin: 2px 0 !important; }}

/* ---------- 6. Sliders ---------- */
.quick-slider {{
  background-color: transparent !important;
  border: none !important;
  box-shadow: none !important;
}}
.slider {{
  -slider-background-color: {p['card_hover']} !important;
  -slider-active-background-color: {p['accent']} !important;
  -slider-handle-border-color: transparent !important;
  color: {p['text']} !important;
}}

/* ---------- 8. Overview: wallpaper under the app drawer, glass dock ---------- */
.lumina-overview-scrim {{ background-color: rgba(0, 0, 0, {p['scrim']}); }}
.icon-grid StLabel {{
  color: #FFFFFF !important;
  text-shadow: 0 1px 4px rgba(0, 0, 0, 0.65) !important;
}}
/* Folder tiles: a light glass card instead of an opaque grey block */
.app-folder {{
  background-color: rgba(255, 255, 255, 0.14) !important;
  border: 1px solid rgba(255, 255, 255, 0.22) !important;
  color: #FFFFFF !important;
}}
.app-folder:hover, .app-folder:focus {{ background-color: rgba(255, 255, 255, 0.22) !important; }}
.app-folder:active, .app-folder:checked, .app-folder:highlighted, .app-folder:selected {{
  background-color: rgba(255, 255, 255, 0.28) !important;
}}
/* Dock icons sit straight on the glass; only hover / pressed / focused get a soft glass chip */
#dash .dash-item-container .show-apps .overview-icon,
#dash .dash-item-container .overview-tile .overview-icon {{
  background-color: transparent !important;
}}
#dash .dash-item-container .show-apps:hover .overview-icon,
#dash .dash-item-container .overview-tile:hover .overview-icon,
#dash .dash-item-container .show-apps:focus .overview-icon,
#dash .dash-item-container .overview-tile:focus .overview-icon {{
  background-color: rgba(255, 255, 255, 0.18) !important;
}}
#dash .dash-item-container .show-apps:active .overview-icon,
#dash .dash-item-container .overview-tile:active .overview-icon,
#dash .dash-item-container .show-apps:checked .overview-icon,
#dash .dash-item-container .overview-tile:checked .overview-icon {{
  background-color: rgba(255, 255, 255, 0.26) !important;
}}
#dash .dash-separator {{ background-color: rgba(255, 255, 255, 0.25) !important; }}
#dash .dash-background {{
  background-color: {p['dock']['bg']} !important;
  border: 1px solid {p['dock']['border']} !important;
  border-radius: 28px !important;
  box-shadow: none !important;
  -lumina-blur: 14;
  -lumina-brightness: {p['dock']['bright']};
  -lumina-saturation: {p['dock']['sat']};
  -lumina-refraction: 10;
  -lumina-gloss: {p['dock']['gloss']};
  -lumina-max-luma: {p['dock']['lim']['lmax']};
  -lumina-min-luma: {p['dock']['lim']['lmin']};
  -lumina-lift-r: {p['dock']['lim']['lift'][0]};
  -lumina-lift-g: {p['dock']['lim']['lift'][1]};
  -lumina-lift-b: {p['dock']['lim']['lift'][2]};
}}

/* ---------- 7. Calendar, notifications ---------- */
.events-button, .world-clocks-button, .weather-button, .message {{
  background-color: {p['card']} !important;
  border: 1px solid {p['border']} !important;
  box-shadow: none !important;
  border-radius: 20px !important;
  color: {p['text']} !important;
}}
.events-button:hover, .world-clocks-button:hover, .weather-button:hover, .message:hover {{
  background-color: {p['card_hover']} !important;
  border-color: {p['border_strong']} !important;
}}
.calendar, .calendar-day, .calendar-month-header .pager-button, .calendar-month-label,
.datemenu-today-button .day-label, .datemenu-today-button .date-label,
.events-title, .events-section-title, .world-clocks-header, .weather-header {{
  color: {p['text']} !important;
}}
.calendar-day-base, .calendar-day {{ background-color: transparent !important; }}
.calendar-day-base:hover, .calendar-day:hover, .calendar-month-header .pager-button:hover,
.calendar-day-base:focus {{ background-color: {p['card_hover']} !important; }}
.calendar-month-header .pager-button, .calendar-month-label {{ background-color: {p['card']} !important; }}
.calendar .calendar-today, .calendar-today {{
  background-color: {p['accent']} !important;
  color: {p['on_accent']} !important;
}}
.calendar-weekend, .calendar-other-month {{ color: {p['text_dim']} !important; }}
"""


def apply_ptyxis_palette(palette):
    """Ptyxis terminal palette from the same tonal system (terminal stays dark in both schemes)."""
    try:
        P, N = palette['T']['P'], palette['T']['N']
        hue = palette['hue']

        def hue_tone(h, L, C):
            return Tone(L, C, h).hex()

        bg = N(0.19, 1.5).hex()
        fg = N(0.93, 0.5).hex()
        cursor = P(0.82).hex()
        normal = [N(0.26, 1.5).hex(), hue_tone(25, 0.70, 0.14), hue_tone(145, 0.76, 0.13),
                  hue_tone(85, 0.82, 0.13), hue_tone(255, 0.72, 0.12), hue_tone(320, 0.72, 0.12),
                  hue_tone(200, 0.78, 0.10), fg]
        bright = [N(0.48, 1.5).hex(), hue_tone(25, 0.78, 0.12), hue_tone(145, 0.84, 0.12),
                  hue_tone(85, 0.89, 0.12), hue_tone(255, 0.80, 0.11), hue_tone(320, 0.80, 0.11),
                  hue_tone(200, 0.86, 0.09), N(0.99, 0.2).hex()]
        _ = hue
        lines = ['[Palette]', 'Name=Monet', f'Background={bg}', f'Foreground={fg}', f'Cursor={cursor}']
        lines += [f'Color{i}={c}' for i, c in enumerate(normal + bright)]
        atomic_write(PTYXIS_PALETTE_PATH, '\n'.join(lines) + '\n')

        prof_cmd = ['gsettings', 'get', 'org.gnome.Ptyxis', 'default-profile-uuid']
        prof_uuid = subprocess.check_output(prof_cmd, stderr=subprocess.DEVNULL).decode().strip().strip("'")
        if prof_uuid:
            key_path = f"org.gnome.Ptyxis.Profile:/org/gnome/Ptyxis/Profiles/{prof_uuid}/"
            subprocess.run(['gsettings', 'set', key_path, 'palette', 'monet'], stderr=subprocess.DEVNULL)
            subprocess.run(['gsettings', 'set', key_path, 'opacity', '0.94'], stderr=subprocess.DEVNULL)
            print("[Monet] Configured Ptyxis terminal profile (Opacity: 0.94, Palette: Monet)")
    except Exception as e:
        print(f"[Monet] Failed to apply Ptyxis palette: {e}", file=sys.stderr)


def apply_gtk_theme(palette):
    """Libadwaita / GTK colours from the same tonal palette as the Shell (light and dark)."""
    try:
        P, N = palette['T']['P'], palette['T']['N']
        is_dark = palette['is_dark']
        accent_enum = palette['accent_enum']
        try:
            Gio.Settings.new('org.gnome.desktop.interface').set_string('accent-color', accent_enum)
        except Exception:
            subprocess.run(['gsettings', 'set', 'org.gnome.desktop.interface', 'accent-color', accent_enum],
                           stderr=subprocess.DEVNULL)

        if is_dark:
            accent_text = P(0.82)            # links / accent-coloured text on dark surfaces
            accent_bg = P(0.70)              # suggested buttons, switches
            accent_fg = P(0.20, 0.04)
            window_bg, view_bg, card_bg = N(0.21, 1.5), N(0.18, 1.5), N(0.26, 1.5)
            header_bg, sidebar_bg, side2_bg = N(0.23, 1.5), N(0.19, 1.5), N(0.17, 1.5)
            fg = N(0.95, 0.4)
        else:
            accent_text = P(0.48)
            accent_bg = P(0.54)
            accent_fg = Tone(0.99, 0.0, 0)
            window_bg, view_bg, card_bg = N(0.975, 0.6), N(0.99, 0.4), N(1.0, 0.0)
            header_bg, sidebar_bg, side2_bg = N(0.955, 0.8), N(0.955, 0.8), N(0.965, 0.7)
            fg = N(0.24, 1.2)
        for _ in range(12):
            if contrast(accent_bg.Y, accent_fg.Y) >= 4.5:
                break
            accent_bg = P(accent_bg.L + (0.02 if is_dark else -0.02))

        a = 0.92
        gtk_css = f"""/* Libadwaita / GTK Monet palette - generated by monet-panel.py */
@define-color accent_color {accent_text.hex()};
@define-color accent_bg_color {accent_bg.hex()};
@define-color accent_fg_color {accent_fg.hex()};

@define-color window_bg_color {window_bg.a(a)};
@define-color window_fg_color {fg.hex()};
@define-color view_bg_color {view_bg.a(a)};
@define-color view_fg_color {fg.hex()};
@define-color headerbar_bg_color {header_bg.a(a)};
@define-color headerbar_fg_color {fg.hex()};
@define-color headerbar_border_color {fg.a(0.10)};
@define-color headerbar_backdrop_color {header_bg.a(a)};
@define-color sidebar_bg_color {sidebar_bg.a(a)};
@define-color sidebar_fg_color {fg.hex()};
@define-color sidebar_backdrop_color {sidebar_bg.a(a)};
@define-color sidebar_border_color {fg.a(0.10)};
@define-color secondary_sidebar_bg_color {side2_bg.a(a)};
@define-color secondary_sidebar_fg_color {fg.hex()};
@define-color secondary_sidebar_backdrop_color {side2_bg.a(a)};
@define-color secondary_sidebar_border_color {fg.a(0.10)};
@define-color card_bg_color {card_bg.a(0.94)};
@define-color card_fg_color {fg.hex()};
@define-color card_border_color {fg.a(0.08)};
@define-color popover_bg_color {card_bg.a(0.97)};
@define-color popover_fg_color {fg.hex()};
@define-color dialog_bg_color {card_bg.a(0.97)};
@define-color dialog_fg_color {fg.hex()};

window.background {{ background-color: @window_bg_color; }}
headerbar, .titlebar {{ background-color: @headerbar_bg_color; }}

popover, popover.background {{ background-color: transparent; box-shadow: none; }}
popover > contents {{
  background-color: @popover_bg_color;
  border-radius: 14px;
  border: 1px solid {fg.a(0.10)};
  box-shadow: 0 4px 16px rgba(0, 0, 0, {0.45 if is_dark else 0.18});
}}

.sidebar-pane, .sidebar, placessidebar, navigation-sidebar, .navigation-sidebar {{
  background-color: @sidebar_bg_color;
  color: @sidebar_fg_color;
}}
.navigation-sidebar row:hover, placessidebar row:hover {{
  background-color: {accent_bg.a(0.14)};
  border-radius: 10px;
}}
.navigation-sidebar row:selected, placessidebar row:selected {{
  background-color: {accent_bg.a(0.24)};
  color: @window_fg_color;
  border-radius: 10px;
}}

textview, textview text, .view {{ background-color: transparent; color: @window_fg_color; }}
.nautilus-window .view, .nautilus-window gridview, .nautilus-window columnview,
.nautilus-window listview, .nautilus-window scrolledwindow {{ background-color: transparent; }}
"""
        atomic_write(GTK4_CSS_PATH, gtk_css)
        atomic_write(GTK3_CSS_PATH, gtk_css)
        print(f"[Monet] Applied GTK/Libadwaita theme (Accent: {accent_enum} / {accent_bg.hex()})")
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
            'org.gnome.Shell',
            '/org/gnome/Shell',
            'org.gnome.Shell.Extensions',
            'DisableExtension',
            GLib.Variant('(s)', (EXTENSION_UUID,)),
            None,
            Gio.DBusCallFlags.NONE,
            1000,
            None,
        )
        bus.call_sync(
            'org.gnome.Shell',
            '/org/gnome/Shell',
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

    # The Shell extension drops a marker while its backdrop blur runs; glass tints are tuned
    # differently with and without blur, so regenerate whenever it appears or disappears.
    runtime_dir = os.environ.get('XDG_RUNTIME_DIR') or f"/run/user/{os.getuid()}"
    state['glass'] = glass_blur_active()

    def on_runtime_change(_mon, file, _other, _event):
        if file and file.get_basename() == GLASS_MARKER and glass_blur_active() != state['glass']:
            state['glass'] = glass_blur_active()
            print(f"[Monet] Liquid-glass backdrop {'active' if state['glass'] else 'inactive'}; regenerating")
            GLib.timeout_add(200, lambda: (apply_all(force=True), False)[1])

    runtime_monitor = Gio.File.new_for_path(runtime_dir).monitor_directory(Gio.FileMonitorFlags.NONE, None)
    runtime_monitor.connect('changed', on_runtime_change)

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
