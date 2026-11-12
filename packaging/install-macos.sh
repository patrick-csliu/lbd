#!/bin/sh
# Install (or upgrade) LBD Viewer on macOS from the latest release on GitHub.
#
#   curl -fsSL https://github.com/patrick-csliu/lbd/releases/latest/download/install-macos.sh | sh
#
# What it does: downloads SHA256SUMS and the disk image for this Mac (Apple Silicon: arm64,
# Intel: x86_64) of the latest release, checks the disk image's SHA-256 against SHA256SUMS,
# opens it, and copies LBD Viewer.app to /Applications, replacing an older one (a running viewer
# is asked to stop first). It refuses to replace a newer LBD Viewer. The .lbd file type comes
# with the app. The download is deleted and the disk image closed afterwards, also when
# something fails, and the old app is only replaced once the new one is completely copied.
#
# For tests: LBD_RELEASE_BASE replaces the release's address (a URL, or a local folder holding
# SHA256SUMS and the disk image), LBD_INSTALL_CHECK_ONLY=1 stops after the checksum check, and
# LBD_APPLICATIONS replaces /Applications.
set -eu

BASE="${LBD_RELEASE_BASE:-https://github.com/patrick-csliu/lbd/releases/latest/download}"
BASE=${BASE%/}
APPS="${LBD_APPLICATIONS:-/Applications}"
APP="$APPS/LBD Viewer.app"

say() { printf '==> %s\n' "$1"; }
fail() { printf 'LBD Viewer was not installed: %s\n' "$1" >&2; exit 1; }

[ $# -eq 0 ] || fail "install-macos.sh takes no options"

fetch() {
    if [ -d "$BASE" ]; then
        cp "$BASE/$1" "$2"
    else
        curl -fsSL --retry 2 -o "$2" "$BASE/$1"
    fi
}

# versions as in lbd_viewer/updates.py: version_newer A B is true if A is newer than B
version_fields() {
    v=$1; rel=1
    case "$v" in *-dev) rel=0; v=${v%-dev} ;; esac
    echo "$v" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' || return 1
    echo "$v $rel" | tr . ' '
}
version_newer() {
    a=$(version_fields "$1") || return 1
    b=$(version_fields "$2") || return 1
    awk -v a="$a" -v b="$b" 'BEGIN { split(a, x, " "); split(b, y, " ")
        for (i = 1; i <= 4; i++) { if (x[i] + 0 > y[i] + 0) exit 0; if (x[i] + 0 < y[i] + 0) exit 1 }
        exit 1 }'
}
app_version() { /usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "$1/Contents/Info.plist" 2>/dev/null || true; }

TMP=$(mktemp -d "${TMPDIR:-/tmp}/lbd-install.XXXXXX") || fail "couldn't make a temporary folder"
MNT="$TMP/mnt"
cleanup() {
    [ -d "$MNT" ] && hdiutil detach -quiet "$MNT" 2>/dev/null || true
    rm -rf "$TMP" "$APPS/.LBD Viewer.app.new" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

case "$(uname -m)" in
    arm64) ARCH=arm64 ;;
    x86_64) ARCH=x86_64 ;;
    *) fail "no LBD Viewer for this Mac's processor ($(uname -m))" ;;
esac

say "Fetching the list of files and checksums (SHA256SUMS) from $BASE"
fetch SHA256SUMS "$TMP/SHA256SUMS" ||
    fail "couldn't download SHA256SUMS. Check the internet connection (or proxy), then try again."
LINE=$(grep -E "^[0-9a-fA-F]{64} [ *]?LBD-Viewer-[^ ]+-macos-$ARCH\.dmg\$" "$TMP/SHA256SUMS" | head -n 1 || true)
[ -n "$LINE" ] || fail "this release has no disk image for $ARCH Macs (SHA256SUMS names none)"
EXPECTED=$(echo "$LINE" | cut -d' ' -f1 | tr 'A-F' 'a-f')
NAME=$(echo "$LINE" | sed 's/^[0-9a-fA-F]* [ *]*//')

say "Downloading $NAME"
fetch "$NAME" "$TMP/$NAME" ||
    fail "couldn't download $NAME. Check the internet connection (or proxy), then try again."

say "Checking its SHA-256 checksum"
GOT=$(shasum -a 256 "$TMP/$NAME" | cut -d' ' -f1)
if [ "$GOT" != "$EXPECTED" ]; then
    fail "the checksum of $NAME doesn't match SHA256SUMS (expected $EXPECTED, got $GOT). The download is damaged or not the published file; it was deleted. Try again later."
fi
echo "    ok: $GOT"
if [ "${LBD_INSTALL_CHECK_ONLY:-}" = 1 ]; then
    say "Checked (LBD_INSTALL_CHECK_ONLY): not installing"
    exit 0
fi

[ -w "$APPS" ] || fail "no permission to write to $APPS; sign in as an administrator, or ask one"

say "Opening the disk image"
mkdir -p "$MNT"
hdiutil attach -quiet -nobrowse -readonly -mountpoint "$MNT" "$TMP/$NAME" || fail "couldn't open $NAME"
[ -d "$MNT/LBD Viewer.app" ] || fail "$NAME holds no LBD Viewer.app"

NEW_VERSION=$(app_version "$MNT/LBD Viewer.app")
OLD_VERSION=$(app_version "$APP")
if version_newer "$OLD_VERSION" "$NEW_VERSION"; then
    fail "LBD Viewer $OLD_VERSION is installed, newer than this one ($NEW_VERSION). To go back to $NEW_VERSION, drag $APP to the Trash first, then run this again. Your settings and Library are kept."
fi

say "Copying LBD Viewer $NEW_VERSION to $APPS"
rm -rf "$APPS/.LBD Viewer.app.new"
ditto "$MNT/LBD Viewer.app" "$APPS/.LBD Viewer.app.new" || fail "couldn't copy the app (no space left?)"
if [ -d "$APP" ]; then
    # gently first: labels still waiting are written; then by force what still runs from it
    "$APP/Contents/MacOS/lbd-view" --stop >/dev/null 2>&1 || true
    pkill -f "$APP/Contents/MacOS/" 2>/dev/null || true
    rm -rf "$APP" || fail "couldn't remove the old $APP"
fi
mv "$APPS/.LBD Viewer.app.new" "$APP" || fail "couldn't put the app in place"
say "Done. Open LBD Viewer from Launchpad or Spotlight, or double-click an .lbd file."
