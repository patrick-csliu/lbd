"""Set a new version everywhere and head its CHANGELOG section.

    uv run python scripts/bump_version.py 1.2.0 --dev [--dry-run]    start developing 1.2.0
    uv run python scripts/bump_version.py 1.2.0 [--dry-run]          release it

1. Writes the version into every place scripts/check_versions.py reads (version_locations():
   the viewer, each language's [[version]] files, uv.lock and package-lock.json), each in its
   own spelling (1.2.0.dev0 in Python files, 1.2.0-dev.0 in npm files, 1.2.0-dev elsewhere).
2. CHANGELOG.md:
   - --dev: a new top section "## 1.2.0 (in development)" (kept if it is already there);
   - release: the top section, "## Unreleased" or "## <version> (in development)", becomes
     "## 1.2.0 (2026-11-03)". A release needs notes, so a missing or empty section is an error.
3. Checks the result with check_versions and prints the next steps.

The new version must not be lower than the current one: 1.2.0-dev -> 1.2.0 releases it, and the
same version is allowed. Nothing is written if any check fails.
"""

import argparse
import datetime
import re
import sys
from pathlib import Path
from typing import Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_versions import (REPO, Version, VersionError, form_of, parse_version,  # noqa: E402
                            the_version, version_locations)

# The section to release; the lookahead keeps a Windows line ending (\r) in place.
SECTION_RE = re.compile(r"^## (?:Unreleased|\S+ \(in development\))[ \t]*(?=\r?$)", re.MULTILINE)


class BumpError(Exception):
    """The version can't be set; the message says why. Nothing has been written."""


def current_version(repo: Path) -> Version:
    try:
        return the_version(repo)
    except VersionError:
        raise BumpError("the files don't agree on the current version; run scripts/check_versions.py") from None


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


def start_changelog(text: str, version: str) -> str:
    """CHANGELOG text with "## <version> (in development)" as its top section: "## Unreleased"
    is renamed, a missing section is added."""
    heading = f"## {version} (in development)"
    m = SECTION_RE.search(text)
    if m and m.group(0).strip() == heading:
        return text
    if m and m.group(0).strip() == "## Unreleased":
        return text[:m.start()] + heading + text[m.end():]
    if m:
        raise BumpError(f'CHANGELOG.md already starts with "{m.group(0).strip()}"; '
                        f'rename it to "{heading}" or release it first')
    first = re.search(r"^## ", text, re.MULTILINE)
    if not first:
        raise BumpError("CHANGELOG.md has no version sections")
    nl = "\r\n" if "\r\n" in text else "\n"
    return text[:first.start()] + heading + nl + nl + text[first.start():]


def read(path: Path) -> str:
    with open(path, encoding="utf-8", newline="") as f:     # newline="": keep \r\n as it is
        return f.read()


def write(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def main(argv=None, repo: Path = REPO, today: Optional[str] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("version", help="the new version, X.Y.Z (e.g. 0.2.0)")
    ap.add_argument("--dev", action="store_true", help="start developing this version (X.Y.Z-dev)")
    ap.add_argument("--dry-run", action="store_true", help="show what would change, write nothing")
    args = ap.parse_args(argv)
    today = today or datetime.date.today().isoformat()
    try:
        number = parse_version(args.version)
        if number is None or number.dev:
            raise BumpError(f"{args.version!r}: use three numbers, X.Y.Z (e.g. 0.2.0); "
                            "for a development version add --dev")
        new = number._replace(dev=args.dev)
        old = current_version(repo)
        if new.order() < old.order():
            raise BumpError(f"{new} is lower than the current version {old}")

        # Change everything in memory first, so a failed check writes nothing.
        texts: Dict[Path, str] = {}
        for where, path, pattern in version_locations(repo):
            texts[path] = set_version(texts.get(path) or read(path), pattern, new.spell(form_of(path)), where)
        changelog = repo / "CHANGELOG.md"
        if new.dev:
            texts[changelog] = start_changelog(read(changelog), new.spell("number"))
        else:
            texts[changelog] = date_changelog(read(changelog), str(new), today)
    except (BumpError, FileNotFoundError) as e:
        print(f"bump_version: {e}", file=sys.stderr)
        return 1

    rel = [p.resolve().relative_to(repo.resolve()).as_posix() for p in texts]
    heading = f"## {new.spell('number')} (in development)" if new.dev else f"## {new} ({today})"
    if args.dry_run:
        print(f"Would set {old} -> {new} in:\n  " + "\n  ".join(rel))
        print(f'and head the CHANGELOG section "{heading}". Nothing written (--dry-run).')
        return 0
    for path, text in texts.items():
        write(path, text)
    try:
        written = the_version(repo)
    except VersionError as e:
        print(f"bump_version: the files don't all say {new} now:\n{e}", file=sys.stderr)
        return 1
    print(f"Version {old} -> {new} in:\n  " + "\n  ".join(rel))
    if written.dev:
        print(f"""
Next: write each change under "{heading}" in CHANGELOG.md.
  git commit -am "Start {new}"
A development version can't be released; run bump_version.py {new.spell('number')} for that.""")
        return 0
    print(f"""
Next:
  uv run python scripts/test_all.py
  git commit -am "Release {new}"
  git tag -a v{new} -m "LBD {new}"   # annotated: --follow-tags pushes only those
  git push --follow-tags        # GitHub builds and tests it, then makes a draft release""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
