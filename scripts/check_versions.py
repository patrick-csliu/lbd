"""Check that every component carries the same release version, and that every language
implements the format version of the spec. Prints the release version; exits 1 on mismatch.

Where versions live (version_locations(); scripts/bump_version.py writes the same places):
  - each languages/<id>/language.toml lists its files under [[version]] and [format_version]
  - the viewer: viewer/pyproject.toml, viewer/src/lbd_viewer/__init__.py, viewer/web/package.json
  - the lock files: uv.lock (the workspace packages) and viewer/web/package-lock.json
"""

import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from languages import REPO, discover, read_pattern  # noqa: E402

# (where, file relative to the repository, regex whose group 1 is the version; multiline)
FIXED = [
    ("viewer/pyproject.toml", "viewer/pyproject.toml", r'^version\s*=\s*"([^"]+)"'),
    ("viewer/pyproject.toml (lbd dependency)", "viewer/pyproject.toml", r'"lbd\[plot\]==([^"]+)"'),
    ("viewer/src/lbd_viewer/__init__.py", "viewer/src/lbd_viewer/__init__.py", r'^__version__\s*=\s*"([^"]+)"'),
    ("viewer/web/package.json", "viewer/web/package.json", r'^  "version":\s*"([^"]+)"'),
    ("viewer/web/package-lock.json (top)", "viewer/web/package-lock.json",
     r'\A\{\s*"name":\s*"lbd-viewer-web",\s*"version":\s*"([^"]+)"'),
    ("viewer/web/package-lock.json (root package)", "viewer/web/package-lock.json",
     r'"":\s*\{\s*"name":\s*"lbd-viewer-web",\s*"version":\s*"([^"]+)"'),
    ("uv.lock (lbd)", "uv.lock", r'^name = "lbd"\r?\nversion = "([^"]+)"'),
    ("uv.lock (lbd-viewer)", "uv.lock", r'^name = "lbd-viewer"\r?\nversion = "([^"]+)"'),
]


def version_locations(repo: Path = REPO) -> List[Tuple[str, Path, str]]:
    """Every place that holds the release version, as (where, file, pattern): FIXED plus each
    language's [[version]] entries."""
    places = [(where, repo / rel, pat) for where, rel, pat in FIXED]
    for lang in discover(repo / "languages"):
        for v in lang.data.get("version", []):
            path = lang.dir / v["file"]
            places.append((path.resolve().relative_to(repo.resolve()).as_posix(), path, v["pattern"]))
    return places


def spec_version(repo: Path = REPO) -> str:
    m = re.search(r"version (\d+\.\d+)", (repo / "spec" / "LBD-v1.md").read_text(encoding="utf-8"))
    if not m:
        raise SystemExit("can't find the format version in spec/LBD-v1.md")
    return m.group(1)


def collect(repo: Path = REPO) -> Tuple[Dict[str, Optional[str]], Dict[str, Optional[str]]]:
    """({where: release version}, {file: format version}); None where a version wasn't found."""
    release = {where: read_pattern(path, pat) for where, path, pat in version_locations(repo)}
    fmt = {}
    for lang in discover(repo / "languages"):
        fv = lang.data.get("format_version")
        if fv:
            rel = (lang.dir / fv["file"]).resolve().relative_to(repo.resolve()).as_posix()
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
