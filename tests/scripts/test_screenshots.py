"""The documentation's screenshots (scripts/make_screenshots.py) and the pages that show them.

The images are made by hand (they need Chromium and look the same only on one system), so these
checks catch the mistakes that don't need them: a shot the docs don't use, an image the docs
use that doesn't exist, a leftover image nobody makes any more.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "make_screenshots.py"
FOLDERS = {"VIEWER_IMG": REPO / "docs" / "viewer" / "img", "QUICKSTART_IMG": REPO / "docs" / "getting-started" / "img"}


def shots():
    """The images the script makes: their paths."""
    found = re.findall(r'save\(page, (VIEWER_IMG|QUICKSTART_IMG) / "([^"]+)"', SCRIPT.read_text(encoding="utf-8"))
    return {FOLDERS[folder] / name for folder, name in found}


def used_images():
    """Image paths referenced by the docs (Markdown ![...](...)), resolved from each page."""
    used = {}
    for page in (REPO / "docs").rglob("*.md"):
        for ref in re.findall(r"!\[[^\]]*\]\(([^)\s]+)", page.read_text(encoding="utf-8")):
            if not ref.startswith(("http:", "https:")):
                used[(page.parent / ref).resolve()] = page
    return used


def test_every_shot_is_used_in_the_docs():
    used = used_images()
    unused = sorted(str(p.relative_to(REPO)) for p in shots() if p.resolve() not in used)
    assert len(shots()) >= 10 and not unused, f"shots not shown on any page: {unused}"


def test_every_image_the_docs_use_exists():
    missing = sorted(f"{page.relative_to(REPO)} -> {img}" for img, page in used_images().items() if not img.is_file())
    assert not missing, f"missing images (run scripts/make_screenshots.py?): {missing}"


def test_no_leftover_screenshots():
    made = {p.resolve() for p in shots()}
    leftovers = sorted(str(p.relative_to(REPO)) for folder in FOLDERS.values() for p in folder.glob("*.png")
                       if p.resolve() not in made)
    assert not leftovers, f"images no shot makes any more (delete them): {leftovers}"
