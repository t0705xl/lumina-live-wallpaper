#!/bin/bash
# Headless GNOME Shell preview for the Lumina top bar / quick settings.
# Runs a private, isolated gnome-shell (own D-Bus session, dconf, data and runtime dirs) with the
# repo's extension + a generated stylesheet, so the look can be checked by screenshot without
# touching the real desktop or logging out.
#
#   dev/preview/preview.sh shoot <wallpaper> <prefer-dark|default> <tag> [glass=1]   # SUB=1 opens a submenu
#   dev/preview/preview.sh start [scheme] | stop | menu <quickSettings|dateMenu|qsSubmenu|close> | shot <name>
#   X11=1 WP_URI=file://...-cover.png dev/preview/preview.sh start; dev/preview/preview.sh live
#       runs the real live-wallpaper daemon (X11 desktop window) inside the preview
# Screenshots land in $PREVIEW_DIR/run/lumina-debug/.
set -e
REPO=$(cd "$(dirname "$0")/../.." && pwd)
P=${PREVIEW_DIR:-$HOME/.cache/lumina-preview}
UUID=lumina-shell@lumina-live-wallpaper
EXT=$P/data/gnome-shell/extensions

setup() {
    mkdir -p "$P"/{config,cache,run,data/gnome-shell/extensions}; chmod 700 "$P/run"
    ln -sfn "$HOME/.local/share/fonts" "$P/data/fonts"
    ln -sfn "$HOME/.local/share/backgrounds" "$P/data/backgrounds"
    rm -rf "$EXT/$UUID" "$EXT/lumina-debug@lumina-live-wallpaper"
    cp -r "$REPO/linux/extension/$UUID" "$EXT/"
    cp -r "$REPO/dev/preview/lumina-debug@lumina-live-wallpaper" "$EXT/"
    [ -d "$HOME/.local/share/gnome-shell/extensions/Vitals@CoreCoding.com" ] && \
        cp -r "$HOME/.local/share/gnome-shell/extensions/Vitals@CoreCoding.com" "$EXT/" || true
}

bus() { cat "$P/bus"; }
call() {
    export DBUS_SESSION_BUS_ADDRESS=$(bus)
    local owner; owner=$(gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus \
        --method org.freedesktop.DBus.GetNameOwner org.gnome.Shell | tr -d "(',)")
    gdbus call --session --dest "$owner" --object-path /org/lumina/Debug --method "org.lumina.Debug.$1" "$2"
}

case "$1" in
inner)  # runs inside dbus-run-session
    echo "$DBUS_SESSION_BUS_ADDRESS" > "$P/bus"
    gsettings set org.gnome.shell enabled-extensions "['$UUID','lumina-debug@lumina-live-wallpaper','Vitals@CoreCoding.com']"
    gsettings set org.gnome.shell welcome-dialog-last-shown-version '999'
    gsettings set org.gnome.desktop.interface color-scheme "${SCHEME:-prefer-dark}"
    [ -n "$WP_URI" ] && gsettings set org.gnome.desktop.background picture-uri "$WP_URI" && \
        gsettings set org.gnome.desktop.background picture-uri-dark "$WP_URI"
    exec gnome-shell --headless $([ -n "$X11" ] || echo --no-x11) --wayland --virtual-monitor ${PREVIEW_SIZE:-1368x912} ;;
start)
    "$0" stop >/dev/null 2>&1 || true
    systemctl --user reset-failed lumina-preview.scope lumina-live-preview.scope >/dev/null 2>&1 || true
    [ -z "$NOSETUP" ] && setup; rm -f "$P/bus"
    systemd-run --user --scope --quiet --unit=lumina-preview -p MemoryMax=1400M -p MemorySwapMax=0 \
        env -u WAYLAND_DISPLAY -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XDG_SESSION_TYPE \
        XDG_CONFIG_HOME="$P/config" XDG_DATA_HOME="$P/data" XDG_CACHE_HOME="$P/cache" XDG_RUNTIME_DIR="$P/run" \
        SCHEME="${2:-prefer-dark}" WP_URI="$WP_URI" PREVIEW_DIR="$P" X11="$X11" \
        dbus-run-session -- "$0" inner > "$P/shell.log" 2>&1 &
    for _ in $(seq 40); do [ -s "$P/bus" ] && grep -q "GNOME Shell started" "$P/shell.log" 2>/dev/null && break; sleep 0.5; done
    sleep 1.5; call Menu desktop >/dev/null; sleep 1 ;;
stop)   systemctl --user stop lumina-live-preview.scope 2>/dev/null || true; systemctl --user stop lumina-preview.scope ;;
live)   # the real daemon on the preview's Xwayland, D-Bus, dconf and runtime dir (needs X11=1 start)
    DISP=$(grep -oE 'Using public X11 display :[0-9]+' "$P/shell.log" | tail -1 | grep -oE ':[0-9]+')
    [ -n "$DISP" ] || { echo "no Xwayland in the preview (start it with X11=1)"; exit 1; }
    systemd-run --user --scope --quiet --unit=lumina-live-preview -p MemoryMax=800M -p MemorySwapMax=0 \
        env -u WAYLAND_DISPLAY DISPLAY="$DISP" GDK_BACKEND=x11 DBUS_SESSION_BUS_ADDRESS="$(bus)" \
        LIVE_WALLPAPER_RELEASE_AFTER="${LIVE_WALLPAPER_RELEASE_AFTER:-60}" \
        XAUTHORITY="$(ls -t "$P"/run/.mutter-Xwaylandauth.* | head -1)" \
        XDG_CONFIG_HOME="$P/config" XDG_CACHE_HOME="$P/cache" XDG_RUNTIME_DIR="$P/run" \
        gjs "$REPO/linux/live-wallpaper-daemon" > "$P/daemon.log" 2>&1 &
    for _ in $(seq 20); do grep -q Activating "$P/daemon.log" 2>/dev/null && break; sleep 0.5; done
    sleep 2; cat "$P/daemon.log" ;;
pause|play)  # freeze the preview's live wallpaper (as when windows cover it) / let it play again
    DBUS_SESSION_BUS_ADDRESS=$(bus) gdbus emit --session --object-path /org/gnome/LiveWallpaper \
        --signal org.gnome.LiveWallpaper.OcclusionChanged "$([ "$1" = pause ] && echo true || echo false)" ;;
menu)   call Menu "$2" ;;
shot)   call Screenshot "$2" ;;
shoot)
    WP=$2; SC=$3; TAG=$4
    export WP_URI; WP_URI=$(python3 -c "import sys,pathlib;print(pathlib.Path(sys.argv[1]).as_uri())" "$WP")
    setup
    LUMINA_GLASS=${5:-1} python3 "$REPO/dev/preview/gen_css.py" "$WP" "$SC" "$EXT/$UUID/stylesheet.css"
    NOSETUP=1 "$0" start "$SC"
    call Menu quickSettings >/dev/null; sleep 1.6
    [ -n "$SUB" ] && { call Menu qsSubmenu >/dev/null; sleep 1.3; }
    call Screenshot "$TAG"; call Menu close >/dev/null ;;
*) sed -n '2,10p' "$0"; exit 1 ;;
esac
