/* extension.js
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 2 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 *
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import Gio from 'gi://Gio';
import Meta from 'gi://Meta';
import St from 'gi://St';
import AccountsService from 'gi://AccountsService';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as UserWidget from 'resource:///org/gnome/shell/ui/userWidget.js';

import {GlassManager} from './glass.js';

export default class QuickSettingsAvatarExtension extends Extension {
    enable() {
        this._avatar = null;
        this._idleId = 0;
        this._cssReloadIdleId = 0;
        this._occlusionIdleId = 0;
        this._cssMonitor = null;
        this._lastOccluded = null;
        this._modificationFailed = false;

        Main.panel.statusArea.quickSettings.connectObject(
            'destroy',
            () => this._removeAvatar(),
            this
        );

        if (!this._modifySystemItem())
            this._queueModifySystemItem();

        this._setupStylesheetHotReload();
        this._setupWallpaperOcclusionTracker();

        try {
            this._glass = new GlassManager();
            this._glass.enable();
        } catch (e) {
            logError(e, `${this.metadata.name}: liquid glass backdrop unavailable`);
            this._glass = null;
        }
    }

    disable() {
        this._glass?.disable();
        this._glass = null;

        Main.panel.statusArea.quickSettings?.disconnectObject(this);
        global.display?.disconnectObject(this);
        global.window_manager?.disconnectObject(this);
        Main.overview?.disconnectObject(this);
        global.workspace_manager?.disconnectObject(this);

        if (this._idleId) {
            GLib.source_remove(this._idleId);
            this._idleId = 0;
        }

        if (this._cssReloadIdleId) {
            GLib.source_remove(this._cssReloadIdleId);
            this._cssReloadIdleId = 0;
        }

        if (this._occlusionIdleId) {
            GLib.source_remove(this._occlusionIdleId);
            this._occlusionIdleId = 0;
        }

        if (this._cssDirMonitor) {
            this._cssDirMonitor.cancel();
            this._cssDirMonitor = null;
        }

        if (this._cssFileMonitor) {
            this._cssFileMonitor.cancel();
            this._cssFileMonitor = null;
        }

        for (const marker of ['monet-hot-reload-active', 'live-wallpaper-occluded']) {
            try {
                const path = GLib.build_filenamev([GLib.get_user_runtime_dir(), marker]);
                GLib.unlink(path);
            } catch (_e) {
                // Ignore if marker does not exist
            }
        }

        this._removeAvatar();
    }

    _setupStylesheetHotReload() {
        try {
            const markerPath = GLib.build_filenamev([
                GLib.get_user_runtime_dir(),
                'monet-hot-reload-active',
            ]);
            GLib.file_set_contents(markerPath, '1');

            const triggerReload = () => {
                if (this._cssReloadIdleId)
                    GLib.source_remove(this._cssReloadIdleId);

                this._cssReloadIdleId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 25, () => {
                    this._cssReloadIdleId = 0;
                    this._reloadStylesheetSeamless();
                    return GLib.SOURCE_REMOVE;
                });
            };

            // Monitor both directory (for atomic renames) and the css file directly (for in-place writes)
            this._cssDirMonitor = this.dir.monitor_directory(
                Gio.FileMonitorFlags.NONE,
                null
            );
            this._cssDirMonitor.connect('changed', (_mon, file, otherFile, _event) => {
                const name = file?.get_basename() ?? '';
                const otherName = otherFile?.get_basename() ?? '';
                if (name === 'stylesheet.css' || otherName === 'stylesheet.css')
                    triggerReload();
            });

            const cssFile = this.dir.get_child('stylesheet.css');
            this._cssFileMonitor = cssFile.monitor_file(
                Gio.FileMonitorFlags.NONE,
                null
            );
            this._cssFileMonitor.connect('changed', (_mon, _file, _otherFile, _event) => {
                triggerReload();
            });
        } catch (e) {
            logError(e, `${this.metadata.name}: failed to setup CSS hot reload`);
        }
    }

    _reloadStylesheetSeamless() {
        try {
            const cssFile = this.dir.get_child('stylesheet.css');
            if (!cssFile.query_exists(null))
                return;

            const themeContext = St.ThemeContext.get_for_stage(global.stage);
            const theme = themeContext?.get_theme();
            if (!theme)
                return;

            const ext = Main.extensionManager?.lookup(this.uuid);
            if (ext?.stylesheet) {
                theme.unload_stylesheet(ext.stylesheet);
                delete ext.stylesheet;
            }
            if (this.stylesheet) {
                theme.unload_stylesheet(this.stylesheet);
                delete this.stylesheet;
            }

            theme.load_stylesheet(cssFile);
            this.stylesheet = cssFile;
            if (ext)
                ext.stylesheet = cssFile;
            log(`${this.metadata.name}: Hot reloaded stylesheet.css successfully`);
        } catch (e) {
            logError(e, `${this.metadata.name}: failed to reload stylesheet`);
        }
    }

    _setupWallpaperOcclusionTracker() {
        try {
            const scheduleUpdate = () => {
                if (this._occlusionIdleId)
                    GLib.source_remove(this._occlusionIdleId);
                this._occlusionIdleId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 80, () => {
                    this._occlusionIdleId = 0;
                    this._updateOcclusionState();
                    return GLib.SOURCE_REMOVE;
                });
            };

            global.display.connectObject(
                'in-fullscreen-changed', scheduleUpdate,
                'restacked', scheduleUpdate,
                'notify::focus-window', scheduleUpdate,
                this
            );
            global.window_manager?.connectObject(
                'size-change', scheduleUpdate,
                'minimize', scheduleUpdate,
                'unminimize', scheduleUpdate,
                'map', scheduleUpdate,
                'destroy', scheduleUpdate,
                this
            );
            Main.overview.connectObject(
                'showing', scheduleUpdate,
                'hidden', scheduleUpdate,
                this
            );
            global.workspace_manager?.connectObject(
                'active-workspace-changed', scheduleUpdate,
                this
            );
            this._updateOcclusionState();
        } catch (e) {
            logError(e, `${this.metadata.name}: failed to setup occlusion tracker`);
        }
    }

    _isPrimaryDesktopOccluded() {
        if (Main.overview?.visible)
            return false;

        if (Main.layoutManager.primaryMonitor?.inFullscreen)
            return true;

        const primaryIdx = Main.layoutManager.primaryIndex ?? 0;
        const activeWs = global.workspace_manager?.get_active_workspace?.();
        if (!activeWs)
            return false;

        const workArea = Main.layoutManager.getWorkAreaForMonitor?.(primaryIdx);
        const windows = activeWs.list_windows?.() ?? [];

        for (const win of windows) {
            if (!win || win.minimized || !win.showing_on_its_workspace?.())
                continue;
            if (win.get_monitor?.() !== primaryIdx)
                continue;

            const wType = win.get_window_type?.();
            if (wType !== Meta.WindowType.NORMAL)
                continue;

            const title = win.get_title?.() ?? '';
            if (title === 'GNOME Live Wallpaper')
                continue;

            if (win.is_fullscreen?.())
                return true;

            if (typeof win.get_maximized === 'function' && win.get_maximized() === Meta.MaximizeFlags.BOTH)
                return true;

            if (win.maximized_horizontally && win.maximized_vertically)
                return true;

            if (workArea && typeof win.get_frame_rect === 'function') {
                const rect = win.get_frame_rect();
                if (rect.width >= workArea.width * 0.94 && rect.height >= workArea.height * 0.94)
                    return true;
            }
        }

        return false;
    }

    _updateOcclusionState() {
        try {
            const occluded = this._isPrimaryDesktopOccluded();

            if (this._lastOccluded === occluded)
                return;

            this._lastOccluded = occluded;

            const runtimeFile = GLib.build_filenamev([
                GLib.get_user_runtime_dir(),
                'live-wallpaper-occluded',
            ]);
            GLib.file_set_contents(runtimeFile, occluded ? '1' : '0');

            Gio.DBus.session.emit_signal(
                null,
                '/org/gnome/LiveWallpaper',
                'org.gnome.LiveWallpaper',
                'OcclusionChanged',
                new GLib.Variant('(b)', [occluded])
            );
        } catch (_e) {
            // Ignore transient occlusion signal errors
        }
    }

    _removeAvatar() {
        if (this._avatar) {
            this._avatar.destroy();
            this._avatar = null;
        }
    }

    _modifySystemItem() {
        if (this._avatar)
            return true;

        try {
            const quickSettings = Main.panel.statusArea.quickSettings;
            const menuBox = quickSettings?.menu?.box;

            if (!menuBox)
                return false;

            const userManager = AccountsService.UserManager.get_default();
            const user = userManager.get_user(GLib.get_user_name());

            this._avatar = new UserWidget.UserWidget(user);

            menuBox.insert_child_at_index(this._avatar, 0);

            for (const child of this._avatar.get_children()) {
                if (!(child instanceof GObject.Object))
                    continue;

                if (!child.has_style_class_name?.('user-icon'))
                    child.add_style_class_name?.('user-widget-label');
            }

            return true;
        } catch (e) {
            logError(
                e,
                `${this.metadata.name}: failed to add avatar to quick settings`
            );

            this._modificationFailed = true;
            return false;
        }
    }

    _queueModifySystemItem() {
        if (this._idleId)
            return;

        this._idleId = GLib.idle_add(GLib.PRIORITY_DEFAULT, () => {
            const done =
                this._modifySystemItem() || this._modificationFailed;

            if (done)
                this._idleId = 0;

            return done ? GLib.SOURCE_REMOVE : GLib.SOURCE_CONTINUE;
        });
    }
}