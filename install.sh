#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
SYSTEMD_DIR="$HOME/.config/systemd/user"
EXT_UUID="lumina-shell@lumina-live-wallpaper"
# The extension was first developed inside this borrowed extensions.gnome.org UUID.
LEGACY_UUID="avatar-quick-settings@github.leginreklaw"
EXT_DIR="$HOME/.local/share/gnome-shell/extensions/$EXT_UUID"

echo "========================================================"
echo "  Lumina Live Wallpaper & Monet Engine - Linux Installer"
echo "========================================================"

# 1. Check / Install System Dependencies (Fedora / Ubuntu / Arch)
if command -v dnf >/dev/null 2>&1; then
    echo "[1/4] 检测到 Fedora/RHEL 系统，检查依赖..."
    sudo dnf install -y gjs gtk4 gstreamer1-plugins-bad-free-gtk4 gstreamer1-vaapi python3-pillow python3-gobject xprop
elif command -v apt-get >/dev/null 2>&1; then
    echo "[1/4] 检测到 Ubuntu/Debian 系统，检查依赖..."
    sudo apt-get update && sudo apt-get install -y gjs gir1.2-gtk-4.0 gstreamer1.0-gtk4 gstreamer1.0-vaapi python3-pil python3-gi x11-utils
elif command -v pacman >/dev/null 2>&1; then
    echo "[1/4] 检测到 Arch Linux 系统，检查依赖..."
    sudo pacman -S --needed --noconfirm gjs gtk4 gst-plugin-gtk4 gstreamer-vaapi python-pillow python-gobject xorg-xprop
else
    echo "[1/4] 未识别包管理器，请确保已安装: gjs, gtk4, gst-plugin-gtk4, python3-pillow, xprop"
fi

# 2. Install Scripts to ~/.local/bin
echo "[2/4] 安装核心守护进程与命令行工具至 $BIN_DIR ..."
mkdir -p "$BIN_DIR"
cp -f "$REPO_DIR/linux/live-wallpaper-daemon" "$BIN_DIR/live-wallpaper-daemon"
cp -f "$REPO_DIR/linux/set-live-wallpaper" "$BIN_DIR/set-live-wallpaper"
cp -f "$REPO_DIR/linux/monet-panel.py" "$BIN_DIR/monet-panel.py"
cp -f "$REPO_DIR/linux/lumina-migrate-uuid" "$BIN_DIR/lumina-migrate-uuid"
cp -f "$REPO_DIR/linux/lumina-fit-video" "$BIN_DIR/lumina-fit-video"
chmod +x "$BIN_DIR/live-wallpaper-daemon" "$BIN_DIR/set-live-wallpaper" "$BIN_DIR/monet-panel.py" "$BIN_DIR/lumina-migrate-uuid" "$BIN_DIR/lumina-fit-video"

# 3. Install GNOME Shell Extension (Zero-flicker Monet CSS hot-reload & Fullscreen occlusion tracker)
echo "[3/4] 部署 GNOME Shell 莫奈状态栏与全屏检测扩展 ($EXT_UUID) ..."
mkdir -p "$EXT_DIR"
# Every module (extension.js imports glass.js) plus metadata. stylesheet.css is not shipped:
# monet-panel.py generates it from the current wallpaper.
cp -f "$REPO_DIR/linux/extension/$EXT_UUID/"*.js "$EXT_DIR/"
cp -f "$REPO_DIR/linux/extension/$EXT_UUID/metadata.json" "$EXT_DIR/metadata.json"
gsettings set org.gnome.shell disable-user-extensions false || true
# `gnome-extensions enable` only works for an extension the running shell has already loaded, and
# a freshly copied one is only loaded at the next login, so put it in the enabled list directly.
python3 -I - "$EXT_UUID" <<'PY'
import sys
from gi.repository import Gio
uuid, s = sys.argv[1], Gio.Settings.new('org.gnome.shell')
for key, want in (('enabled-extensions', True), ('disabled-extensions', False)):
    v = s.get_strv(key)
    if (uuid in v) != want:
        s.set_strv(key, v + [uuid] if want else [u for u in v if u != uuid])
Gio.Settings.sync()
PY

# 4. Install & Enable systemd User Services
echo "[4/4] 注册并启动 systemd 用户常驻服务..."
mkdir -p "$SYSTEMD_DIR"
cp -f "$REPO_DIR/linux/systemd/live-wallpaper.service" "$SYSTEMD_DIR/live-wallpaper.service"
cp -f "$REPO_DIR/linux/systemd/monet-panel.service" "$SYSTEMD_DIR/monet-panel.service"
# An older install lives under $LEGACY_UUID. Swapping it for $EXT_UUID live would drop the glass
# until the next login anyway, so do the swap at that login, before GNOME Shell starts.
if [ -f "$HOME/.local/share/gnome-shell/extensions/$LEGACY_UUID/glass.js" ]; then
    cp -f "$REPO_DIR/linux/systemd/lumina-migrate-uuid.service" "$SYSTEMD_DIR/lumina-migrate-uuid.service"
    MIGRATE=1
fi

# Screen-sized, <=30 fps playback copies of already registered wallpapers (needs the GNOME session).
"$BIN_DIR/lumina-fit-video" --all || true

systemctl --user daemon-reload
systemctl --user enable --now live-wallpaper.service
systemctl --user enable --now monet-panel.service
[ -n "${MIGRATE:-}" ] && systemctl --user enable lumina-migrate-uuid.service

echo ""
echo "✅ 安装完成！"
echo "注销并重新登录一次后，GNOME Shell 才会加载扩展 $EXT_UUID。"
echo "用法示例:"
echo "  set-live-wallpaper <视频路径.mp4>     # 注册并启用 30fps 硬件加速动态壁纸（自动生成 ▶ LIVE 角标与莫奈配色）"
echo "  set-live-wallpaper --static          # 切换回静态壁纸"
echo "  set-live-wallpaper --live            # 切换回动态壁纸"
echo "  你也可以直接打开「系统设置 -> 外观」点击任意壁纸自由切换！"
