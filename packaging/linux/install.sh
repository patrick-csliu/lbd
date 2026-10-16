#!/bin/sh
# Install LBD Viewer for the current user (no root needed).
#   ./install.sh               (asks to install the Arial font if it is missing)
#   ./install.sh --no-fonts    (skip the font check, e.g. for scripted installs)
# Installs to ~/.local/share/lbd-viewer, adds `lbd-view` to ~/.local/bin, a menu entry,
# and makes double-clicking .lbd files open the viewer.
set -eu

CHECK_FONTS=1
for arg in "$@"; do
    case "$arg" in
        --no-fonts) CHECK_FONTS=0 ;;
        *) echo "usage: $0 [--no-fonts]" >&2; exit 2 ;;
    esac
done

HERE=$(cd "$(dirname "$0")" && pwd)
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
APPDIR="$DATA/lbd-viewer"
BINDIR="$HOME/.local/bin"

if [ ! -x "$HERE/LBDViewer/lbd-view" ]; then
    echo "error: $HERE/LBDViewer/lbd-view not found; run this script from the unpacked folder" >&2
    exit 1
fi

echo "Installing LBD Viewer to $APPDIR"
rm -rf "$APPDIR"
mkdir -p "$APPDIR" "$BINDIR" "$DATA/applications" "$DATA/mime/packages" \
         "$DATA/icons/hicolor/256x256/apps" "$DATA/icons/hicolor/256x256/mimetypes" \
         "$DATA/icons/hicolor/scalable/apps" "$DATA/icons/hicolor/scalable/mimetypes"
cp -a "$HERE/LBDViewer/." "$APPDIR/"
ln -sf "$APPDIR/lbd-view" "$BINDIR/lbd-view"

cp "$HERE/lbd.png" "$DATA/icons/hicolor/256x256/apps/lbd-viewer.png"
cp "$HERE/lbd.png" "$DATA/icons/hicolor/256x256/mimetypes/application-x-lbd.png"
cp "$HERE/lbd.svg" "$DATA/icons/hicolor/scalable/apps/lbd-viewer.svg"
cp "$HERE/lbd.svg" "$DATA/icons/hicolor/scalable/mimetypes/application-x-lbd.svg"

sed "s|@EXEC@|$APPDIR/lbd-view|g" "$HERE/lbd-viewer.desktop" > "$DATA/applications/lbd-viewer.desktop"
chmod 644 "$DATA/applications/lbd-viewer.desktop"
cp "$HERE/lbd-mime.xml" "$DATA/mime/packages/lbd-viewer.xml"

# Register the file type and make the viewer its default app. These tools are optional.
command -v update-mime-database >/dev/null 2>&1 && update-mime-database "$DATA/mime" || true
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$DATA/applications" || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t "$DATA/icons/hicolor" || true
command -v xdg-mime >/dev/null 2>&1 && xdg-mime default lbd-viewer.desktop application/x-lbd || true

echo "Done."
case ":$PATH:" in
    *":$BINDIR:"*) ;;
    *) echo "Note: $BINDIR is not on your PATH; add it to start the viewer with 'lbd-view'." ;;
esac
echo "Open LBD Viewer from your applications menu, or double-click an .lbd file."

# ---- the default style's font -------------------------------------------------------------
# LBD's default style uses Arial, and drawing with a font that isn't installed is an error.
# Arial can't be shipped with LBD (Microsoft's licence), but the system's "core fonts" package
# downloads it; you accept Microsoft's licence there.
has_arial() { command -v fc-list >/dev/null 2>&1 && fc-list : family | grep -qix "arial"; }

arial_help() {
    echo "  Debian/Ubuntu:  sudo apt-get install ttf-mscorefonts-installer"
    echo "  openSUSE:       sudo zypper install fetchmsttfonts"
    echo "  Fedora:         see https://mscorefonts2.sourceforge.net (msttcore-fonts-installer)"
    echo "  Arch:           install ttf-ms-fonts from the AUR"
    echo "Or choose another font for the default style on LBD Viewer's Styles page"
    echo "(e.g. DejaVu Sans, which is always available)."
}

if [ "$CHECK_FONTS" = 1 ] && ! has_arial; then
    echo
    echo "LBD's default style uses the font Arial, which isn't installed."
    answer=n
    if [ -t 0 ]; then
        printf "Install it now? This needs sudo, and you accept Microsoft's core fonts licence. [Y/n] "
        read -r answer || answer=n
        [ -z "$answer" ] && answer=y
    fi
    case "$answer" in
        y|Y|yes|YES)
            if command -v apt-get >/dev/null 2>&1; then
                sudo apt-get install -y ttf-mscorefonts-installer || true
            elif command -v zypper >/dev/null 2>&1; then
                sudo zypper install -y fetchmsttfonts || true
            else
                echo "No automatic install for this system:"
            fi
            command -v fc-cache >/dev/null 2>&1 && fc-cache -f >/dev/null 2>&1 || true ;;
    esac
    if has_arial; then
        echo "Arial is installed."
    else
        echo "Arial is still missing. Figures in the default style need it; install it with:"
        arial_help
    fi
fi
