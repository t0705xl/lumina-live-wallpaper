"""Set the preview's virtual monitor to a scale factor (logical layout), e.g. 2 for the Surface.
usage: DBUS_SESSION_BUS_ADDRESS=$(cat ~/.cache/lumina-preview/bus) python3 scale.py 2"""
import sys
from gi.repository import Gio, GLib

scale = float(sys.argv[1])
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
call = lambda m, args, ret: bus.call_sync('org.gnome.Mutter.DisplayConfig', '/org/gnome/Mutter/DisplayConfig',
                                          'org.gnome.Mutter.DisplayConfig', m, args, ret, 0, 5000, None).unpack()
serial, monitors, logical, props = call('GetCurrentState', None, GLib.VariantType('(ua((ssss)a(siiddada{sv})a{sv})a(iiduba(ssss)a{sv})a{sv})'))
(connector, *_), modes, _ = monitors[0]
mode = next(m for m in modes if m[6].get('is-current')) if any(m[6].get('is-current') for m in modes) else modes[0]
call('ApplyMonitorsConfig', GLib.Variant('(uua(iiduba(ssa{sv}))a{sv})',
     (serial, 1, [(0, 0, scale, 0, True, [(connector, mode[0], {})])], {})), None)
print(f'{connector} {mode[0]} -> scale {scale}')
