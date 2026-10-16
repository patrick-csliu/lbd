"""Viewer settings (folders, default preset) and access to the shared style presets.

Storage (platformdirs user config dir, override with LBD_CONFIG_DIR):
    settings.json              folder list, default preset name
    styles/<name>.lbd.json     style presets, shared with Python (lbd.plot)
Styles themselves (schema, presets, resolution) live in lbd.plot.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from lbd.plot.presets import BUILTIN_PRESETS, PresetStore, config_dir
from lbd.plot.style import QuantityStyle, Style, StyleError, deep_merge, from_dict, validate

__all__ = ["Config", "ConfigError", "Style", "QuantityStyle", "StyleError", "deep_merge", "BUILTIN_PRESETS",
           "from_dict", "validate", "config_dir"]


class ConfigError(ValueError):
    """The viewer's settings are invalid (e.g. a broken settings.json, an unknown style)."""


class Config:
    """Viewer settings and style presets on disk. Thread-safe for the viewer's use."""

    def __init__(self, directory: Optional[Path] = None):
        self.dir = Path(directory) if directory else config_dir()
        self.styles_dir = self.dir / "styles"
        self.store = PresetStore(self.styles_dir)
        self._lock = threading.RLock()
        self.styles_dir.mkdir(parents=True, exist_ok=True)

    # settings

    @property
    def settings_path(self) -> Path:
        return self.dir / "settings.json"

    def _stored(self) -> Dict[str, Any]:
        """settings.json as stored, checked: {"roots": [...], "default_style": str or None}."""
        with self._lock:
            data = _read_json(self.settings_path)
        if data is None:
            return {"roots": [], "default_style": None}
        if not isinstance(data, dict):
            raise ConfigError(f"{self.settings_path} must contain a JSON object; fix or delete the file")
        roots = data.get("roots", [])
        if not isinstance(roots, list) or not all(isinstance(r, str) for r in roots):
            raise ConfigError(f"{self.settings_path}: 'roots' must be a list of folder paths; fix or delete the file")
        default = data.get("default_style")
        if default is not None and not isinstance(default, str):
            raise ConfigError(f"{self.settings_path}: 'default_style' must be text; fix or delete the file")
        return {"roots": list(roots), "default_style": default or None}

    def settings(self) -> Dict[str, Any]:
        """{"roots": [...], "default_style": name}; a default style that no longer exists is 'default'."""
        stored = self._stored()
        default = stored["default_style"] or "default"
        if default not in self.style_names():
            default = "default"
        return {"roots": stored["roots"], "default_style": default}

    def problems(self) -> List[str]:
        """Things the user should know about the settings (shown as warnings in the viewer)."""
        out = []
        stored = self._stored()
        if stored["default_style"] and stored["default_style"] not in self.style_names():
            out.append(f"The default style {stored['default_style']!r} no longer exists; 'default' is used.")
        for r in stored["roots"]:
            if not Path(r).is_dir():
                out.append(f"The folder {r} no longer exists (or isn't reachable); remove it from the list "
                           "or reconnect the drive.")
        return out

    def _save_settings(self, settings: Dict[str, Any]) -> None:
        _write_json(self.settings_path, settings)

    def add_root(self, path: str) -> List[str]:
        p = Path(path).expanduser()
        if not p.is_dir():
            raise ConfigError(f"not a folder: {path}")
        resolved = str(p.resolve())
        with self._lock:
            s = self.settings()
            if not any(_same_path(resolved, r) for r in s["roots"]):
                s["roots"].append(resolved)
                self._save_settings(s)
            return s["roots"]

    def remove_root(self, path: str) -> List[str]:
        """Remove a folder from the list (no files are touched). KeyError if it isn't listed."""
        with self._lock:
            s = self.settings()
            kept = [r for r in s["roots"] if not _same_path(r, path)]
            if len(kept) == len(s["roots"]):
                raise KeyError(f"{path} is not one of your folders")
            s["roots"] = kept
            self._save_settings(s)
            return s["roots"]

    def set_default_style(self, name: str) -> None:
        if name not in self.style_names():
            raise ConfigError(f"no style named {name!r}")
        with self._lock:
            s = self.settings()
            s["default_style"] = name
            self._save_settings(s)

    # style presets (delegated to the shared store)

    def style_names(self) -> List[str]:
        return self.store.names()

    def is_builtin(self, name: str) -> bool:
        return self.store.is_builtin(name)

    def is_customized(self, name: str) -> bool:
        return self.store.is_customized(name)

    def preset(self, name: str) -> Dict[str, Any]:
        """The preset's own (partial) settings. Raises KeyError if it doesn't exist."""
        return self.store.preset(name)

    def save_preset(self, name: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return self.store.save(name, data)

    def import_preset(self, name: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return self.store.import_file(name, data)

    def delete_preset(self, name: str) -> None:
        """Delete a user preset, or reset a customized built-in one."""
        self.store.delete(name)
        with self._lock:
            stored = self._stored()
            if stored["default_style"] and stored["default_style"] not in self.style_names():
                self._save_settings({"roots": stored["roots"], "default_style": "default"})

    # resolution

    def resolve(
        self,
        preset: Optional[str] = None,
        file_style_name: Optional[str] = None,
        file_style: Optional[Dict[str, Any]] = None,
        ui_override: Optional[Dict[str, Any]] = None,
    ) -> Style:
        """Built-in defaults <- one preset <- file's style override <- UI override."""
        return self.store.resolve(self.preset_for(preset, file_style_name), file_style, ui_override)

    def preset_for(self, preset: Optional[str], file_style_name: Optional[str],
                   warnings: Optional[List[str]] = None) -> str:
        """Which preset applies: the one picked in the UI, else the file's, else the app default.

        An unknown preset picked in the UI is an error. A file may name a preset that only
        exists on another computer; then the default is used and a message is added to
        `warnings`.
        """
        names = self.style_names()
        if preset:
            if preset not in names:
                raise ConfigError(f"no style named {preset!r}; available: {', '.join(names)}")
            return preset
        default = self.settings()["default_style"]
        if file_style_name:
            if file_style_name in names:
                return file_style_name
            if warnings is not None:
                warnings.append(f"This file asks for the style {file_style_name!r}, which doesn't exist here; "
                                f"{default!r} is used.")
        return default


def _same_path(a: str, b: str) -> bool:
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ConfigError(f"{path} is not valid JSON ({e}); fix or delete the file") from e


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
