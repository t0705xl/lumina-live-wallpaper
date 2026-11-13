"""Write the Shell stylesheet monet-panel.py would generate, without applying anything system-wide.
usage: gen_css.py <wallpaper> <prefer-dark|default> <out.css>   (LUMINA_GLASS=0/1 picks the tint set)"""
import importlib.util
import os
import sys

here = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('monet_panel', os.path.join(here, '..', '..', 'linux', 'monet-panel.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
wp, scheme, out = sys.argv[1:4]
p = m.extract_palette(wp, scheme)
a = p['analysis']
print(f"hue={p['hue']} chroma={p['chroma']} accent={p['accent']} ({p['accent_enum']}) blur={p['blur']} "
      f"pill_alpha={p['pill_alpha']} popup_alpha={p['popup_alpha']} bar_Y={a['bar_y_lo']:.2f}..{a['bar_y_hi']:.2f}")
with open(out, 'w') as f:
    f.write(m.generate_gnome_shell_css(p))
