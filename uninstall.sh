#!/usr/bin/env bash
set -euo pipefail

echo "正在停止并卸载 Lumina Live Wallpaper & Monet Engine 服务..."
systemctl --user disable --now live-wallpaper.service 2>/dev/null || true
systemctl --user disable --now monet-panel.service 2>/dev/null || true

rm -f "$HOME/.config/systemd/user/live-wallpaper.service"
rm -f "$HOME/.config/systemd/user/monet-panel.service"
systemctl --user daemon-reload

rm -f "$HOME/.local/bin/live-wallpaper-daemon"
rm -f "$HOME/.local/bin/set-live-wallpaper"
rm -f "$HOME/.local/bin/monet-panel.py"
rm -f "$HOME/.local/bin/lumina-migrate-uuid"
rm -f "$HOME/.local/bin/lumina-fit-video"
# Playback copies made by lumina-fit-video (the original videos are left alone).
rm -rf "$HOME/.local/share/live-wallpaper/fitted"
systemctl --user disable lumina-migrate-uuid.service 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/lumina-migrate-uuid.service"

EXT_UUID="lumina-shell@lumina-live-wallpaper"
gnome-extensions disable "$EXT_UUID" 2>/dev/null || true
python3 -I - "$EXT_UUID" <<'PY'
import sys
from gi.repository import Gio
uuid, s = sys.argv[1], Gio.Settings.new('org.gnome.shell')
s.set_strv('enabled-extensions', [u for u in s.get_strv('enabled-extensions') if u != uuid])
Gio.Settings.sync()
PY
rm -rf "$HOME/.local/share/gnome-shell/extensions/$EXT_UUID"

echo "✅ 已完成卸载。"
