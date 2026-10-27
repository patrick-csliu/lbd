"""HTTP API of the viewer, plus the static web UI.

Security model: the server binds to 127.0.0.1 only, every /api request must carry the
per-session token (X-LBD-Token), and the Host header must be the local address (blocks DNS
rebinding). Files are only served from configured root folders or from files the user
explicitly opened (double-click / command line). The documentation under /docs/ holds no user
data, so it needs no token.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import math
import os
import secrets
import subprocess
import sys
import threading
import time
import warnings
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

import matplotlib

matplotlib.use("Agg")  # a server: never open windows

import numpy as np  # noqa: E402
from fastapi import Body, FastAPI, HTTPException, Query, Request  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from starlette.concurrency import run_in_threadpool  # noqa: E402
from pydantic import BaseModel, ConfigDict  # noqa: E402

import lbd  # noqa: E402
from lbd.plot import render as rnd  # noqa: E402
from lbd.plot.style import STYLE_SUFFIX, read_style_file  # noqa: E402
from lbd.plot.units import prefix_scale  # noqa: E402

from . import VERSION  # noqa: E402
from . import files, images, scan, sdk  # noqa: E402
from .pages import PageError, Pages, UnknownPage  # noqa: E402
from .config import Config, ConfigError, Style, StyleError, from_dict  # noqa: E402

CREATOR = f"LBD viewer {VERSION} (matplotlib {matplotlib.__version__})"

STATIC_DIR = Path(__file__).resolve().parent / "static"
META_ARRAY_PREVIEW = 50


NO_DOCS_HTML = (
    "<!doctype html><meta charset='utf-8'><title>LBD documentation</title>"
    "<body style='font-family:sans-serif;max-width:40em;margin:3em auto'>"
    "<h1>Documentation not built</h1>"
    "<p>This copy of LBD Viewer runs from source and the documentation site hasn't been built. "
    "In the repository, run:</p>"
    "<pre>uv sync --all-packages --group docs\nuv run mkdocs build</pre>"
    "<p>then reload this page. The installed app always includes the documentation.</p>"
)


def docs_dir() -> Optional[Path]:
    """The built documentation site: $LBD_DOCS_DIR, the installed app's docs (sdk.app_folders),
    the docs inside the release wheel (scripts/build_wheels.py), or <repo>/site."""
    candidates = []
    env = os.environ.get("LBD_DOCS_DIR")
    if env:
        candidates.append(Path(env))
    candidates += sdk.app_folders("docs")
    candidates.append(sdk.PACKAGE_DIR / "docs")
    candidates.append(sdk.REPO_ROOT / "site")
    for c in candidates:
        if (c / "index.html").is_file():
            return c
    return None


class _DocsApp:
    """Serves docs_dir() as static files, looked up per request (docs built later still show)."""

    def __init__(self):
        self._dir: Optional[Path] = None
        self._static: Optional[StaticFiles] = None

    async def __call__(self, scope, receive, send):
        d = docs_dir()
        if d is None:
            await HTMLResponse(NO_DOCS_HTML, status_code=404)(scope, receive, send)
            return
        if d != self._dir:
            self._dir, self._static = d, StaticFiles(directory=d, html=True)
        await self._static(scope, receive, send)


class AppState:
    def __init__(self, config: Config, token: Optional[str] = None, port: int = 0,
                 check_host: bool = True, pages: Optional[Pages] = None):
        self.config = config
        self.pages = pages or Pages()       # the browser tabs showing the viewer (pages.py)
        self.token = token or secrets.token_urlsafe(24)
        self.port = port
        self.check_host = check_host
        self.opened: Set[str] = set()
        self.started = time.monotonic()
        self.last_heartbeat: Optional[float] = None

    def open_file(self, path: str) -> str:
        p = Path(path).expanduser().resolve()
        if not p.is_file():
            raise FileNotFoundError(path)
        self.opened.add(_key(p))
        return str(p)

    def check_allowed(self, path: str) -> Path:
        """Resolve `path` and make sure it is inside a root folder or was opened explicitly."""
        if not path:
            raise HTTPException(400, "missing path")
        p = Path(path).expanduser().resolve()
        if _key(p) in self.opened:
            return p
        for root in self.config.settings()["roots"]:
            r = Path(root).resolve()
            if p == r or _is_relative_to(p, r):
                return p
        raise HTTPException(403, "this path is not inside one of your folders")


def _key(p: Path) -> str:
    return os.path.normcase(str(p))


def _is_relative_to(p: Path, root: Path) -> bool:
    try:
        p.relative_to(root)
        return True
    except ValueError:
        return False


# ---- warnings ------------------------------------------------------------------------

_WARN_LOCK = threading.RLock()


@contextlib.contextmanager
def collect_warnings() -> Iterator[List[str]]:
    """Collect LBD warnings raised inside the block into a list (filled when the block ends).

    The viewer shows them as notices instead of letting them vanish in the server log.
    """
    found: List[str] = []
    with _WARN_LOCK, warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", lbd.LBDWarning)
        yield found
    for w in caught:
        if issubclass(w.category, lbd.LBDWarning):
            text = str(w.message)
            if text not in found:
                found.append(text)


# ---- request bodies ---------------------------------------------------------------


class _Body(BaseModel):
    # An unknown field is a client bug (e.g. a typo); reject it instead of ignoring it.
    model_config = ConfigDict(extra="forbid")


class PathBody(_Body):
    path: str


class RenameBody(_Body):
    path: str
    name: str


class RenderBody(_Body):
    path: str
    spec: Optional[Dict[str, Any]] = None
    preset: Optional[str] = None
    style: Optional[Dict[str, Any]] = None   # unsaved UI tweaks
    style_file: Optional[str] = None         # a .lbd.json file to use instead of a preset (preview)
    format: str = "svg"                      # export only; /api/render always returns SVG


class PresetBody(_Body):
    preset: Dict[str, Any]


class ImportBody(_Body):
    name: str
    content: Any                             # the style file's JSON (object) or its text
    overwrite: bool = False


class SettingsBody(_Body):
    default_style: Optional[str] = None
    open_files_in: Optional[str] = None   # "viewer" or "browser-tab" (config.OPEN_FILES_IN)
    theme: Optional[str] = None           # "system", "light" or "dark" (config.THEMES)


class FilePlotBody(_Body):
    path: str
    spec: Optional[Dict[str, Any]] = None
    style: Optional[Dict[str, Any]] = None
    style_name: Optional[str] = None
    if_version: Optional[str] = None      # the file's `version` when the page loaded it


class PagePathBody(_Body):
    path: str


class TransferBody(_Body):
    page: str
    paths: List[str]
    states: Dict[str, Any] = {}           # unsaved tab settings that travel with the files
    to: Optional[str] = None              # a page id, or None for a new browser tab


class PageBody(_Body):
    page: str


class CancelBody(_Body):
    reason: str = "the move was cancelled"   # shown to the user: "The move was cancelled (<reason>)"


class DeliverBody(_Body):
    files: List[str] = []
    dirs: List[str] = []


class ChangesBody(_Body):
    files: List[str] = []                 # the files a page shows
    dirs: List[str] = []                  # the folders it lists


def canonical(path: str) -> str:
    """One spelling per file, so the page rules never see one file as two."""
    return str(Path(path).expanduser().resolve())


def file_version(path: Path) -> str:
    """Changes when the file is written: modification time and size."""
    st = path.stat()
    return f"{st.st_mtime_ns}-{st.st_size}"


# ---- JSON helpers -------------------------------------------------------------------


def jsonable(x: Any) -> Any:
    """Meta values -> JSON. Large arrays are summarized, complex numbers become strings."""
    if isinstance(x, dict):
        return {str(k): jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [jsonable(v) for v in x]
    if isinstance(x, np.ndarray):
        if x.size > META_ARRAY_PREVIEW:
            return {"array": True, "shape": list(x.shape), "dtype": str(x.dtype),
                    "preview": jsonable(x.ravel()[:10].tolist())}
        return jsonable(x.tolist())
    if isinstance(x, np.generic):
        return jsonable(x.item())
    if isinstance(x, complex):
        return f"{x.real:g}{x.imag:+g}j"
    if isinstance(x, float) and not math.isfinite(x):
        return None
    return x


def file_summary(d: "lbd.Dataset") -> Dict[str, Any]:
    # HDF5 lists group members alphabetically; show axes in the order the values use them.
    order: List[str] = []
    for v in d.values.values():
        order += [a for a in v.axes if a not in order]
    order += [a for a in d.axes if a not in order]
    axes = []
    for a in (d.axes[n] for n in order):
        data = np.asarray(a.data)
        finite = data[np.isfinite(data)] if data.dtype.kind == "f" else data
        axes.append({
            "name": a.name, "unit": a.unit, "label": a.label, "length": int(data.size), "dtype": str(data.dtype),
            "min": jsonable(finite.min()) if finite.size else None,
            "max": jsonable(finite.max()) if finite.size else None,
        })
    values = [{"name": v.name, "unit": v.unit, "label": v.label, "axes": v.axes, "shape": list(v.shape),
               "dtype": v.dtype, "complex": v.dtype.startswith("complex")} for v in d.values.values()]
    numbers = _single_numbers(d)
    for v in values:
        if v["name"] in numbers:
            v["text"] = numbers[v["name"]]             # e.g. "21 µs": shown in the values list
    stat = d.path.stat() if d.path else None
    return {
        "path": str(d.path), "name": d.path.name if d.path else "",
        "title": d.title, "description": d.description, "created": d.created, "writer": d.writer,
        "lbd_version": d.lbd_version, "size": stat.st_size if stat else None,
        "axes": axes, "values": values, "meta": jsonable(d.meta),
        "plot": d.plot, "style": d.style, "style_name": d.style_name, "matplotlib": d.matplotlib,
        "version": file_version(d.path) if d.path else None,
    }


def _single_numbers(d: "lbd.Dataset") -> Dict[str, str]:
    """The single-number (0-D) values as text with a unit prefix, as a plot shows them: "21 µs".
    `d` may be header-only (lbd.info); then these small values are read from its file."""
    names = [n for n, v in d.values.items() if len(v.shape) == 0]
    if not names:
        return {}
    full = lbd.load(d.path, values=names) if d.path and any(d.values[n].data is None for n in names) else d
    out = {}
    for n in names:
        v = full.values[n]
        x = np.asarray(v.data)
        if np.iscomplexobj(x):
            out[n] = f"{complex(x):.6g} {v.unit}".strip()
            continue
        factor, unit = prefix_scale(x, v.unit, "auto", warn=False)
        out[n] = f"{float(x) * factor:.6g} {unit}".strip()
    return out


_DIALOG_LOCK = threading.Lock()
_DIALOG_BUSY = "a file dialog of LBD Viewer is already open; finish or cancel it first"


def _dialog_backend() -> str:
    """"osascript" on macOS, "tk" elsewhere.

    macOS only allows windows on a program's main thread, and a server request runs on a worker
    thread, so there AppleScript shows the dialog in its own process instead of tkinter.
    """
    return "osascript" if sys.platform == "darwin" else "tk"


def _applescript_string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _mac_dialog(script: str, what: str, fallback: str) -> Optional[str]:
    """Run an AppleScript `choose …` dialog and return the chosen POSIX path, or None if cancelled.

    Raises HTTP 501 if it can't be shown (the UI then uses `fallback`), 409 if one is already open.
    """
    if not _DIALOG_LOCK.acquire(blocking=False):
        raise HTTPException(409, _DIALOG_BUSY)
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    except FileNotFoundError:
        raise HTTPException(501, f"no {what} dialog on this system (osascript is missing); {fallback}")
    finally:
        _DIALOG_LOCK.release()
    if r.returncode == 0:
        path = r.stdout.strip()
        return path[:-1] if len(path) > 1 and path.endswith("/") else path   # folders end in "/"
    if "-128" in r.stderr:  # AppleScript's "User canceled."
        return None
    raise HTTPException(501, f"no {what} dialog available ({r.stderr.strip()}); {fallback}")


def _tk_dialog(ask, what: str, fallback: str) -> Optional[str]:
    """Run one tkinter file dialog, on top of other windows. `ask(filedialog, root)` shows it.

    Raises HTTP 501 where tkinter or a display is unavailable (the UI then uses `fallback`),
    409 if another dialog is already open. Returns None if the user cancels.
    """
    try:
        import tkinter
        from tkinter import filedialog
    except ImportError:
        raise HTTPException(501, f"no {what} dialog on this system; {fallback}")
    if not _DIALOG_LOCK.acquire(blocking=False):
        raise HTTPException(409, _DIALOG_BUSY)
    try:
        root = tkinter.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = ask(filedialog, root)
        root.destroy()
        return path or None
    except tkinter.TclError as e:
        raise HTTPException(501, f"no {what} dialog available ({e}); {fallback}")
    finally:
        _DIALOG_LOCK.release()


def native_folder_dialog() -> Optional[str]:
    """Native "choose folder" dialog. Returns None if cancelled."""
    fallback = "type or paste the folder path"
    if _dialog_backend() == "osascript":
        return _mac_dialog('POSIX path of (choose folder with prompt "Add folder to LBD Viewer")',
                           "folder", fallback)
    return _tk_dialog(
        lambda fd, root: fd.askdirectory(parent=root, title="Add folder to LBD Viewer", mustexist=True),
        "folder", fallback)


def native_save_dialog(folder: Path, name: str, fmt: str) -> Optional[str]:
    """Native "Save as" dialog in `folder` with `name` filled in. Returns None if cancelled.

    The system dialog asks before replacing an existing file.
    """
    fallback = "the figure is saved to your browser's download folder instead"
    if _dialog_backend() == "osascript":
        return _mac_dialog(
            f'POSIX path of (choose file name with prompt "Export figure" '
            f'default name {_applescript_string(name)} '
            f'default location (POSIX file {_applescript_string(str(folder))}))',
            "save", fallback)
    ext = f".{fmt}"
    return _tk_dialog(
        lambda fd, root: fd.asksaveasfilename(
            parent=root, title="Export figure", initialdir=str(folder), initialfile=name,
            defaultextension=ext, filetypes=[(f"{fmt.upper()} file", f"*{ext}")], confirmoverwrite=True),
        "save", fallback)


def deliver_files(state: AppState, files: List[str], dirs: List[str]) -> Dict[str, Any]:
    """Hand double-clicked files and folders to the open viewer pages (lbd-view, the macOS app).

    Folders join the folder panel. Files go to the open pages (Pages.offer): a file already open
    is shown where it is, the others go to the most recently used page, which must take them
    within a few seconds. Returns {"delivered", "shown", "busy", "unplaced"}: files in
    "unplaced" need a new browser tab (no page took them); "busy" files are being moved between
    pages right now. FileNotFoundError for a missing file, ConfigError for a bad folder.
    """
    opened = [state.open_file(f) for f in files]
    for d in dirs:
        state.config.add_root(d)
    if dirs:
        state.pages.broadcast("roots_changed")
    offer = state.pages.offer(opened)
    unplaced = list(offer.unplaced)
    if offer.delivery is not None and not state.pages.wait_for_ack(offer.delivery):
        unplaced += [p for p in offer.delivery.current.values() if p is not None]
    if not opened:                                  # only folders: bring a page forward
        page = state.pages.attention()
        return {"delivered": page is not None, "shown": [], "busy": [], "unplaced": []}
    return {"delivered": not unplaced, "shown": offer.shown, "busy": offer.busy, "unplaced": unplaced}


# ---- app ---------------------------------------------------------------------------------


def create_app(state: AppState) -> FastAPI:
    app = FastAPI(title="LBD viewer", version=VERSION, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.lbd = state
    cfg = state.config

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if state.check_host:
            host = (request.headers.get("host") or "").split(":")[0]
            if host not in ("127.0.0.1", "localhost"):
                return JSONResponse({"detail": "bad host"}, status_code=403)
        if request.url.path.startswith("/api/"):
            if not secrets.compare_digest(request.headers.get("x-lbd-token", ""), state.token):
                return JSONResponse({"detail": "missing or wrong session token; reopen the viewer"}, status_code=403)
        return await call_next(request)

    @app.exception_handler(lbd.LBDError)
    async def _lbd_error(request: Request, exc: lbd.LBDError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(rnd.RenderError)
    async def _render_error(request: Request, exc: rnd.RenderError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(ConfigError)
    async def _config_error(request: Request, exc: ConfigError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(StyleError)
    async def _style_error(request: Request, exc: StyleError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(images.ImageError)
    async def _image_error(request: Request, exc: images.ImageError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(FileNotFoundError)
    async def _not_found(request: Request, exc: FileNotFoundError):
        return JSONResponse({"detail": f"not found: {exc}"}, status_code=404)

    @app.exception_handler(OSError)
    async def _os_error(request: Request, exc: OSError):
        return JSONResponse({"detail": f"can't read: {exc}"}, status_code=400)

    # -- app state

    @app.get("/api/ping")
    def ping():
        return {"app": "lbd-viewer", "version": VERSION, "pid": os.getpid()}

    @app.post("/api/heartbeat")
    def heartbeat():
        state.last_heartbeat = time.monotonic()
        return {"ok": True}

    @app.get("/api/state")
    def get_state():
        with collect_warnings() as warns:
            s = cfg.settings()
            names = cfg.style_names()
            problems = cfg.problems()
        return {
            "version": VERSION, "lbd_version": lbd.FORMAT_VERSION,
            "roots": s["roots"], "default_style": s["default_style"], "styles": names,
            "open_files_in": s["open_files_in"], "theme": s["theme"],
            "platform": sys.platform, "config_dir": str(cfg.dir), "warnings": problems + warns,
        }

    @app.post("/api/open")
    def open_file(body: PathBody):
        return {"path": state.open_file(body.path)}

    # -- folders

    @app.post("/api/roots")
    def add_root(body: PathBody):
        roots = cfg.add_root(body.path)
        state.pages.broadcast("roots_changed")
        return {"roots": roots}

    @app.post("/api/pick-folder")
    def pick_folder():
        """Show the native folder dialog on this computer. Returns {"path": null} if cancelled."""
        return {"path": native_folder_dialog()}

    @app.delete("/api/roots")
    def remove_root(path: str = Query(...)):
        try:
            roots = cfg.remove_root(path)
        except KeyError:
            raise HTTPException(404, f"{path} is not one of your folders")
        state.pages.broadcast("roots_changed")
        return {"roots": roots}

    @app.get("/api/list")
    def list_dir(path: str = Query(...)):
        p = state.check_allowed(path)
        if not p.is_dir():
            raise HTTPException(404, f"not a folder: {path}")
        return scan.list_dir(p)

    @app.post("/api/changes")
    def changes(body: ChangesBody):
        """What changed on disk, for pages that show files and folders (watch.ts): each file's
        version and each folder's listing signature, None when it is gone. Only sizes and times
        are read; no file is opened, so a program writing it is never in the way. A path that
        isn't allowed is listed under "errors" with the reason."""
        out: Dict[str, Any] = {"files": {}, "dirs": {}, "errors": {}}
        for kind, paths in (("files", body.files), ("dirs", body.dirs)):
            for path in paths:
                try:
                    p = state.check_allowed(path)
                    if kind == "files":
                        out[kind][path] = file_version(p) if p.is_file() else None
                    else:
                        out[kind][path] = scan.list_dir(p)["signature"] if p.is_dir() else None
                except HTTPException as e:
                    out["errors"][path] = e.detail
                except FileNotFoundError:          # removed between the check and the read
                    out[kind][path] = None
                except OSError as e:
                    out["errors"][path] = e.strerror or str(e)
        return out

    @app.get("/api/search")
    def search(root: str = Query(...), q: str = Query("")):
        p = state.check_allowed(root)
        if not p.is_dir():
            raise HTTPException(404, f"not a folder: {root}")
        return scan.search(p, q)

    # -- files

    @app.get("/api/file")
    def get_file(path: str = Query(...)):
        p = state.check_allowed(path)
        if not p.is_file():
            raise HTTPException(404, f"not a file: {path}")
        with collect_warnings() as warns:
            summary = file_summary(lbd.info(p))
        return {**summary, "warnings": warns}

    @app.get("/api/axis")
    def get_axis(path: str = Query(...), name: str = Query(...)):
        """An axis' values, e.g. to jump to the point nearest a typed value."""
        p = state.check_allowed(path)
        if not p.is_file():
            raise HTTPException(404, f"not a file: {path}")
        d = lbd.info(p)
        if name not in d.axes:
            raise HTTPException(404, f"{p.name} has no axis {name!r}; its axes: {list(d.axes)}")
        a = d.axes[name]
        data = np.asarray(a.data)
        if data.dtype.kind not in "biuf":
            raise HTTPException(400, f"axis {name!r} holds {data.dtype} values, not numbers")
        # every point, in full (JSON has no NaN: a missing point is null)
        values = [float(v) if np.isfinite(v) else None for v in data.astype(float).ravel()]
        return {"name": a.name, "label": a.label, "unit": a.unit, "values": values}

    @app.put("/api/file/plot")
    def put_file_plot(body: FilePlotBody):
        p = state.check_allowed(body.path)
        changes = {k: getattr(body, k) for k in ("spec", "style", "style_name") if k in body.model_fields_set}
        if not changes:
            raise HTTPException(400, "nothing to change: send spec, style and/or style_name")
        try:
            state.pages.check_unlocked(str(p))
        except PageError as e:
            raise HTTPException(409, str(e))
        if body.if_version is not None and p.is_file() and file_version(p) != body.if_version:
            raise HTTPException(409, f"{p.name} was changed since you opened it (in another page or "
                                     "program); reload it, or save again to overwrite")
        with collect_warnings() as warns:
            lbd.set_plot(p, **changes)
            summary = file_summary(lbd.info(p))
        return {**summary, "warnings": warns}

    def _style_for(body: RenderBody, p: Path, notes: List[str]) -> Tuple[Style, str]:
        header = lbd.info(p)
        if body.style_file:
            # Preview a style file from a folder: it replaces the preset.
            sf = state.check_allowed(body.style_file)
            base = from_dict(read_style_file(sf), unknown="warn", where=sf.name)
            merged = from_dict(header.style, base=base.model_dump(), unknown="warn", where="the file's own style")
            return from_dict(body.style, base=merged.model_dump()), sf.name
        preset = cfg.preset_for(body.preset, header.style_name, notes)
        return cfg.resolve(preset=preset, file_style=header.style, ui_override=body.style), preset

    @app.post("/api/render")
    def render_view(body: RenderBody):
        p = state.check_allowed(body.path)
        if body.format.lower() != "svg":
            raise HTTPException(400, "/api/render always returns SVG; use /api/export for other formats")
        notes: List[str] = []
        with collect_warnings() as warns:
            style, preset = _style_for(body, p, notes)
            # The UI only shows the controls that apply, so settings left over from another plot
            # type are expected here and not reported.
            svg, spec = rnd.render_file(str(p), body.spec, style, fmt="svg", display=True, creator=CREATOR,
                                        warn_unused=False)
        return {"svg": svg.decode("utf-8"), "spec": spec, "preset": preset,
                "size_mm": [style.figure.width_mm, style.figure.height_mm], "warnings": notes + warns}

    def _export(body: RenderBody) -> Tuple[Path, str, bytes, str, List[str]]:
        """Render a figure for export: (data file, format, bytes, default file name, warnings)."""
        p = state.check_allowed(body.path)
        fmt = rnd.check_format(body.format)
        notes: List[str] = []
        with collect_warnings() as warns:
            style, _ = _style_for(body, p, notes)
            data, spec = rnd.render_file(str(p), body.spec, style, fmt=fmt, display=False, creator=CREATOR,
                                         warn_unused=False)
        name = rnd.safe_filename(f"{p.stem}_{'_'.join(spec['values'])}") + f".{fmt}"
        return p, fmt, data, name, notes + warns

    @app.post("/api/export")
    def export(body: RenderBody):
        """The figure as a download (used where there is no save dialog)."""
        _, fmt, data, name, warns = _export(body)
        headers = {"Content-Disposition": f'attachment; filename="{name}"'}
        if warns:
            headers["X-LBD-Warnings"] = json.dumps(warns, ensure_ascii=True)
        return Response(data, media_type=rnd.FORMATS[fmt], headers=headers)

    @app.post("/api/export/save")
    def export_save(body: RenderBody):
        """Render, then ask where to save with the system's "Save as" dialog, starting in the data
        file's folder with the default name filled in. {"path": null} if cancelled."""
        p, fmt, data, name, warns = _export(body)  # errors show before the dialog, not after it
        chosen = native_save_dialog(p.parent, name, fmt)
        if chosen is None:
            return {"path": None, "warnings": warns}
        target = Path(chosen)
        if not target.suffix:  # macOS's dialog doesn't add the extension itself
            target = target.with_name(f"{target.name}.{fmt}")
        suffix = target.suffix.lower().lstrip(".")
        if {"jpeg": "jpg", "tif": "tiff"}.get(suffix, suffix) != fmt:
            raise HTTPException(400, f"{target.name}: this is a {fmt.upper()} figure, so the name must end in .{fmt}; nothing was saved")
        try:
            target.write_bytes(data)
        except OSError as e:
            raise HTTPException(400, f"couldn't save {target}: {e.strerror or e}")
        return {"path": str(target), "warnings": warns}

    # -- styles

    @app.get("/api/styles")
    def list_styles():
        default = cfg.settings()["default_style"]
        return [{"name": n, "builtin": cfg.is_builtin(n), "customized": cfg.is_customized(n),
                 "default": n == default} for n in cfg.style_names()]

    @app.get("/api/fonts")
    def fonts():
        """Font families installed on this computer (what a style's font may be), plus generic ones."""
        from matplotlib import font_manager

        installed = sorted({f.name for f in font_manager.fontManager.ttflist}, key=str.lower)
        return {"installed": installed, "generic": ["sans-serif", "serif", "monospace"]}

    @app.get("/api/style-defaults")
    def style_defaults():
        return {"defaults": Style().model_dump(), "schema": Style.model_json_schema()}

    @app.get("/api/styles/{name}")
    def get_style(name: str):
        with collect_warnings() as warns:
            try:
                preset = cfg.preset(name)
            except KeyError:
                raise HTTPException(404, f"no style named {name!r}")
            resolved = cfg.resolve(preset=name).model_dump()
        return {"name": name, "preset": preset, "resolved": resolved,
                "builtin": cfg.is_builtin(name), "customized": cfg.is_customized(name), "warnings": warns}

    @app.put("/api/styles/{name}")
    def put_style(name: str, body: PresetBody):
        cfg.save_preset(name, body.preset)
        state.pages.broadcast("styles_changed")
        return get_style(name)

    @app.get("/api/styles/{name}/export")
    def export_style(name: str, format: str = Query("lbd")):
        """The complete style as a .lbd.json file, or matplotlib's .mplstyle."""
        if name not in cfg.style_names():
            raise HTTPException(404, f"no style named {name!r}")
        s = cfg.resolve(preset=name)
        s.name = name
        fname = rnd.safe_filename(name)
        if format == "mpl":
            return Response(s.to_mplstyle(), media_type="text/plain; charset=utf-8",
                            headers={"Content-Disposition": f'attachment; filename="{fname}.mplstyle"'})
        if format != "lbd":
            raise HTTPException(400, "format must be 'lbd' or 'mpl'")
        return Response(json.dumps(s.model_dump(), indent=2, ensure_ascii=False),
                        media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{fname}{STYLE_SUFFIX}"'})

    @app.post("/api/styles/import")
    def import_style(body: ImportBody):
        content = body.content
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except json.JSONDecodeError as e:
                raise HTTPException(400, f"not a valid style file (JSON): {e}")
        if not isinstance(content, dict):
            raise HTTPException(400, "a style file must contain a JSON object")
        if body.overwrite:
            cfg.save_preset(body.name, content)
        else:
            cfg.import_preset(body.name, content)
        state.pages.broadcast("styles_changed")
        return get_style(body.name)

    @app.get("/api/stylefile")
    def get_style_file(path: str = Query(...)):
        """A .lbd.json style file from one of the folders, fully resolved (for previewing it)."""
        p = state.check_allowed(path)
        with collect_warnings() as warns:
            s = from_dict(read_style_file(p), unknown="warn", where=p.name)
        stem = p.name[: -len(STYLE_SUFFIX)] if p.name.endswith(STYLE_SUFFIX) else p.stem
        return {"path": str(p), "name": s.name or stem, "description": s.description,
                "resolved": s.model_dump(), "size": p.stat().st_size, "warnings": warns}

    # -- images (view only)

    @app.get("/api/image/info")
    def image_info(path: str = Query(...)):
        p = state.check_allowed(path)
        return images.info(p)

    @app.get("/api/image")
    def image_data(path: str = Query(...)):
        p = state.check_allowed(path)
        data, media = images.browser_bytes(p)
        headers = {"Cache-Control": "no-store"}
        if media == "image/svg+xml":
            headers["Content-Security-Policy"] = "script-src 'none'"  # an SVG may contain scripts
        return Response(data, media_type=media, headers=headers)

    @app.delete("/api/styles/{name}")
    def delete_style(name: str):
        try:
            cfg.delete_preset(name)
        except KeyError:
            raise HTTPException(404, f"no style named {name!r}")
        state.pages.broadcast("styles_changed")
        return list_styles()

    @app.put("/api/settings")
    def put_settings(body: SettingsBody):
        if body.default_style is None and body.open_files_in is None and body.theme is None:
            raise HTTPException(400, "nothing to change: send default_style, open_files_in and/or theme")
        if body.default_style is not None:
            cfg.set_default_style(body.default_style)
            state.pages.broadcast("styles_changed")
        if body.open_files_in is not None:
            cfg.set_open_files_in(body.open_files_in)
        if body.theme is not None:
            cfg.set_theme(body.theme)
        if body.open_files_in is not None or body.theme is not None:
            state.pages.broadcast("settings_changed")      # every page shows the new setting
        return get_state()

    # -- SDK page

    @app.get("/api/sdk")
    def get_sdk():
        return sdk.sdk_info()

    @app.post("/api/sdk/reveal")
    def reveal_sdk(lang: str = Query(...)):
        try:
            return {"folder": sdk.reveal(lang)}
        except KeyError:
            raise HTTPException(404, f"unknown language {lang!r}")

    @app.post("/api/reveal")
    def reveal_file(body: PathBody = Body(...)):
        files.show_in_file_manager(state.check_allowed(body.path))
        return {"ok": True}

    # -- file actions of the folder panel (data, style and image files only)

    @app.post("/api/file/rename")
    def rename_file(body: RenameBody):
        p = state.check_allowed(body.path)
        try:
            state.pages.check_unlocked(str(p))
        except PageError as e:
            raise HTTPException(409, str(e))
        try:
            new = files.rename(p, body.name)
        except files.NameTakenError as e:
            raise HTTPException(409, str(e))
        except files.FileActionError as e:
            raise HTTPException(400, str(e))
        except FileNotFoundError as e:
            raise HTTPException(404, str(e))
        if _key(p) in state.opened:  # a file opened by double-click stays readable
            state.opened.add(_key(new))
        state.pages.broadcast("renamed", old=str(p), new=str(new))
        return {"path": str(new)}

    @app.post("/api/file/trash")
    def trash_file(body: PathBody):
        p = state.check_allowed(body.path)
        try:
            state.pages.check_unlocked(str(p))
        except PageError as e:
            raise HTTPException(409, str(e))
        try:
            files.trash(p)
        except files.FileActionError as e:
            raise HTTPException(400, str(e))
        except FileNotFoundError as e:
            raise HTTPException(404, str(e))
        except OSError as e:
            raise HTTPException(500, str(e))
        state.pages.broadcast("trashed", path=str(p))
        return {"ok": True}

    # -- pages: the browser tabs showing the viewer (the rules are in pages.py)

    def page_call(action, *args):
        """Run a page rule; its refusals become HTTP errors carrying the rule's message."""
        try:
            return action(*args)
        except UnknownPage as e:
            raise HTTPException(404, str(e))
        except PageError as e:
            raise HTTPException(409, str(e))

    @app.post("/api/pages")
    def register_page():
        page = state.pages.register()
        return {"page": page.id, "number": page.number}

    @app.get("/api/pages")
    def list_pages():
        """The open pages and their files, for "Move to ▸ Page N"."""
        return {"pages": state.pages.page_list()}

    @app.post("/api/pages/{page_id}/focus")
    def page_focus(page_id: str):
        page_call(state.pages.focus, page_id)
        return {"ok": True}

    @app.post("/api/pages/{page_id}/bye")
    def page_bye(page_id: str):
        state.pages.bye(page_id)
        return {"ok": True}

    @app.get("/api/pages/{page_id}/next")
    async def page_next(request: Request, page_id: str, wait: float = Query(25.0, ge=0, le=30),
                        after: int = Query(0, ge=0)):
        """The long poll: the page's first unconfirmed command, or {} after `wait` seconds.
        `after`: the id of the last command the page handled (confirms it and those before).

        While it waits, the connection is watched: if it drops (the tab was closed or crashed,
        even without saying goodbye), the page is gone unless it polls again soon (pages.py)."""
        poll = await run_in_threadpool(page_call, state.pages.start_poll, page_id, after)
        waiting = asyncio.ensure_future(run_in_threadpool(page_call, state.pages.wait_for_command, page_id, poll, wait))
        while not waiting.done():
            await asyncio.wait({waiting}, timeout=0.5)
            if not waiting.done() and await request.is_disconnected():
                state.pages.connection_lost(page_id, poll)     # ends the wait at once
        command = await waiting
        if command is None:
            return {}
        return {"id": command.id, "kind": command.kind, "data": command.data}

    @app.post("/api/pages/{page_id}/ack/{command_id}")
    def page_ack(page_id: str, command_id: int):
        return page_call(state.pages.ack, page_id, command_id)

    @app.post("/api/pages/{page_id}/acquire")
    def page_acquire(page_id: str, body: PagePathBody):
        """The page opens a file: {"path"} (its canonical spelling), plus {"owner": n} if Page n
        has it open already (then this page doesn't open it)."""
        path = str(state.check_allowed(body.path))
        other = page_call(state.pages.acquire, page_id, path)
        return {"path": path} if other is None else {"path": path, "owner": other.number}

    @app.post("/api/pages/{page_id}/release")
    def page_release(page_id: str, body: PagePathBody):
        page_call(state.pages.release, page_id, canonical(body.path))
        return {"ok": True}

    @app.post("/api/pages/show")
    def page_show(body: PagePathBody):
        """Ask the page that has the file open to show it (switch to it, come forward)."""
        owner = state.pages.show(canonical(body.path))
        if owner is None:
            raise HTTPException(404, "no page has this file open")
        return {"page": owner.number}

    @app.post("/api/transfers")
    def start_transfer(body: TransferBody):
        transfer = page_call(state.pages.start_transfer, body.page, [canonical(p) for p in body.paths],
                             {canonical(k): v for k, v in body.states.items()}, body.to)
        return {"id": transfer.id, "timeout": transfer.timeout}

    @app.post("/api/transfers/{transfer_id}/claim")
    def claim_transfer(transfer_id: str, body: PageBody):
        transfer = page_call(state.pages.claim, transfer_id, body.page)
        source = state.pages.pages.get(transfer.source)
        return {"paths": transfer.paths, "states": transfer.states, "from": source.number if source else None}

    @app.post("/api/transfers/{transfer_id}/complete")
    def complete_transfer(transfer_id: str, body: PageBody):
        return {"paths": page_call(state.pages.complete, transfer_id, body.page)}

    @app.post("/api/transfers/{transfer_id}/cancel")
    def cancel_transfer(transfer_id: str, body: Optional[CancelBody] = None):
        reason = body.reason if body else CancelBody().reason
        page_call(state.pages.cancel_transfer, transfer_id, reason)
        return {"ok": True}

    @app.post("/api/deliver")
    def deliver(body: DeliverBody):
        """lbd-view hands over double-clicked files and folders (see deliver_files)."""
        try:
            return deliver_files(state, body.files, body.dirs)
        except FileNotFoundError as e:
            raise HTTPException(404, f"not found: {e}")
        except PageError as e:
            raise HTTPException(409, str(e))

    # -- documentation (Help)

    @app.get("/docs", include_in_schema=False)
    def docs_root():
        return RedirectResponse("/docs/")

    app.mount("/docs", _DocsApp(), name="docs")

    # -- web UI

    if (STATIC_DIR / "index.html").is_file():
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    else:
        @app.get("/", response_class=HTMLResponse)
        def no_ui():
            return ("<h1>LBD viewer</h1><p>The web UI is not built. Run <code>npm run build</code> "
                    "in <code>viewer/web/</code>, or use the Vite dev server.</p>")

    return app
