"""The oldest macOS an app bundle can run on, from the libraries inside it (macOS only).

    python3 scripts/macos_min_version.py "LBD Viewer.app"

Every compiled file (Mach-O) records the macOS version it needs ("minos" in `otool -l`). The app
needs the highest of these. Prints it and exits 1 if it is newer than the bundle's
LSMinimumSystemVersion (Info.plist), so the app never claims to run where it can't.
"""

import plistlib
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

Version = Tuple[int, ...]


def parse_versions(otool_output: str) -> List[Version]:
    """The minimum macOS versions in `otool -l` output (LC_BUILD_VERSION and the older
    LC_VERSION_MIN_MACOSX load commands)."""
    found = re.findall(r"^\s*minos (\d+(?:\.\d+)*)", otool_output, re.MULTILINE)
    old = re.findall(r"cmd LC_VERSION_MIN_MACOSX\n.*?\n\s*version (\d+(?:\.\d+)*)", otool_output)
    return [tuple(int(n) for n in v.split(".")) for v in found + old]


def as_text(v: Version) -> str:
    return ".".join(str(n) for n in v)


def highest_minimum(app: Path) -> Optional[Tuple[Version, Path]]:
    best = None
    for f in (app / "Contents").rglob("*"):
        if not f.is_file() or f.is_symlink():
            continue
        with open(f, "rb") as fh:
            magic = fh.read(4)
        if magic not in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xce\xfa\xed\xfe"):   # Mach-O
            continue
        out = subprocess.run(["otool", "-l", str(f)], capture_output=True, text=True).stdout
        for v in parse_versions(out):
            if best is None or v > best[0]:
                best = (v, f)
    return best


def main(argv=None) -> int:
    app = Path((argv or sys.argv[1:])[0])
    declared = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())["LSMinimumSystemVersion"]
    best = highest_minimum(app)
    if best is None:
        print("no compiled files found", file=sys.stderr)
        return 1
    needed, where = best
    print(f"needs macOS {as_text(needed)} (highest: {where.relative_to(app)}); "
          f"Info.plist says {declared}")
    if needed > tuple(int(n) for n in declared.split(".")):
        print(f"::error::The app needs macOS {as_text(needed)} but declares {declared}: "
              f"set MACOS_MIN in packaging/lbd-view.spec and the docs to {as_text(needed)}.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
