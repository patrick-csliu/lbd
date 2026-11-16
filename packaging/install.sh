#!/bin/sh
# Install (or upgrade) LBD Viewer on Linux from the latest release on GitHub, for this user.
#
#   curl -fsSL https://github.com/patrick-csliu/lbd/releases/latest/download/install.sh | sh
#   curl -fsSL https://github.com/patrick-csliu/lbd/releases/latest/download/install.sh | sh -s -- --desktop
#
# Options are those of the package's own install.sh: --desktop / --no-desktop (a desktop
# shortcut; default no), --no-menu (not in the applications menu; default yes), --no-fonts (skip
# the Arial check). Without a terminal its questions take the defaults.
#
# What it does: downloads SHA256SUMS and this computer's package (lbd-viewer-<version>-linux-
# <arch>.tar.gz) of the latest release, checks the package's SHA-256 against SHA256SUMS,
# unpacks it and runs its install.sh, which does the rest (as when you run it by hand: stops a
# running viewer, refuses an older version, the menu entry and the .lbd file type). The download
# is deleted afterwards, also when something fails, so nothing is left half-installed.
#
# For tests: LBD_RELEASE_BASE replaces the release's address (a URL, or a local folder holding
# SHA256SUMS and the package), and LBD_INSTALL_CHECK_ONLY=1 stops after the checksum check.
set -eu

BASE="${LBD_RELEASE_BASE:-https://github.com/patrick-csliu/lbd/releases/latest/download}"
BASE=${BASE%/}

say() { printf '==> %s\n' "$1"; }
fail() { printf 'LBD Viewer was not installed: %s\n' "$1" >&2; exit 1; }

for arg in "$@"; do
    case "$arg" in
        --desktop|--no-desktop|--menu|--no-menu|--no-fonts) ;;
        *) fail "unknown option $arg (known: --desktop, --no-desktop, --no-menu, --no-fonts)" ;;
    esac
done

# fetch NAME DEST: one file of the release (from the web, or a local folder for tests)
fetch() {
    if [ -d "$BASE" ]; then
        cp "$BASE/$1" "$2"
    elif command -v curl >/dev/null 2>&1; then
        curl -fsSL --retry 2 -o "$2" "$BASE/$1"
    elif command -v wget >/dev/null 2>&1; then
        wget -q -O "$2" "$BASE/$1"
    else
        fail "neither curl nor wget is installed; install one of them, then try again"
    fi
}

sha256() {
    if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
    elif command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | cut -d' ' -f1
    else fail "no sha256sum or shasum to check the download with; install coreutils, then try again"
    fi
}

TMP=$(mktemp -d "${TMPDIR:-/tmp}/lbd-install.XXXXXX") || fail "couldn't make a temporary folder"
trap 'rm -rf "$TMP"' EXIT INT TERM

ARCH=$(uname -m)
say "Fetching the list of files and checksums (SHA256SUMS) from $BASE"
fetch SHA256SUMS "$TMP/SHA256SUMS" ||
    fail "couldn't download SHA256SUMS. Check the internet connection (or proxy), then try again."

# Lines are "<sha256>  <file name>", as sha256sum writes them.
LINE=$(grep -E "^[0-9a-fA-F]{64} [ *]?lbd-viewer-[^ ]+-linux-$ARCH\.tar\.gz\$" "$TMP/SHA256SUMS" | head -n 1 || true)
[ -n "$LINE" ] || fail "this release has no Linux package for $ARCH (SHA256SUMS names none)"
EXPECTED=$(echo "$LINE" | cut -d' ' -f1 | tr 'A-F' 'a-f')
NAME=$(echo "$LINE" | sed 's/^[0-9a-fA-F]* [ *]*//')

say "Downloading $NAME"
fetch "$NAME" "$TMP/$NAME" ||
    fail "couldn't download $NAME. Check the internet connection (or proxy), then try again."

say "Checking its SHA-256 checksum"
GOT=$(sha256 "$TMP/$NAME")
if [ "$GOT" != "$EXPECTED" ]; then
    fail "the checksum of $NAME doesn't match SHA256SUMS (expected $EXPECTED, got $GOT). The download is damaged or not the published file; it was deleted. Try again later."
fi
echo "    ok: $GOT"
if [ "${LBD_INSTALL_CHECK_ONLY:-}" = 1 ]; then
    say "Checked (LBD_INSTALL_CHECK_ONLY): not installing"
    exit 0
fi

say "Unpacking"
tar -xzf "$TMP/$NAME" -C "$TMP" || fail "couldn't unpack $NAME (no space left?)"
DIR="$TMP/${NAME%.tar.gz}"
[ -f "$DIR/install.sh" ] || fail "$NAME holds no install.sh; this package is incomplete"

say "Running the package's install.sh"
sh "$DIR/install.sh" "$@" </dev/null || fail "the package's install.sh stopped (see above)"
