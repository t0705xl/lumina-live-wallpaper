#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
SYSTEMD_DIR="$HOME/.config/systemd/user"
EXT_UUID="avatar-quick-settings@github.leginreklaw"
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
chmod +x "$BIN_DIR/live-wallpaper-daemon" "$BIN_DIR/set-live-wallpaper" "$BIN_DIR/monet-panel.py"

# 3. Install GNOME Shell Extension (Zero-flicker Monet CSS hot-reload & Fullscreen occlusion tracker)
echo "[3/4] 部署 GNOME Shell 莫奈状态栏与全屏检测扩展 ($EXT_UUID) ..."
mkdir -p "$EXT_DIR"
cp -f "$REPO_DIR/linux/extension/$EXT_UUID/extension.js" "$EXT_DIR/extension.js"
cp -f "$REPO_DIR/linux/extension/$EXT_UUID/metadata.json" "$EXT_DIR/metadata.json"
gsettings set org.gnome.shell disable-user-extensions false || true
gnome-extensions enable "$EXT_UUID" 2>/dev/null || true

# 4. Install & Enable systemd User Services
echo "[4/4] 注册并启动 systemd 用户常驻服务..."
mkdir -p "$SYSTEMD_DIR"
cp -f "$REPO_DIR/linux/systemd/live-wallpaper.service" "$SYSTEMD_DIR/live-wallpaper.service"
cp -f "$REPO_DIR/linux/systemd/monet-panel.service" "$SYSTEMD_DIR/monet-panel.service"

systemctl --user daemon-reload
systemctl --user enable --now live-wallpaper.service
systemctl --user enable --now monet-panel.service

echo ""
echo "✅ 安装完成！"
echo "用法示例:"
echo "  set-live-wallpaper <视频路径.mp4>     # 注册并启用 30fps 硬件加速动态壁纸（自动生成 ▶ LIVE 角标与莫奈配色）"
echo "  set-live-wallpaper --static          # 切换回静态壁纸"
echo "  set-live-wallpaper --live            # 切换回动态壁纸"
echo "  你也可以直接打开「系统设置 -> 外观」点击任意壁纸自由切换！"
