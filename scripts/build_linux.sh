#!/bin/sh
# Build the Linux package of LBD Viewer (a tarball with install.sh).
#
#   sh scripts/build_linux.sh [OUTDIR]          (default OUTDIR: ~/.cache/lbd-build)
#
# Needs: uv, Node.js (npm). Language build tools are optional (e.g. MATLAB builds LBD.mltbx;
# without it the sources are shipped). Run on Linux or WSL2; PyInstaller can not cross-compile.
# Result: OUTDIR/lbd-viewer-<version>-linux-<arch>.tar.gz
set -eu

REPO=$(cd "$(dirname "$0")/.." && pwd)
OUT="${1:-$HOME/.cache/lbd-build}"
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

step "Language modules (sdk)"
uv run python packaging/stage_sdk.py --dest "$OUT/dist/LBDViewer/sdk"

step "Documentation (Help)"
uv run mkdocs build --strict --quiet --site-dir "$OUT/site"
rm -rf "$OUT/dist/LBDViewer/docs"
cp -a "$OUT/site" "$OUT/dist/LBDViewer/docs"

step "Tarball"
ARCH=$(uname -m)
NAME="lbd-viewer-$VERSION-linux-$ARCH"
STAGE="$OUT/$NAME"
rm -rf "$STAGE"
mkdir -p "$STAGE"
cp -a "$OUT/dist/LBDViewer" "$STAGE/LBDViewer"
cp packaging/linux/install.sh packaging/linux/uninstall.sh packaging/linux/lbd-viewer.desktop \
   packaging/linux/lbd-mime.xml packaging/icons/lbd.png packaging/icons/lbd.svg "$STAGE/"
chmod +x "$STAGE/install.sh" "$STAGE/uninstall.sh" "$STAGE/LBDViewer/lbd-view"
cat > "$STAGE/README.txt" <<EOF
LBD Viewer $VERSION for Linux

Install (for the current user, no root needed):
    ./install.sh
Uninstall:
    ./uninstall.sh

After installing, open "LBD Viewer" from the applications menu, run lbd-view, or
double-click an .lbd file. The language modules (Python, MATLAB, Julia, ...) are in
~/.local/share/lbd-viewer/sdk; see "Language modules" in the viewer.
EOF
tar -C "$OUT" -czf "$OUT/$NAME.tar.gz" "$NAME"
printf '\033[32mDone: %s\033[0m\n' "$OUT/$NAME.tar.gz"
