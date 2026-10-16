"""Check that every component carries the same release version, and that every language
implements the format version of the spec. Prints the release version; exits 1 on mismatch.

Where versions live:
  - each languages/<id>/language.toml lists its files under [[version]] and [format_version]
  - the viewer: viewer/pyproject.toml, viewer/src/lbd_viewer/__init__.py, viewer/web/package.json
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from languages import REPO, discover, read_pattern  # noqa: E402

VIEWER = [
    ("viewer/pyproject.toml", r'^version\s*=\s*"([^"]+)"'),
    ("viewer/src/lbd_viewer/__init__.py", r'^__version__\s*=\s*"([^"]+)"'),
]


def spec_version() -> str:
    m = re.search(r"version (\d+\.\d+)", (REPO / "spec" / "LBD-v1.md").read_text(encoding="utf-8"))
    if not m:
        raise SystemExit("can't find the format version in spec/LBD-v1.md")
    return m.group(1)


def collect():
    """({file: release version}, {file: format version})"""
    release, fmt = {}, {}
    for rel, pat in VIEWER:
        release[rel] = read_pattern(REPO / rel, pat)
    release["viewer/web/package.json"] = json.loads(
        (REPO / "viewer/web/package.json").read_text(encoding="utf-8"))["version"]
    for lang in discover():
        for v in lang.data.get("version", []):
            rel = (lang.dir / v["file"]).resolve().relative_to(REPO.resolve()).as_posix()
            release[rel] = read_pattern(lang.dir / v["file"], v["pattern"])
        fv = lang.data.get("format_version")
        if fv:
            rel = (lang.dir / fv["file"]).resolve().relative_to(REPO.resolve()).as_posix()
            fmt[rel] = read_pattern(lang.dir / fv["file"], fv["pattern"])
    return release, fmt


class VersionError(Exception):
    """The components don't carry one release version (the message lists them)."""


def release_version() -> str:
    """The one release version of every component; VersionError if they differ or one is missing."""
    release, _ = collect()
    if None in release.values() or len(set(release.values())) != 1:
        listing = "\n".join(f"  {str(v):10s} {k}" for k, v in release.items())
        raise VersionError(f"release versions differ (or were not found):\n{listing}")
    return next(iter(release.values()))


def main() -> int:
    release, fmt = collect()
    spec = spec_version()
    ok = True
    if None in release.values() or len(set(release.values())) != 1:
        ok = False
        print("release versions differ (or were not found):", file=sys.stderr)
        for k, v in release.items():
            print(f"  {str(v):10s} {k}", file=sys.stderr)
    bad_fmt = {k: v for k, v in fmt.items() if v != spec}
    if bad_fmt:
        ok = False
        print(f"format versions differ from the spec ({spec}):", file=sys.stderr)
        for k, v in bad_fmt.items():
            print(f"  {str(v):10s} {k}", file=sys.stderr)
    if not ok:
        return 1
    print(next(iter(release.values())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
