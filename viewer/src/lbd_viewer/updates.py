"""LBD's versions: is there a newer release (plan 16.25), and an older viewer after a newer one.

Versions are written X.Y.Z, or X.Y.Z-dev while X.Y.Z is in development (scripts/check_versions.py);
1.3.0-dev comes after 1.2.0 and before 1.3.0. The installers compare versions the same way
(packaging/windows/LBDViewer.iss, packaging/linux/install.sh).

The check for a new version:
- asks GitHub for the latest published release (`LATEST_URL`), with a 5 s time limit. It sends
  only a plain request with the program's name and version (`User-Agent: LBD-Viewer/<version>`);
  nothing about the computer, the user or their files. LBD never downloads or installs anything:
  Settings → About shows the release page and the install command.
- runs by itself only at the viewer's real start, in the background, at most once a day (not
  with --dev, nor for a viewer left open overnight). Without internet it is quiet; a check by
  hand says it failed and why.
- what it found and the reminder's choice are kept in the settings (config.py, "updates").
- the reminder window: when a newer version is known, the first page that asks after a real start
  gets it, once (`Updates.claim_reminder`). "Remind later": not again that day; "Never remind":
  not for this version (a newer one reminds again).
"""

from __future__ import annotations

import json
import logging
import re
import sys
import threading
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any, Callable, Dict, Optional, Tuple

from . import VERSION

RELEASES_URL = "https://github.com/patrick-csliu/lbd/releases"
LATEST_URL = "https://api.github.com/repos/patrick-csliu/lbd/releases/latest"
TIMEOUT = 5.0
# The one-line install commands (plan 16.27; README and Install show the same).
_SCRIPTS = "https://github.com/patrick-csliu/lbd/releases/latest/download"
INSTALL_COMMANDS = {
    "win32": f"irm {_SCRIPTS}/install.ps1 | iex",
    "linux": f"curl -fsSL {_SCRIPTS}/install.sh | sh",
    "darwin": f"curl -fsSL {_SCRIPTS}/install-macos.sh | sh",
}
REMIND_CHOICES = ("later", "never", "install")

log = logging.getLogger("lbd_viewer")


def version_key(text: object) -> Optional[Tuple[int, int, int, int]]:
    """(major, minor, patch, 0 for -dev else 1), to compare versions; None for anything else
    (also a leading "v", as in a release tag: `check` takes that off)."""
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


# ---- asking GitHub


class CheckError(Exception):
    """The check couldn't find out; the message says why, for the user."""


