"""Print one version's section of CHANGELOG.md: the text of its GitHub release.

    uv run python scripts/release_notes.py 0.2.0 > notes.md

Used by .github/workflows/release.yml. The section must be dated by scripts/bump_version.py
("## 0.2.0 (2026-11-03)"); a missing, empty or still "in development" section is an error, so a
release never goes out without notes.
"""

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


class NotesError(Exception):
    """No usable CHANGELOG section for the version; the message says what to do."""


def section(changelog: str, version: str, allow_unreleased: bool = False) -> str:
    """The text under "## <version> (<date>)", without the heading.

    allow_unreleased: also accept "## <version> (in development)" (trial runs of the release
    workflow, which build the version still in development).
    """
    m = re.search(rf"^## {re.escape(version)} \(([^)]*)\)[ \t]*\r?$", changelog, re.MULTILINE)
    if not m:
        raise NotesError(f'CHANGELOG.md has no "## {version} (<date>)" section; '
                         f"run scripts/bump_version.py {version}")
    if m.group(1) == "in development" and not allow_unreleased:
        raise NotesError(f"CHANGELOG.md: {version} is still in development; "
                         f"run scripts/bump_version.py {version} to date it")
    following = re.search(r"^## ", changelog[m.end():], re.MULTILINE)
    body = changelog[m.end():m.end() + following.start()] if following else changelog[m.end():]
    if not body.strip():
        raise NotesError(f"CHANGELOG.md: the {version} section is empty")
    return body.strip() + "\n"


def main(argv=None, repo: Path = REPO) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("version", help="X.Y.Z, or X.Y.Z-dev (its section is still in development)")
    ap.add_argument("--allow-unreleased", action="store_true",
                    help='accept a section still "in development" (trial runs only)')
    args = ap.parse_args(argv)
    try:
        version = args.version
        if version.endswith("-dev"):
            if not args.allow_unreleased:
                raise NotesError(f"{version} is a development version; it can't be released. "
                                 f"Run scripts/bump_version.py {version[:-4]} first")
            version = version[:-4]       # its section is "## X.Y.Z (in development)"
        notes = section((repo / "CHANGELOG.md").read_text(encoding="utf-8"), version,
                        args.allow_unreleased)
    except NotesError as e:
        print(f"release_notes: {e}", file=sys.stderr)
        return 1
    sys.stdout.buffer.write(notes.encode("utf-8"))   # UTF-8 whatever the console's encoding
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
