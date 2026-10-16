"""Find and validate the language manifests in languages/<id>/language.toml.

Used by tests/crosslang/run_all.py, scripts/test_all.py, scripts/check_versions.py and
packaging/stage_sdk.py, so adding a language never requires editing those tools.
The manifest format is described in languages/README.md.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[1]
LANGUAGES_DIR = REPO / "languages"

TOP_KEYS = {"id", "name", "order", "requirements", "example", "check", "notes",
            "version", "format_version", "test", "crosslang", "sdk", "install"}
SECTION_KEYS = {
    "test": {"requires", "command"},
    "crosslang": {"requires", "write", "check"},
    "sdk": {"requires", "build", "fallback_copy", "copy"},
}
INSTALL_KEYS = {"where", "if_exists", "steps", "upgrade", "uninstall"}
PLACEHOLDERS = ("python", "repo", "lang_dir", "out", "root", "dest", "version")
_PLACEHOLDER_RE = re.compile(r"\{(" + "|".join(PLACEHOLDERS) + r")\}")


class ManifestError(Exception):
    """A language.toml is missing, invalid, or a command needs a value that wasn't given."""


@dataclass
class Language:
    dir: Path
    data: Dict[str, Any]

    @property
    def id(self) -> str:
        return self.data["id"]

    @property
    def name(self) -> str:
        return self.data["name"]

    @property
    def order(self) -> int:
        return int(self.data.get("order", 100))

    def section(self, name: str) -> Dict[str, Any]:
        return self.data.get(name) or {}

    def missing_tool(self, section: str) -> Optional[str]:
        """Name of the required executable of a section if it is not on PATH, else None."""
        req = self.section(section).get("requires")
        return req if req and shutil.which(req) is None else None

    def values(self, **extra: Any) -> Dict[str, str]:
        v = {"python": sys.executable, "repo": str(REPO), "lang_dir": str(self.dir)}
        v.update({k: str(val) for k, val in extra.items() if val is not None})
        return v

    def command(self, cmd: List[str], **extra: Any) -> List[str]:
        """`cmd` with its {placeholders} filled in; ManifestError if one has no value here."""
        vals = self.values(**extra)

        def fill(m: "re.Match[str]") -> str:
            if m.group(1) not in vals:
                raise ManifestError(f"{self.id}: the command {cmd} uses {{{m.group(1)}}}, which isn't available "
                                    f"here (available: {', '.join('{' + k + '}' for k in sorted(vals))})")
            return vals[m.group(1)]

        out = [_PLACEHOLDER_RE.sub(fill, part) for part in cmd]
        exe = shutil.which(out[0])  # resolve e.g. "matlab" -> full path (and .exe/.cmd on Windows)
        if exe:
            out[0] = exe
        return out

    def env(self, **extra: Any) -> Dict[str, str]:
        env = dict(os.environ)
        for k, v in self.values(**extra).items():
            env[f"LBD_{k.upper()}"] = v
        return env

    def run(self, cmd: List[str], capture: bool = True, **extra: Any) -> subprocess.CompletedProcess:
        """Run a manifest command in the language folder, with placeholders and LBD_* env set."""
        return subprocess.run(
            self.command(cmd, **extra), cwd=self.dir, env=self.env(**extra),
            capture_output=capture, text=True, encoding="utf-8", errors="replace",
        )


