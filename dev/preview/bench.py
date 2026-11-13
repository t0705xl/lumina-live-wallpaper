"""Glass cost benchmark in the headless preview shell (start it first with preview.sh).

A full-screen layer under the bar changes colour 30x a second (like a video wallpaper); for each
case the preview shell's CPU, its frame rate and the GPU busy share (i915 RC6) are measured.
  cases: glass   - the stylesheet as monet-panel generates it
         noglass - the same with every -lumina-blur set to 0 (glass skipped entirely)
         idle    - glass on, no animation
usage: python3 bench.py [seconds] [case ...]
"""
import glob, os, re, subprocess, sys, time

P = os.path.expanduser(os.environ.get('PREVIEW_DIR', '~/.cache/lumina-preview'))
HERE = os.path.dirname(os.path.abspath(__file__))
CSS = os.path.join(P, 'data/gnome-shell/extensions/lumina-shell@lumina-live-wallpaper/stylesheet.css')
RC6 = glob.glob('/sys/class/drm/card*/gt/gt0/rc6_residency_ms')[0]
SECS = float(sys.argv[1]) if len(sys.argv) > 1 else 20
CASES = sys.argv[2:] or ['glass', 'noglass', 'idle']


def menu(which):
    subprocess.run([os.path.join(HERE, 'preview.sh'), 'menu', which], check=True, capture_output=True)


def shell_pid():
    for d in glob.glob('/proc/[0-9]*'):
        try:
            if open(f'{d}/comm').read().strip() != 'gnome-shell':
                continue
            if f'XDG_RUNTIME_DIR={P}/run'.encode() in open(f'{d}/environ', 'rb').read():
                return int(d.split('/')[-1])
        except OSError:
            pass
    sys.exit('preview gnome-shell not running')


def ticks(pid):
    f = open(f'/proc/{pid}/stat').read().rsplit(')', 1)[1].split()
    return int(f[11]) + int(f[12])


def frames():
    lines = [l for l in open(os.path.join(P, 'shell.log'), errors='replace') if 'LUMINA-DEBUG frames' in l]
    m = re.search(r'= ([\d.]+) fps', lines[-1]) if lines else None
    return float(m.group(1)) if m else float('nan')


pid = shell_pid()
orig = open(CSS).read()
hz = os.sysconf('SC_CLK_TCK')
try:
    for case in CASES:
        css = re.sub(r'-lumina-blur:\s*[\d.]+', '-lumina-blur: 0', orig) if case == 'noglass' else orig
        with open(CSS, 'w') as f:
            f.write(css)
        menu('animate:off' if case == 'idle' else 'animate:on')
        time.sleep(4)
        menu('frames:reset')
        t0, c0, r0 = time.monotonic(), ticks(pid), int(open(RC6).read())
        time.sleep(SECS)
        menu('frames:log')
        dt, c1, r1 = time.monotonic() - t0, ticks(pid), int(open(RC6).read())
        time.sleep(0.3)
        cpu = 100 * (c1 - c0) / hz / dt
        print(f'{case:8s} shell CPU {cpu:5.1f}% core   {frames():5.1f} fps   '
              f'{cpu / max(frames(), 1e-9) * 10:5.2f} ms CPU/frame   GPU busy {100 * (1 - (r1 - r0) / (dt * 1000)):4.1f}%',
              flush=True)
finally:
    with open(CSS, 'w') as f:
        f.write(orig)
    menu('animate:off')
