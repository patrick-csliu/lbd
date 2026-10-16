"""Named style presets, shared by LBD Viewer and Python scripts.

Presets live in the LBD settings folder (LBD_CONFIG_DIR overrides it):
    Windows  %APPDATA%\\lbd\\styles\\<name>.lbd.json
    Linux    ~/.config/lbd/styles/<name>.lbd.json
A preset file stores only the settings that differ from the built-in defaults.
"""

from __future__ import annotations

import copy
import json
import os
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Union

from lbd.io import _warn

from .style import STYLE_SUFFIX, STYLE_VERSION, Style, StyleError, StyleWarning, from_dict

BUILTIN_PRESETS: Dict[str, Dict[str, Any]] = {
    "default": {
        "description": "Journal figure for APS and AIP (Physical Review, Applied Physics Letters, …): one "
                       "column 85 × 64 mm, Arial 10 pt for all text, 600 dpi, every line ≥ 0.5 pt, colours that "
                       "stay apart in greyscale. For a two-column figure set the width to 170 mm.",
    },
}

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}$")
# File names Windows reserves (also with an extension), so no preset may be called that.
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def config_dir() -> Path:
    """The LBD settings folder: `$LBD_CONFIG_DIR`, else `%APPDATA%\\lbd` / `~/.config/lbd`.

    Presets are in its `styles` subfolder; LBD Viewer keeps `settings.json` there.
    """
    env = os.environ.get("LBD_CONFIG_DIR")
    if env:
        return Path(env)
    try:
        import platformdirs
    except ImportError:  # pragma: no cover - depends on the environment
        raise ImportError('lbd.plot needs platformdirs. Install it with:  pip install "lbd[plot]"') from None
    return Path(platformdirs.user_config_dir("lbd", appauthor=False, roaming=True))


def check_name(name: Any) -> str:
    """Raise StyleError unless `name` can be a preset name (and a file name on every system)."""
    if not isinstance(name, str):
        raise StyleError(f"a style name must be text, not {type(name).__name__}")
    if not _NAME_RE.match(name) or name.endswith((".", " ")):
        raise StyleError(f"invalid style name {name!r}: use letters, digits, space, '_', '.', '-' "
                         "(at most 64; starting with a letter or digit, not ending with '.' or space)")
    if name.split(".")[0].strip().lower() in _RESERVED:
        raise StyleError(f"{name!r} can't be a style name (it is a reserved file name on Windows)")
    return name


