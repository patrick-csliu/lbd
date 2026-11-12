"""LBD's versions compared: an older viewer started after a newer one.

Versions are written X.Y.Z, or X.Y.Z-dev while X.Y.Z is in development (scripts/check_versions.py);
1.3.0-dev comes after 1.2.0 and before 1.3.0. The installers compare versions the same way
(packaging/windows/LBDViewer.iss, packaging/linux/install.sh).
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

from . import VERSION

RELEASES_URL = "https://github.com/patrick-csliu/lbd/releases"


def version_key(text: object) -> Optional[Tuple[int, int, int, int]]:
    """(major, minor, patch, 0 for -dev else 1), to compare versions; None for anything else
    (also a leading "v", as in a release tag: `release_version` takes that off)."""
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(-dev)?", text) if isinstance(text, str) else None
    if not m:
        return None
    return int(m[1]), int(m[2]), int(m[3]), 0 if m[4] else 1


def is_newer(a: object, b: object) -> bool:
    """True if version `a` is newer than version `b`; False when either isn't a version."""
    ka, kb = version_key(a), version_key(b)
    return ka is not None and kb is not None and ka > kb


def older_than_before(before: Optional[str], now: str = VERSION) -> Optional[str]:
    """The message for a viewer older than the one used before on this computer, else None.
    (The macOS app shows it at its first start: a disk image can't refuse an older version.)"""
    if not is_newer(before, now):
        return None
    return (f"This LBD Viewer ({now}) is older than the one used before on this computer ({before}). "
            f"It reads your settings and Library as far as it can; settings that only {before} knows are "
            f"kept for it. To use {before} again, install it from {RELEASES_URL}.")
