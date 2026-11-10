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
import St from 'gi://St';
import AccountsService from 'gi://AccountsService';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as UserWidget from 'resource:///org/gnome/shell/ui/userWidget.js';

export default class QuickSettingsAvatarExtension extends Extension {
    enable() {
        this._avatar = null;
        this._idleId = 0;
        this._cssReloadIdleId = 0;
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
    }

    disable() {
        Main.panel.statusArea.quickSettings?.disconnectObject(this);
        global.display?.disconnectObject(this);
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

        if (this._cssMonitor) {
            this._cssMonitor.cancel();
            this._cssMonitor = null;
        }

        this._removeAvatar();
    }

    _setupStylesheetHotReload() {
        try {
            this._cssMonitor = this.dir.monitor_directory(
                Gio.FileMonitorFlags.WATCH_MOVES,
                null
            );
            this._cssMonitor.connect('changed', (_mon, file, otherFile, eventType) => {
                const name = file?.get_basename() ?? '';
                const otherName = otherFile?.get_basename() ?? '';
                if (name !== 'stylesheet.css' && otherName !== 'stylesheet.css')
                    return;

                if (
                    eventType !== Gio.FileMonitorEvent.CHANGES_DONE_HINT &&
                    eventType !== Gio.FileMonitorEvent.MOVED_IN &&
                    eventType !== Gio.FileMonitorEvent.CREATED &&
                    eventType !== Gio.FileMonitorEvent.CHANGED
                )
                    return;

                if (this._cssReloadIdleId)
                    GLib.source_remove(this._cssReloadIdleId);

                this._cssReloadIdleId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 25, () => {
                    this._cssReloadIdleId = 0;
                    this._reloadStylesheetSeamless();
                    return GLib.SOURCE_REMOVE;
                });
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

            if (this.stylesheet)
                theme.unload_stylesheet(this.stylesheet);

            theme.load_stylesheet(cssFile);
            this.stylesheet = cssFile;
        } catch (e) {
            logError(e, `${this.metadata.name}: failed to reload stylesheet`);
        }
    }

    _setupWallpaperOcclusionTracker() {
        try {
            const update = () => this._updateOcclusionState();
            global.display.connectObject('in-fullscreen-changed', update, this);
            Main.overview.connectObject(
                'showing', update,
                'hidden', update,
                this
            );
            global.workspace_manager?.connectObject(
                'active-workspace-changed', update,
                this
            );
            this._updateOcclusionState();
        } catch (e) {
            logError(e, `${this.metadata.name}: failed to setup occlusion tracker`);
        }
    }

    _updateOcclusionState() {
        try {
            const inFullscreen = Boolean(Main.layoutManager.primaryMonitor?.inFullscreen);
            const inOverview = Boolean(Main.overview?.visible);
            const occluded = inFullscreen && !inOverview;

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