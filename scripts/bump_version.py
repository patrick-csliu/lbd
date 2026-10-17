"""Set a new release version everywhere and date its CHANGELOG section.

    uv run python scripts/bump_version.py 0.2.0 [--dry-run]

1. Writes the version into every place scripts/check_versions.py reads (version_locations():
   the viewer, each language's [[version]] files, uv.lock and package-lock.json).
2. CHANGELOG.md: the top section, "## Unreleased" or "## <version> (in development)", becomes
   "## 0.2.0 (2026-11-03)". A release needs notes, so a missing or empty section is an error.
3. Checks the result with check_versions and prints the next steps (test, commit, tag, push).

Versions are X.Y.Z. The new one must not be lower than the current one; the same version is
allowed, to release the version in development (e.g. 0.1.0). Nothing is written if any check fails.
"""

import argparse
import datetime
import re
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_versions import REPO, collect, version_locations  # noqa: E402

VERSION_RE = re.compile(r"\d+\.\d+\.\d+")
# The section to release; the lookahead keeps a Windows line ending (\r) in place.
SECTION_RE = re.compile(r"^## (?:Unreleased|\S+ \(in development\))[ \t]*(?=\r?$)", re.MULTILINE)


class BumpError(Exception):
    """The version can't be set; the message says why. Nothing has been written."""


def as_tuple(version: str) -> Tuple[int, ...]:
    return tuple(int(n) for n in version.split("."))


def current_version(repo: Path) -> str:
    release, _ = collect(repo)
    versions = set(release.values())
    if None in versions or len(versions) != 1:
        raise BumpError("the files don't agree on the current version; run scripts/check_versions.py")
    return versions.pop()


def set_version(text: str, pattern: str, version: str, where: str) -> str:
    """`text` with the version that `pattern` (group 1) finds replaced; it must match exactly once."""
    matches = list(re.finditer(pattern, text, re.MULTILINE))
    if len(matches) != 1:
        raise BumpError(f"{where}: expected the version once, found it {len(matches)} times")
    m = matches[0]
    return text[:m.start(1)] + version + text[m.end(1):]


def date_changelog(text: str, version: str, today: str) -> str:
    """CHANGELOG text with the section to release headed "## <version> (<today>)"."""
    m = SECTION_RE.search(text)
    if not m:
        raise BumpError('CHANGELOG.md has no "## Unreleased" or "## <version> (in development)" '
                        "section at the top; add one with the changes of this release")
    following = re.search(r"^## ", text[m.end():], re.MULTILINE)
    body = text[m.end():m.end() + following.start()] if following else text[m.end():]
    if not body.strip():
        raise BumpError("the CHANGELOG section to release is empty; write what changed first")
    return text[:m.start()] + f"## {version} ({today})" + text[m.end():]


def read(path: Path) -> str:
    with open(path, encoding="utf-8", newline="") as f:     # newline="": keep \r\n as it is
        return f.read()


def write(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def main(argv=None, repo: Path = REPO, today: Optional[str] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("version", help="the new version, X.Y.Z (e.g. 0.2.0)")
    ap.add_argument("--dry-run", action="store_true", help="show what would change, write nothing")
    args = ap.parse_args(argv)
    new = args.version
    today = today or datetime.date.today().isoformat()
    try:
        if not VERSION_RE.fullmatch(new):
            raise BumpError(f"{new!r}: use three numbers, X.Y.Z (e.g. 0.2.0); no other forms")
        old = current_version(repo)
        if as_tuple(new) < as_tuple(old):
            raise BumpError(f"{new} is lower than the current version {old}")

        # Change everything in memory first, so a failed check writes nothing.
        texts: Dict[Path, str] = {}
        for where, path, pattern in version_locations(repo):
            texts[path] = set_version(texts.get(path) or read(path), pattern, new, where)
        changelog = repo / "CHANGELOG.md"
        texts[changelog] = date_changelog(read(changelog), new, today)
    except (BumpError, FileNotFoundError) as e:
        print(f"bump_version: {e}", file=sys.stderr)
        return 1

    rel = [p.resolve().relative_to(repo.resolve()).as_posix() for p in texts]
    if args.dry_run:
        print(f"Would set {old} -> {new} in:\n  " + "\n  ".join(rel))
        print(f'and head the CHANGELOG section "## {new} ({today})". Nothing written (--dry-run).')
        return 0
    for path, text in texts.items():
        write(path, text)
    release, _ = collect(repo)
    wrong = {k: v for k, v in release.items() if v != new}
    if wrong:
        print(f"bump_version: these still don't say {new}: {wrong}", file=sys.stderr)
        return 1
    print(f"Version {old} -> {new} in:\n  " + "\n  ".join(rel))
    print(f"""
Next:
  uv run python scripts/test_all.py
  git commit -am "Release {new}"
  git tag -a v{new} -m "LBD {new}"   # annotated: --follow-tags pushes only those
  git push --follow-tags        # GitHub builds and tests it, then makes a draft release""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
