# PyInstaller spec for LBD Viewer (one-folder build; on macOS also the app bundle).
#   pyinstaller packaging/lbd-view.spec --distpath <out>/dist --workpath <out>/work
# Output: <out>/dist/LBDViewer/  (lbd-view[.exe] + _internal/); macOS also <out>/dist/LBD Viewer.app

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
VIEWER_SRC = ROOT / "viewer" / "src"
LBD_SRC = ROOT / "languages" / "python" / "src"
STATIC = VIEWER_SRC / "lbd_viewer" / "static"
ICON = ROOT / "packaging" / "icons" / "lbd.ico"

if not (STATIC / "index.html").is_file():
    raise SystemExit(f"web UI not built: {STATIC} (run `npm run build` in viewer/web/)")

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(VIEWER_SRC), str(LBD_SRC)],
    datas=[(str(STATIC), "lbd_viewer/static")],
    # matplotlib picks its output backends by name at savefig() time, so list them explicitly.
    hiddenimports=collect_submodules("uvicorn") + collect_submodules("lbd_viewer") + collect_submodules("lbd") + [
        "matplotlib.backends.backend_agg",
        "matplotlib.backends.backend_svg",
        "matplotlib.backends.backend_pdf",
    ],
    excludes=["IPython", "pytest", "PyQt5", "PyQt6", "PySide2", "PySide6", "notebook", "jupyter_client"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="lbd-view",
    console=False,  # Windows: no console window; output goes to a log file (see entry.py)
    icon=str(ICON) if sys.platform == "win32" and ICON.is_file() else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="LBDViewer")

if sys.platform == "darwin":
    # macOS: an app bundle that opens .lbd files from Finder (lbd_viewer/macapp.py handles them).
    sys.path.insert(0, str(ROOT / "scripts"))
    from check_versions import release_version

    VERSION = release_version()
    # The oldest macOS the app runs on. scripts/build_macos.sh checks that no bundled library
    # needs a newer one.
    MACOS_MIN = "14.0"   # measured by the first release build (1.0.0): bundled libraries need 14
    LBD_TYPE = "io.github.patrick-csliu.lbd.data"
    app = BUNDLE(
        coll,
        name="LBD Viewer.app",
        icon=str(ROOT / "packaging" / "icons" / "lbd.icns"),
        bundle_identifier="io.github.patrick-csliu.lbd",
        version=VERSION,
        info_plist={
            "CFBundleName": "LBD Viewer",
            "CFBundleDisplayName": "LBD Viewer",
            "CFBundleShortVersionString": VERSION,
            "LSMinimumSystemVersion": MACOS_MIN,
            "NSHighResolutionCapable": True,
            # LBD Viewer opens .lbd files (double-click, "Open With")...
            "CFBundleDocumentTypes": [{
                "CFBundleTypeName": "LBD data file",
                "CFBundleTypeRole": "Viewer",
                "LSHandlerRank": "Owner",
                "LSItemContentTypes": [LBD_TYPE],
            }],
            # ...and tells macOS what a .lbd file is.
            "UTExportedTypeDeclarations": [{
                "UTTypeIdentifier": LBD_TYPE,
                "UTTypeDescription": "LBD data file",
                "UTTypeConformsTo": ["public.data"],
                "UTTypeIconFile": "lbd.icns",
                "UTTypeTagSpecification": {
                    "public.filename-extension": ["lbd"],
                    "public.mime-type": ["application/x-lbd"],
                },
            }],
        },
    )
