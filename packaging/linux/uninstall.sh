#!/bin/sh
# Remove LBD Viewer installed by install.sh. At the end it asks whether to delete your LBD
# presets and settings too (default: keep them). Without a terminal they are always kept.
set -eu

DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
CONF="${XDG_CONFIG_HOME:-$HOME/.config}"
STATE="${XDG_STATE_HOME:-$HOME/.local/state}"

rm -rf "$DATA/lbd-viewer"
[ -L "$HOME/.local/bin/lbd-view" ] && rm -f "$HOME/.local/bin/lbd-view"
rm -f "$DATA/applications/lbd-viewer.desktop" \
      "$DATA/mime/packages/lbd-viewer.xml" \
      "$DATA/icons/hicolor/256x256/apps/lbd-viewer.png" \
      "$DATA/icons/hicolor/256x256/mimetypes/application-x-lbd.png" \
      "$DATA/icons/hicolor/scalable/apps/lbd-viewer.svg" \
      "$DATA/icons/hicolor/scalable/mimetypes/application-x-lbd.svg"

# Drop the default-application entry that install.sh added.
for f in "$CONF/mimeapps.list" "$DATA/applications/mimeapps.list"; do
    [ -f "$f" ] && sed -i '/^application\/x-lbd=lbd-viewer\.desktop;\?$/d' "$f"
done

command -v update-mime-database >/dev/null 2>&1 && update-mime-database "$DATA/mime" || true
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$DATA/applications" || true

echo "LBD Viewer removed."

# Presets and settings (also used by the Python module lbd.plot): keep them unless asked.
answer=n
if [ -t 0 ] && [ -d "$CONF/lbd" ]; then
    printf "Also remove your LBD presets and settings (the list of folders) in %s? [y/N] " "$CONF/lbd"
    read -r answer || answer=n
fi
case "$answer" in
    y|Y|yes|YES)
        # To the desktop's trash when there is one, so it can be undone.
        if command -v gio >/dev/null 2>&1 && gio trash "$CONF/lbd" 2>/dev/null; then
            [ -d "$STATE/lbd" ] && gio trash "$STATE/lbd" 2>/dev/null
            echo "Presets, settings and logs moved to the trash."
        else
            rm -rf "$CONF/lbd" "$STATE/lbd"
            echo "Presets, settings and logs deleted (no trash available)."
        fi ;;
    *)
        [ -d "$CONF/lbd" ] && echo "Presets and settings in $CONF/lbd were kept." ;;
esac