def load(lang_dir: Path) -> Language:
    path = lang_dir / "language.toml"
    where = path.relative_to(REPO) if path.is_relative_to(REPO) else path
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ManifestError(f"{where}: missing (every folder in languages/ needs a language.toml)")
    except tomllib.TOMLDecodeError as e:
        raise ManifestError(f"{where}: invalid TOML: {e}") from None

    def fail(msg: str):
        raise ManifestError(f"{where}: {msg}")

    def text(value: Any, what: str) -> None:
        if not isinstance(value, str):
            fail(f"{what} must be text, not {type(value).__name__}")

    def strings(value: Any, what: str, nonempty: bool = False) -> None:
        if not isinstance(value, list) or not all(isinstance(c, str) for c in value) or (nonempty and not value):
            fail(f"{what} must be a {'non-empty ' if nonempty else ''}list of strings")

    def pattern_table(t: Any, what: str) -> None:
        if not isinstance(t, dict) or not {"file", "pattern"} <= set(t):
            fail(f"{what} needs 'file' and 'pattern'")
        extra = set(t) - {"file", "pattern"}
        if extra:
            fail(f"{what} has unknown keys {sorted(extra)}")
        text(t["file"], f"{what}.file")
        text(t["pattern"], f"{what}.pattern")
        try:
            if re.compile(t["pattern"], re.MULTILINE).groups < 1:
                fail(f"{what}.pattern needs a capture group (...) around the version")
        except re.error as e:
            fail(f"{what}.pattern is not a valid regular expression: {e}")

    for key in ("id", "name"):
        if not isinstance(data.get(key), str) or not data[key]:
            fail(f"'{key}' is required")
    if data["id"] != lang_dir.name:
        fail(f"id '{data['id']}' must equal the folder name '{lang_dir.name}'")
    unknown = set(data) - TOP_KEYS
    if unknown:
        fail(f"unknown keys {sorted(unknown)}")
    if "order" in data and (isinstance(data["order"], bool) or not isinstance(data["order"], int)):
        fail(f"'order' must be a whole number, not {data['order']!r}")
    for key in ("requirements", "example", "check"):
        if key in data:
            text(data[key], f"'{key}'")
    if "notes" in data:
        strings(data["notes"], "'notes'")
    for sec, keys in SECTION_KEYS.items():
        if sec not in data:
            continue
        if not isinstance(data[sec], dict):
            fail(f"[{sec}] must be a table (a [{sec}] section), not {type(data[sec]).__name__}")
        extra = set(data[sec]) - keys
        if extra:
            fail(f"[{sec}] has unknown keys {sorted(extra)}")
        if "requires" in data[sec]:
            text(data[sec]["requires"], f"[{sec}].requires")
    for sec, key in (("test", "command"), ("crosslang", "write"), ("crosslang", "check"), ("sdk", "build")):
        cmd = data.get(sec, {}).get(key)
        if cmd is not None:
            strings(cmd, f"[{sec}].{key}", nonempty=True)
    for key in ("fallback_copy", "copy"):
        if key in data.get("sdk", {}):
            strings(data["sdk"][key], f"[sdk].{key}")
    if "crosslang" in data and not {"write", "check"} <= set(data["crosslang"]):
        fail("[crosslang] needs both 'write' and 'check'")
    versions = data.get("version", [])
    if not isinstance(versions, list):
        fail("[[version]] must be an array of tables (write [[version]], not [version])")
    for i, v in enumerate(versions):
        pattern_table(v, f"[[version]] #{i + 1}")
    if "format_version" in data:
        pattern_table(data["format_version"], "[format_version]")
    installs = data.get("install", [])
    if not isinstance(installs, list):
        fail("[[install]] must be an array of tables (write [[install]], not [install])")
    for i, inst in enumerate(installs):
        what = f"[[install]] #{i + 1}"
        if not isinstance(inst, dict):
            fail(f"{what} must be a table")
        extra = set(inst) - INSTALL_KEYS
        if extra:
            fail(f"{what} has unknown keys {sorted(extra)}")
        if inst.get("where", "any") not in ("sdk", "source", "any"):
            fail(f"{what}: where must be 'sdk', 'source' or 'any'")
        for key in ("if_exists", "upgrade", "uninstall"):
            if key in inst:
                text(inst[key], f"{what}.{key}")
        steps = inst.get("steps")
        if not isinstance(steps, list) or not steps:
            fail(f"{what} needs at least one step")
        for j, step in enumerate(steps):
            if not isinstance(step, dict) or set(step) != {"label", "code"} or not all(isinstance(v, str) for v in step.values()):
                fail(f"{what} step {j + 1} must be {{ label = \"...\", code = \"...\" }}")
    if data.get("example") and not (lang_dir / data["example"]).is_file():
        fail(f"example file '{data['example']}' not found")
    return Language(lang_dir, data)


def discover(languages_dir: Path = LANGUAGES_DIR) -> List[Language]:
    """All languages, sorted by `order` then id. Folders starting with '_' or '.' are skipped."""
    langs = [load(d) for d in sorted(languages_dir.iterdir())
             if d.is_dir() and not d.name.startswith(("_", "."))]
    return sorted(langs, key=lambda l: (l.order, l.id))


def read_pattern(path: Path, pattern: str) -> Optional[str]:
    """First capture group of `pattern` (multiline) in a file, or None if the file or a match is missing.

    Callers report None (check_versions lists it as a problem).
    """
    try:
        m = re.search(pattern, path.read_text(encoding="utf-8"), re.MULTILINE)
    except FileNotFoundError:
        return None
    return m.group(1) if m else None


if __name__ == "__main__":
    for lang in discover():
        print(f"{lang.order:3d}  {lang.id:10s} {lang.name}")
