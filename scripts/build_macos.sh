#!/bin/sh
# Build the macOS app of LBD Viewer: LBD Viewer.app in a disk image (.dmg).
#
#   sh scripts/build_macos.sh [OUTDIR]          (default OUTDIR: ~/Library/Caches/lbd-build)
#
# Needs: macOS, uv, Node.js (npm). Language build tools are optional (e.g. MATLAB builds LBD.mltbx;
# without it the sources are shipped). LBD_PREBUILT="matlab=DIR" uses DIR's files instead of
# building that language (as on GitHub). Builds for this Mac's processor (arm64 or x86_64).
# The app is not signed by a registered Apple developer, only "ad-hoc" (which Apple Silicon needs);
# users approve it once in System Settings, see docs/getting-started/install.md.
# Result: OUTDIR/LBD-Viewer-<version>-macos-<arch>.dmg
set -eu

REPO=$(cd "$(dirname "$0")/.." && pwd)
OUT="${1:-$HOME/Library/Caches/lbd-build}"
mkdir -p "$OUT"
cd "$REPO"
export UV_PROJECT_ENVIRONMENT="$OUT/venv"
step() { printf '\033[36m==> %s\033[0m\n' "$1"; }

step "Checking versions"
VERSION=$(uv run python scripts/check_versions.py)
echo "    version $VERSION"

step "Python build environment ($UV_PROJECT_ENVIRONMENT)"
uv sync --all-packages --group docs

step "Web UI"
(cd viewer/web && npm ci && npm run build)

step "Icons"
uv run python packaging/make_icons.py

step "PyInstaller"
uv run pyinstaller packaging/lbd-view.spec --noconfirm --log-level WARN \
    --distpath "$OUT/dist" --workpath "$OUT/work"
APP="$OUT/dist/LBD Viewer.app"
RESOURCES="$APP/Contents/Resources"

step "Language modules (sdk)"
# shellcheck disable=SC2086  # LBD_PREBUILT may hold several ID=DIR words
uv run python packaging/stage_sdk.py --dest "$RESOURCES/sdk" ${LBD_PREBUILT:+--prebuilt $LBD_PREBUILT}

step "Documentation (Help)"
rm -rf "$RESOURCES/docs"
uv run mkdocs build --strict --quiet --site-dir "$RESOURCES/docs"
cp LICENSE "$RESOURCES/LICENSE"   # MIT: the notice ships with every copy

step "Signature (ad-hoc)"
# Adding files changed the bundle, so sign it again; Apple Silicon refuses an unsigned app.
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict --verbose=2 "$APP"

step "Minimum macOS version"
uv run python scripts/macos_min_version.py "$APP"

step "Disk image"
NAME="LBD-Viewer-$VERSION-macos-$(uname -m)"
STAGE="$OUT/dmg"
rm -rf "$STAGE"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"      # drag the app onto this to install it
hdiutil create -volname "LBD Viewer $VERSION" -srcfolder "$STAGE" -ov -format UDZO "$OUT/$NAME.dmg"
printf '\033[32mDone: %s\033[0m\n' "$OUT/$NAME.dmg"
