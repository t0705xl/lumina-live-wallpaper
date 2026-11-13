import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
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
        this._impl?.unexport();
        this._impl = null;
    }
    // Mirrors the Looking Glass line given to the user: load glass.js into a running Shell whose
    // extension was loaded before glass.js existed (no re-login).
    async _loadGlass(query) {
        const uuid = 'avatar-quick-settings@github.leginreklaw';
        const m = await import(Main.extensionManager.lookup(uuid).dir.get_child('glass.js').get_uri() + query);
        global._luminaGlass?.disable();
        global._luminaGlass = new m.GlassManager();
        global._luminaGlass.enable();
    }

    Menu(which) {
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
        if (which === 'appGrid') {
            Main.overview.showApps();
            return true;
        }
        if (which === 'desktop') {
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
