"""Install instructions for the language modules, shown on the viewer's Language modules page.

The languages and their instructions come from each language's `language.toml`:
  - installed app:   <install dir>/sdk/<id>/language.toml   (staged by packaging/stage_sdk.py)
  - source checkout: languages/<id>/language.toml
The manifest format is described in languages/README.md.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import lbd

from . import __version__

REPO_ROOT = Path(__file__).resolve().parents[3]  # viewer/src/lbd_viewer -> repo
_PLACEHOLDER_RE = re.compile(r"\{(path|match|version)\}")


PACKAGE_DIR = Path(__file__).resolve().parent


def app_folders(name: str) -> List[Path]:
    """Where an installed app keeps a folder such as `sdk` or `docs`: next to the program, and in
    a macOS app bundle in Contents/Resources (the program is in Contents/MacOS)."""
    if not getattr(sys, "frozen", False):
        return []
    exe_dir = Path(sys.executable).resolve().parent
    return [exe_dir / name, exe_dir.parent / "Resources" / name]


def sdk_dir() -> Optional[Path]:
    """The bundled SDK folder of an installed app or wheel, or None when running from source."""
    candidates = []
    env = os.environ.get("LBD_SDK_DIR")
    if env:
        candidates.append(Path(env))
    candidates += app_folders("sdk")
    candidates.append(PACKAGE_DIR / "sdk")   # the release wheel (scripts/build_wheels.py)
    for c in candidates:
        if c.is_dir():
            return c
    return None


def languages_dir() -> Tuple[Path, str]:
    """(folder containing one subfolder per language, 'sdk' or 'source')."""
    base = sdk_dir()
    return (base, "sdk") if base else (REPO_ROOT / "languages", "source")


def _q(path: Path) -> str:
    """A path for use inside double quotes in a shell, Julia or MATLAB string."""
    return path.as_posix() if os.name == "nt" else str(path)


def _fill(text: str, values: Dict[str, str]) -> str:
    # Only {path}, {match} and {version} are placeholders; other braces (e.g. MATLAB's
    # {t.Name}) are left alone.
    return _PLACEHOLDER_RE.sub(lambda m: values[m.group(1)], text)


def _pick_install(manifest: Dict[str, Any], folder: Path, where: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """First [[install]] variant that fits this context, and the file its `if_exists` matched."""
    for variant in manifest.get("install", []):
        if variant.get("where", "any") not in (where, "any"):
            continue
        pattern = variant.get("if_exists")
        if pattern:
            matches = sorted(folder.glob(pattern))
            if not matches:
                continue
            return variant, matches[-1].name
        return variant, ""
    return None, ""


def _broken(folder: Path, error: str) -> Dict[str, Any]:
    """An entry for a language whose files can't be used, so the page shows the problem."""
    return {"id": folder.name, "name": folder.name, "order": 10_000, "folder": str(folder), "available": False,
            "requirements": "", "install": [], "check": "", "upgrade": "", "uninstall": "", "example": "",
            "example_file": "", "notes": [], "error": error}


def _language_info(folder: Path, where: str) -> Optional[Dict[str, Any]]:
    toml = folder / "language.toml"
    if not toml.is_file():
        return _broken(folder, "this folder has no language.toml")
    try:
        manifest = tomllib.loads(toml.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        return _broken(folder, f"language.toml can't be read: {e}")
    try:
        order = int(manifest.get("order", 100))
    except (TypeError, ValueError):
        return _broken(folder, f"language.toml: order must be a whole number, not {manifest.get('order')!r}")
    variant, match = _pick_install(manifest, folder, where)
    values = {"path": _q(folder), "match": match, "version": lbd.__version__}
    example = ""
    error = None
    if manifest.get("example"):
        try:
            example = (folder / manifest["example"]).read_text(encoding="utf-8")
        except OSError as e:
            error = f"the example file {manifest['example']} can't be read ({e.strerror or e})"
    if variant is None:
        error = error or "no install instructions match the files in this folder"
    return {
        "id": manifest.get("id", folder.name),
        "name": manifest.get("name", folder.name),
        "order": order,
        "folder": str(folder),
        "available": variant is not None,
        "requirements": manifest.get("requirements", ""),
        "install": [{"label": s.get("label", ""), "code": _fill(s.get("code", ""), values)}
                    for s in (variant or {}).get("steps", [])],
        "check": manifest.get("check", ""),
        "upgrade": _fill((variant or {}).get("upgrade", ""), values),
        "uninstall": _fill((variant or {}).get("uninstall", ""), values),
        "example": example,
        "example_file": manifest.get("example", ""),
        "notes": list(manifest.get("notes", [])),
        "error": error,
    }


def languages() -> List[Dict[str, Any]]:
    base, where = languages_dir()
    out = []
    if base.is_dir():
        for folder in sorted(base.iterdir()):
            if folder.is_dir() and not folder.name.startswith(("_", ".")):
                info = _language_info(folder, where)
                if info:
                    out.append(info)
    return sorted(out, key=lambda l: (l["order"], l["id"]))


def sdk_info() -> Dict[str, Any]:
    base, where = languages_dir()
    return {
        "version": __version__,
        "lbd_version": lbd.FORMAT_VERSION,
        "bundled": where == "sdk",
        "sdk_dir": str(base) if where == "sdk" else None,
        "languages": languages(),
    }


def reveal(lang: str) -> str:
    """Open the folder of a language in the system file manager."""
    for info in languages():
        if info["id"] == lang:
            open_folder(info["folder"])
            return info["folder"]
    raise KeyError(lang)


def open_folder(folder: str) -> None:
    if os.name == "nt":
        os.startfile(folder)  # noqa: S606 - local folder chosen by the app, not by the request
    elif sys.platform == "darwin":
        subprocess.Popen(["open", folder])
    else:
        subprocess.Popen(["xdg-open", folder])