class PresetStore:
    """The style presets on this computer: the same list LBD Viewer's Styles page shows.

    A **preset** is a named style, e.g. `thesis`. Presets are stored as `<name>.lbd.json` in
    `<settings folder>/styles`, holding only the settings that differ from the built-in
    defaults. The built-in preset is `default` (the journal style for APS and AIP); you can
    change it too (and reset it by deleting).

    **When do you need this class?** For everyday plotting, no: pass a preset name to
    `lp.use("thesis")`, `lp.plot(..., style="thesis")` or `lp.load_style("thesis")`. Use a
    `PresetStore` to *manage* presets from code: create or update one (`save`), list them
    (`names`), remove one (`delete`), add a style file as a preset (`import_file`), or compute the
    exact style the viewer uses for a file (`resolve`).

    How a figure's style is put together (each layer overrides the one before):

    ```
    built-in defaults  <-  preset  <-  the file's own style  <-  unsaved changes
    ```

    Parameters
    ----------
    directory : path, optional
        The styles folder. Default: the LBD settings folder (`%APPDATA%\\lbd\\styles` on
        Windows, `~/.config/lbd/styles` on Linux, or `$LBD_CONFIG_DIR/styles`). Pass a folder
        to keep presets elsewhere, e.g. in a test.

    Examples
    --------
    >>> store = lp.PresetStore()
    >>> store.save("paper", {"figure": {"width_mm": 90, "font": {"size_pt": 9}}})
    >>> lp.load_style("paper").figure.width_mm
    90.0
    """

    def __init__(self, directory: Union[str, Path, None] = None):
        if directory is not None and not isinstance(directory, (str, os.PathLike)):
            raise TypeError(f"directory must be a path, not {type(directory).__name__}")
        if directory is not None and str(directory) == "":
            raise ValueError("directory must not be empty; pass None for the LBD settings folder")
        self.dir = Path(directory) if directory is not None else config_dir() / "styles"
        self._lock = threading.RLock()

    # -- files

    def _path(self, name: str) -> Path:
        return self.dir / f"{name}{STYLE_SUFFIX}"

    def _existing(self, name: str) -> Optional[Path]:
        p = self._path(name)
        return p if p.is_file() else None

    def _canonical(self, name: str) -> Optional[str]:
        """The stored spelling of a name that matches `name` ignoring case, if any."""
        for n in self.names():
            if n.lower() == name.lower():
                return n
        return None

    # -- queries

    def names(self) -> List[str]:
        """Names of all presets: `default` first, then the others alphabetically.

        Use it to show the choices, e.g. in an error message or a notebook widget.
        `lp.list_styles()` is the same list.

        Returns
        -------
        list of str

        Warns
        -----
        StyleWarning
            The styles folder has `.json` files that aren't presets (not `<name>.lbd.json`, or
            a name that can't be a preset name); they are not listed.
        """
        names = set(BUILTIN_PRESETS)
        skipped = []
        if self.dir.is_dir():
            for p in self.dir.glob("*.json"):
                if not p.is_file():
                    continue
                if not p.name.endswith(STYLE_SUFFIX):
                    skipped.append(p.name)
                    continue
                try:
                    names.add(check_name(p.name[: -len(STYLE_SUFFIX)]))
                except StyleError:
                    skipped.append(p.name)
        if skipped:
            _warn(f"{self.dir}: these files are not listed as presets (a preset file is <name>{STYLE_SUFFIX} "
                  f"with a valid name): {', '.join(sorted(skipped))}", StyleWarning)
        return sorted(names, key=lambda n: (n != "default", n.lower()))

    def is_builtin(self, name: str) -> bool:
        """Whether `name` is a built-in preset (only `default`)."""
        return check_name(name) in BUILTIN_PRESETS

    def is_customized(self, name: str) -> bool:
        """Whether a preset file exists for `name`: a user preset, or a built-in one that was changed.

        `delete` on a customized built-in preset resets it; on an unchanged built-in it fails.
        """
        return self._existing(check_name(name)) is not None

    def preset(self, name: str) -> Dict[str, Any]:
        """The preset's own settings, as stored: only what differs from the defaults.

        Use it to see or copy what a preset changes. For the complete style use
        [`style`][lbd.plot.PresetStore.style] or `lp.load_style(name)`.

        Returns
        -------
        dict
            Partial settings, e.g. `{"figure": {"width_mm": 90}}`.

        Raises
        ------
        KeyError
            No preset with that name.
        StyleError
            Invalid name, or the preset file can't be read or isn't a JSON object.
        """
        check_name(name)
        path = self._existing(name)
        if path:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                raise StyleError(f"preset file {path} is not valid JSON: {e}") from None
            except OSError as e:
                raise StyleError(f"can't read the preset file {path}: {e.strerror or e}") from None
            if not isinstance(data, dict):
                raise StyleError(f"preset file {path} must contain a JSON object, not {type(data).__name__}")
            data.pop("name", None)
            return data
        if name in BUILTIN_PRESETS:
            return {"lbd_style": STYLE_VERSION, **copy.deepcopy(BUILTIN_PRESETS[name])}
        raise KeyError(f"no style preset named {name!r}; available: {', '.join(self.names())}")

    def style(self, name: str) -> Style:
        """The complete `Style` of a preset (defaults with the preset's settings merged in).

        The same as `lp.load_style(name)` for a preset name.

        Raises
        ------
        KeyError
            No preset with that name.
        StyleError
            Invalid name or unreadable preset.

        Warns
        -----
        StyleWarning
            The preset file has settings this version doesn't know; they are ignored.
        """
        path = self._existing(check_name(name))
        s = from_dict(self.preset(name), unknown="warn", where=path.name if path else name)
        s.name = name
        return s

    # -- changes

    def save(self, name: str, data: Mapping[str, Any]) -> Dict[str, Any]:
        """Create or update a preset, as the viewer's Styles page does.

        The preset is available at once in the viewer (after a refresh) and in every Python
        session. Saving under a built-in name changes that built-in preset.

        Parameters
        ----------
        name : str
            Letters, digits, space, `_`, `.`, `-` (at most 64). Names are not case-sensitive:
            saving `Paper` when `paper` exists is refused.
        data : dict
            Settings, partial is fine. Only the differences
            from the defaults are written.

        Returns
        -------
        dict
            What was stored: `{"lbd_style": 2, "name": ..., <changed settings>}`.

        Raises
        ------
        StyleError
            Invalid name, a name that differs from an existing one only in case, an unknown
            setting, or an invalid value (the message names it).

        Examples
        --------
        >>> lp.PresetStore().save("paper", {"figure": {"width_mm": 90}})
        """
        check_name(name)
        if not isinstance(data, Mapping):
            raise StyleError(f"a style must be a dict (JSON object), not {type(data).__name__}")
        existing = self._canonical(name)
        if existing is not None and existing != name:
            raise StyleError(f"a style named {existing!r} already exists; names are not case-sensitive")
        partial = {k: v for k, v in data.items() if k != "name"}
        full = from_dict(partial)   # raises on unknown keys and bad values
        stored = {"lbd_style": STYLE_VERSION, "name": name, **full.diff()}
        with self._lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = self._path(name).with_name(f"{name}{STYLE_SUFFIX}.tmp-{os.getpid()}")
            tmp.write_text(json.dumps(stored, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self._path(name))
        return stored

    def delete(self, name: str) -> None:
        """Delete a user preset, or reset a changed built-in preset to its original settings.

        Raises
        ------
        StyleError
            Invalid name, or an unchanged built-in preset (nothing to delete).
        KeyError
            No preset with that name.
        """
        check_name(name)
        path = self._existing(name)
        if path is None:
            if name in BUILTIN_PRESETS:
                raise StyleError(f"'{name}' is built in and unchanged; there is nothing to delete")
            raise KeyError(f"no style preset named {name!r}")
        with self._lock:
            path.unlink()

    def import_file(self, name: str, data: Mapping[str, Any], overwrite: bool = False) -> Dict[str, Any]:
        """Add a style (e.g. the content of a `.lbd.json` file) as a preset.

        Like [`save`][lbd.plot.PresetStore.save], but refuses to replace an existing preset
        unless `overwrite=True`. This is the viewer's *Import…* button.

        Raises
        ------
        StyleError
            A preset with that name exists (ignoring case) and `overwrite` is false, or the
            settings are invalid.

        Examples
        --------
        >>> import json
        >>> lp.PresetStore().import_file("paper2", json.load(open("figs/thesis.lbd.json")))
        """
        check_name(name)
        if not isinstance(overwrite, bool):
            raise TypeError("overwrite must be True or False")
        existing = self._canonical(name)
        if existing is not None and not overwrite:
            raise StyleError(f"a style named {existing!r} already exists")
        return self.save(existing or name, data)

    # -- resolution

    def resolve(self, name: str, file_style: Optional[Mapping[str, Any]] = None,
                override: Optional[Mapping[str, Any]] = None) -> Style:
        """The complete style for one figure, put together exactly as LBD Viewer does.

        A figure's look comes from up to four layers; each overrides the one before:

        ```
        built-in defaults  <-  preset `name`  <-  file_style  <-  override
        ```

        **When to use it:** to reproduce in Python the exact style the viewer uses for a
        file, e.g. to make a matching figure of your own. For a plain preset use
        `lp.load_style(name)`; for plotting a file `lp.plot(path)` already does this for you.

        Parameters
        ----------
        name : str
            The preset to start from (the file's `style_name`, or the default preset).
        file_style : dict, optional
            Style changes saved in an `.lbd` file (`d.style`). Settings this version doesn't
            know are ignored with a warning, because the file may come from a newer LBD.
        override : dict, optional
            Further changes on top (in the viewer: unsaved edits). Unknown settings are errors.

        Returns
        -------
        Style
            The complete style; its `name` is `name`.

        Raises
        ------
        StyleError
            Unknown or invalid preset name, unknown settings in `override`, or invalid values.

        Warns
        -----
        StyleWarning
            Unknown settings in `file_style` (ignored).

        Examples
        --------
        >>> d = lbd.load("sweep.lbd")
        >>> store = lp.PresetStore()
        >>> s = store.resolve(d.style_name or "default", file_style=d.style)
        >>> with lp.use(s):                      # your own figure, exactly the file's look
        ...     fig, ax = plt.subplots()
        """
        try:
            preset = self.preset(name)
        except KeyError:
            raise StyleError(f"no style preset named {name!r}; available: {', '.join(self.names())}") from None
        base = from_dict(preset, unknown="warn", where=f"preset {name!r}").model_dump()
        if file_style is not None:
            base = from_dict(file_style, base=base, unknown="warn", where="the file's own style").model_dump()
        s = from_dict(override, base=base)
        s.name = name
        return s


def default_preset_name(config: Optional[Path] = None) -> str:
    """The default preset chosen on the viewer's Styles page (`"default"` if none was chosen).

    Warns (StyleWarning) when the settings file is broken or names a preset that no longer
    exists; `"default"` is used then.
    """
    folder = config or config_dir()
    path = folder / "settings.json"
    if not path.is_file():
        return "default"
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        _warn(f"can't read {path} ({e}); using the 'default' style", StyleWarning)
        return "default"
    if not isinstance(settings, dict):
        _warn(f"{path} is not a JSON object; using the 'default' style", StyleWarning)
        return "default"
    name = settings.get("default_style") or "default"
    if not isinstance(name, str):
        _warn(f"{path}: default_style must be text; using the 'default' style", StyleWarning)
        return "default"
    store = PresetStore(folder / "styles")
    if name not in store.names():
        _warn(f"the default style {name!r} (chosen on the Styles page) no longer exists; using 'default'",
              StyleWarning)
        return "default"
    return name

