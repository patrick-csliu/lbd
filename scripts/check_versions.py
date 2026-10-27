"""Check that every component carries the same release version, and that every language
implements the format version of the spec. Prints the version (e.g. 1.2.0 or 1.2.0-dev);
exits 1 on mismatch.

Where versions live (version_locations(); scripts/bump_version.py writes the same places):
  - each languages/<id>/language.toml lists its files under [[version]] and [format_version]
  - the viewer: viewer/pyproject.toml, viewer/src/lbd_viewer/__init__.py, viewer/web/package.json
  - the lock files: uv.lock (the workspace packages) and viewer/web/package-lock.json

Versions are X.Y.Z, or X.Y.Z-dev while the next version is in development. Each ecosystem spells
the development version its own way, and every file must use its own spelling (`form_of`):

    form       files                                          1.2.0 in development
    "python"   pyproject.toml, *.py, uv.lock                  1.2.0.dev0   (PEP 440, as uv writes it)
    "npm"      package.json, package-lock.json                1.2.0-dev.0  (npm needs a number after it)
    "text"     everything else (Julia, MATLAB, ...)           1.2.0-dev

All of them sort before 1.2.0, so a development build never passes for the release.
"""

import re
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

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


DEV_SUFFIX = {"python": ".dev0", "npm": "-dev.0", "text": "-dev"}


class Version(NamedTuple):
    major: int
    minor: int
    patch: int
    dev: bool = False

    def spell(self, form: str = "text") -> str:
        """The version as `form` writes it ("python", "npm", "text"), or "number" for X.Y.Z alone
        (where only numbers are allowed: the MATLAB toolbox, the Windows file version)."""
        number = f"{self.major}.{self.minor}.{self.patch}"
        return number + (DEV_SUFFIX[form] if self.dev and form != "number" else "")

    def __str__(self) -> str:
        return self.spell("text")

    def order(self) -> Tuple[int, int, int, int]:
        """For comparing versions: 1.2.0-dev comes after 1.1.0 and before 1.2.0."""
        return (self.major, self.minor, self.patch, 0 if self.dev else 1)


def form_of(path: Path) -> str:
    """How the file at `path` spells a development version (see the table above)."""
    if path.name in ("pyproject.toml", "uv.lock") or path.suffix == ".py":
        return "python"
    if path.name in ("package.json", "package-lock.json"):
        return "npm"
    return "text"


def parse_version(text: str, form: str = "text") -> Optional[Version]:
    """`text` as a Version if it is X.Y.Z or X.Y.Z plus `form`'s development suffix, else None."""
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(" + re.escape(DEV_SUFFIX[form]) + ")?", text or "")
    if not m:
        return None
    return Version(int(m[1]), int(m[2]), int(m[3]), m[4] is not None)


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
    """({where: release version as written}, {file: format version}); None where not found."""
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


def the_version(repo: Path = REPO) -> Version:
    """The one version of every component; VersionError if they differ, if one is missing, or
    if a file doesn't spell it its own way (e.g. 1.2.0-dev in a Python file)."""
    places = version_locations(repo)
    release, _ = collect(repo)
    parsed = {where: parse_version(release[where], form_of(path)) for where, path, _ in places}
    if None in parsed.values() or len(set(parsed.values())) != 1:
        listing = "\n".join(
            f"  {str(release[where]):12s} {where}"
            + ("" if parsed[where] else f"  (not a version as {form_of(path)} files write it)")
            for where, path, _ in places)
        raise VersionError(f"release versions differ (or were not found):\n{listing}")
    return next(iter(parsed.values()))


def release_version(form: str = "text") -> str:
    """The version of every component as `form` spells it (see Version.spell); VersionError if
    they don't agree."""
    return the_version().spell(form)


def main() -> int:
    _, fmt = collect()
    spec = spec_version()
    ok = True
    try:
        version = the_version()
    except VersionError as e:
        ok = False
        print(e, file=sys.stderr)
    bad_fmt = {k: v for k, v in fmt.items() if v != spec}
    if bad_fmt:
        ok = False
        print(f"format versions differ from the spec ({spec}):", file=sys.stderr)
        for k, v in bad_fmt.items():
            print(f"  {str(v):10s} {k}", file=sys.stderr)
    if not ok:
        return 1
    print(version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