def ask_github(timeout: float = TIMEOUT) -> Dict[str, Any]:
    """GitHub's answer about the latest published release (JSON). The system's proxy settings
    apply (urllib reads them). Raises CheckError with the reason."""
    req = urllib.request.Request(LATEST_URL, headers={"User-Agent": f"LBD-Viewer/{VERSION}",
                                                      "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(1_000_000)
    except urllib.error.HTTPError as e:
        raise CheckError(f"GitHub answered {e.code} {e.reason}") from None
    except urllib.error.URLError as e:
        raise CheckError(f"no connection to GitHub ({e.reason}); check the internet connection or proxy") from None
    except (TimeoutError, OSError) as e:
        raise CheckError(f"no answer from GitHub within {timeout:g} s ({e})") from None
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise CheckError("GitHub's answer wasn't a release (not JSON)") from None


def check(fetch: Callable[[], Dict[str, Any]] = ask_github,
          now: Callable[[], datetime] = datetime.now) -> Dict[str, Any]:
    """Ask for the latest release: {"latest": "X.Y.Z", "url": its page, "checked_at": local ISO
    time}. Raises CheckError with the reason (no internet, an unexpected answer)."""
    answer = fetch()
    tag = answer.get("tag_name") if isinstance(answer, dict) else None
    url = answer.get("html_url") if isinstance(answer, dict) else None
    latest = tag[1:] if isinstance(tag, str) and tag.startswith("v") else tag
    if version_key(latest) is None:
        raise CheckError(f"GitHub's answer names no version LBD understands (tag {tag!r})")
    if not (isinstance(url, str) and url.startswith("https://github.com/")):
        url = f"{RELEASES_URL}/tag/{tag}"
    return {"latest": latest, "url": url, "checked_at": now().isoformat(timespec="seconds")}


# ---- the check and the reminder in the viewer


class Updates:
    """The viewer's check for a new version and its reminder. `automatic` is True only for a
    real start (cli.start without --dev): then `start()` checks in the background, once a day,
    and the reminder can be handed to a page once. Tests and --dev get automatic=False."""

    def __init__(self, config, automatic: bool = False,
                 fetch: Optional[Callable[[], Dict[str, Any]]] = None,
                 now: Callable[[], datetime] = datetime.now):
        self.config, self.automatic, self.fetch, self.now = config, automatic, fetch, now
        self.checking = False
        self.reminder_claimed = False          # handed to a page since this start
        self._lock = threading.Lock()

    def _today(self) -> str:
        return self.now().date().isoformat()

    def _kept(self) -> Dict[str, Any]:
        return self.config.settings()["updates"]

    # -- checking

    def start(self) -> Optional[threading.Thread]:
        """At a real start: check in the background, unless already checked today."""
        if not self.automatic:
            return None
        last = self._kept()["last_check"] or ""
        if last[:10] == self._today():
            return None
        self.checking = True
        t = threading.Thread(target=self._check_quietly, name="lbd-update-check", daemon=True)
        t.start()
        return t

    def _check_quietly(self) -> None:
        try:
            self.check_now()
        except CheckError as e:             # no internet: quiet (a line in the log); tried again next start
            log.info("the check for a new LBD version failed: %s", e)
        except Exception:                   # noqa: BLE001 - a bug: in the log, never in the user's way
            log.exception("the check for a new LBD version failed")
        finally:
            self.checking = False

    def check_now(self) -> Dict[str, Any]:
        """Ask GitHub now and keep the answer; raises CheckError with the reason."""
        with self._lock:
            found = check(self.fetch or ask_github, self.now)      # (looked up now: tests replace it)
            self.config.set_updates({"last_check": found["checked_at"], "latest": found["latest"], "url": found["url"]})
        return self.state()

    # -- the reminder

    def remind_due(self) -> bool:
        """A newer version is known, and the reminder's choice doesn't hold it back today."""
        kept = self._kept()
        if not is_newer(kept["latest"], VERSION):
            return False
        remind = kept["remind"] or {}
        if remind.get("never") == kept["latest"]:
            return False
        return remind.get("later", "") < self._today()

    def claim_reminder(self) -> bool:
        """True for the first page that asks after a real start, when the reminder is due; it
        then counts as "later" until the user chooses, so it isn't shown again today."""
        with self._lock:
            if not self.automatic or self.reminder_claimed or self.checking or not self.remind_due():
                return False
            self.reminder_claimed = True
            self.config.set_updates({"remind": {"later": self._today()}})
            return True

    def remind(self, choice: str) -> Dict[str, Any]:
        """The reminder window's answer: "later" (not again today), "install" (Settings → About;
        the same as later) or "never" (not for this version)."""
        if choice not in REMIND_CHOICES:
            raise ValueError(f"choice must be one of {', '.join(REMIND_CHOICES)}, not {choice!r}")
        latest = self._kept()["latest"]
        value = {"never": latest} if choice == "never" and latest else {"later": self._today()}
        self.config.set_updates({"remind": value})
        return self.state()

    def state(self) -> Dict[str, Any]:
        kept = self._kept()
        return {"current": VERSION, "latest": kept["latest"], "url": kept["url"] or RELEASES_URL,
                "checked_at": kept["last_check"], "newer": is_newer(kept["latest"], VERSION),
                "never_for": (kept["remind"] or {}).get("never"), "checking": self.checking,
                "automatic": self.automatic, "install_command": INSTALL_COMMANDS.get(sys.platform)}
