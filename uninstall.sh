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

echo "✅ 已完成卸载。"
