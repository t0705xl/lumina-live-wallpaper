import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Clutter from 'gi://Clutter';
import Cogl from 'gi://Cogl';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

// Fixed-function helper: no eval, screenshots only into one runtime dir.
const IFACE = `<node><interface name="org.lumina.Debug">
<method name="Screenshot"><arg type="s" direction="in" name="name"/><arg type="s" direction="out" name="path"/></method>
<method name="Menu"><arg type="s" direction="in" name="which"/><arg type="b" direction="out" name="ok"/></method>
</interface></node>`;

const MENUS = {
    quickSettings: () => Main.panel.statusArea.quickSettings,
    dateMenu: () => Main.panel.statusArea.dateMenu,
};

export default class LuminaDebug extends Extension {
    enable() {
        this._dir = GLib.build_filenamev([GLib.get_user_runtime_dir(), 'lumina-debug']);
        GLib.mkdir_with_parents(this._dir, 0o700);
        this._impl = Gio.DBusExportedObject.wrapJSObject(IFACE, this);
        this._impl.export(Gio.DBus.session, '/org/lumina/Debug');
    }
    disable() {
        this._animate(false);
        this._impl?.unexport();
        this._impl = null;
    }

    // Benchmark load: a translucent full-screen layer over the wallpaper (under windows and the
    // bar) that changes colour 30 times a second, like a 30 fps video wallpaper.
    _animate(on) {
        if (this._animId) {
            GLib.source_remove(this._animId);
            this._animId = 0;
        }
        this._animActor?.destroy();
        this._animActor = null;
        if (!on)
            return;
        const m = Main.layoutManager.primaryMonitor;
        const a = new Clutter.Actor({x: m.x, y: m.y, width: m.width, height: m.height, opacity: 150});
        Main.layoutManager._backgroundGroup.add_child(a);
        this._animActor = a;
        let i = 0;
        this._animId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 33, () => {
            i++;
            const t = i * 0.21;
            a.background_color = new Cogl.Color({
                red: Math.round(128 + 120 * Math.sin(t)),
                green: Math.round(128 + 120 * Math.sin(t + 2.1)),
                blue: Math.round(128 + 120 * Math.sin(t + 4.2)),
                alpha: 255,
            });
            return GLib.SOURCE_CONTINUE;
        });
    }

    // Frame counter for benchmarks: 'frames:reset' starts, 'frames:log' writes the rate to the log.
    _frames(cmd) {
        if (cmd === 'reset') {
            if (!this._paintId)
                this._paintId = global.stage.connect('after-paint', () => this._frameCount++);
            this._frameCount = 0;
            this._frameT0 = GLib.get_monotonic_time();
        } else if (this._paintId) {
            const dt = (GLib.get_monotonic_time() - this._frameT0) / 1e6;
            console.log(`LUMINA-DEBUG frames ${this._frameCount} in ${dt.toFixed(2)} s = ${(this._frameCount / dt).toFixed(1)} fps`);
        }
    }
    // Mirrors the Looking Glass line given to the user: load glass.js into a running Shell whose
    // extension was loaded before glass.js existed (no re-login).
    async _loadGlass(query) {
        const uuid = 'lumina-shell@lumina-live-wallpaper';
        const m = await import(Main.extensionManager.lookup(uuid).dir.get_child('glass.js').get_uri() + query);
        global._luminaGlass?.disable();
        global._luminaGlass = new m.GlassManager();
        global._luminaGlass.enable();
    }

    // Put the first two normal windows into a fixed layout over the work area, for checking
    // when the live wallpaper counts as hidden: halves (tiled), apart (40% each, 20% gap
    // between), small (two small windows), stack (both over the same left half).
    _arrange(layout) {
        const wa = Main.layoutManager.getWorkAreaForMonitor(Main.layoutManager.primaryIndex);
        const wins = global.get_window_actors().map(a => a.meta_window)
            .filter(w => w.get_window_type() === Meta.WindowType.NORMAL);
        const W = wa.width, H = wa.height, half = Math.floor(W / 2), f = Math.round(W * 0.4);
        const layouts = {
            halves: [[0, 0, half, H], [half, 0, W - half, H]],
            apart: [[0, 0, f, H], [W - f, 0, f, H]],
            small: [[40, 40, 420, 320], [520, 80, 420, 320]],
            stack: [[0, 0, half, H], [0, 0, half, H]],
        };
        const rects = layouts[layout];
        if (!rects || wins.length < 2)
            return false;
        wins.slice(0, 2).forEach((w, i) => {
            const [x, y, w2, h2] = rects[i];
            w.move_resize_frame(false, wa.x + x, wa.y + y, w2, h2);
        });
        // A restack, as when the user clicks a window, so the occlusion check runs.
        wins[0].activate(global.get_current_time());
        return true;
    }

    Menu(which) {
        if (which.startsWith('windows:'))
            return this._arrange(which.slice(8));
        if (which === 'loadGlass' || which === 'loadGlassQuery') {
            this._loadGlass(which === 'loadGlassQuery' ? `?v=${Date.now()}` : '')
                .then(() => console.log('LUMINA-DEBUG loadGlass ok'))
                .catch(e => console.log(`LUMINA-DEBUG loadGlass failed: ${e}`));
            return true;
        }
        if (which === 'overview') {
            Main.overview.show();
            return true;
        }
        if (which === 'animate:on' || which === 'animate:off') {
            this._animate(which === 'animate:on');
            return true;
        }
        if (which === 'frames:reset' || which === 'frames:log') {
            this._frames(which.slice(7));
            return true;
        }
        if (which.startsWith('state:')) {
            // Freeze the overview at one point of its zoom (0 desktop, 1 window picker, 2 app
            // grid) so a transition can be checked frame by frame.
            const v = Number(which.slice(6));
            const adj = Main.overview._overview?._controls?._stateAdjustment;
            if (!adj || !Main.overview.visible || !Number.isFinite(v))
                return false;
            // As in a three-finger swipe held mid-way: GNOME only interpolates the layout
            // between states while a gesture or a transition is running.
            adj.remove_transition?.('value');
            adj.gestureInProgress = true;
            adj.value = v;
            return true;
        }
        if (which === 'appGrid') {
            Main.overview.showApps();
            return true;
        }
        if (which === 'desktop') {
            const adj = Main.overview._overview?._controls?._stateAdjustment;
            if (adj)
                adj.gestureInProgress = false;
            Main.overview.hide();
            return true;
        }
        if (which === 'qsSubmenu') {
            const grid = Main.panel.statusArea.quickSettings.menu._grid;
            const t = grid?.get_children().find(c => c.menu && c.menuEnabled !== false && c.has_style_class_name?.('quick-toggle-has-menu'));
            t?.menu.open();
            return !!t;
        }
        if (which === 'close') {
            Main.panel.menuManager.activeMenu?.close();
            return true;
        }
        const btn = MENUS[which]?.();
        if (!btn?.menu)
            return false;
        btn.menu.open();
        return true;
    }
    ScreenshotAsync([name], invocation) {
        const safe = String(name).replace(/[^A-Za-z0-9_.-]/g, '_').slice(0, 64) || 'shot';
        const path = GLib.build_filenamev([this._dir, `${safe}.png`]);
        try {
            const stream = Gio.File.new_for_path(path).replace(null, false, Gio.FileCreateFlags.NONE, null);
            new Shell.Screenshot().screenshot(false, stream, (o, res) => {
                try {
                    o.screenshot_finish(res);
                    stream.close(null);
                    invocation.return_value(new GLib.Variant('(s)', [path]));
                } catch (e) {
                    invocation.return_value(new GLib.Variant('(s)', [`ERROR ${e}`]));
                }
            });
        } catch (e) {
            invocation.return_value(new GLib.Variant('(s)', [`ERROR ${e}`]));
        }
    }
}
