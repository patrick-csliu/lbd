"""Explore's "Save as CSV" (plan 5): what a panel shows as a table (lbd.plot.tables, the code a
script uses too), its size before writing, and the writing itself in the background (progress,
cancel). Several panels go into one file when they share their axes, else one file each."""

from __future__ import annotations

import re
import secrets
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from lbd.plot import tables
from lbd.plot.tables import Column, Rows, Table, ValueRows

from .explore import ExploreError
from .summaries import Cancelled, Job

if TYPE_CHECKING:                                    # pragma: no cover
    from .explore import ExploreSession

WARN_BYTES = 100 * 1000 ** 2                         # a file this big: "Save anyway?"
EXCEL_ROWS, EXCEL_COLUMNS = 1_048_576, 16_384        # what Excel opens
KEEP_DONE = 120.0                                    # seconds a finished job is still reported


def _operated(s: "ExploreSession") -> bool:
    r = s.ops_result
    return r is not None and r.applied > 0 and s.ops_shown is not None


def _chosen(s: "ExploreSession") -> Optional[List[int]]:
    """The traces (series positions, a map's rows) chosen in the panel, None: all."""
    axis = s.spec.get("series") if s.base_kind == "curve" else s.spec.get("y")
    picked = (s.settings.get("select") or {}).get(axis) if axis else None
    return None if picked is None else sorted(int(i) for i in picked)


def options(s: "ExploreSession") -> Dict[str, Optional[str]]:
    """Each choice of the dialog that can't be made for this panel, with why (None: possible)."""
    stored = None
    if _operated(s) and (not s.ops_result.grid.one_to_one or s.kind != s.base_kind):
        stored = ("after these operations the points shown aren't the stored ones (e.g. an FFT or an "
                  "average); turn the operations off to save the stored numbers")
    elif _operated(s) and len(s.spec["values"]) > 1:
        stored = "with operations on several values, only the numbers as shown can be saved"
    zoomed = None
    if s.kind == "curve" and s.spec["x"] in s.data.values and not _operated(s):
        zoomed = "each trace has its own x (a value), so a range of x can't be kept: save everything"
    return {"stored": stored, "both": stored, "zoomed": zoomed}


def session_table(s: "ExploreSession", numbers: str = "shown", view: Optional[Dict[str, Any]] = None,
                  units: str = "stored") -> Table:
    """The table of what a panel shows. `view`: {"xlim", "ylim"} in plot units (the zoomed
    range), None: everything."""
    why = options(s).get(numbers) if numbers != "shown" else None
    if why:
        raise ExploreError(why)
    m = s.model
    xlim = ylim = None
    if view is not None:
        why = options(s)["zoomed"]
        if why:
            raise ExploreError(why)
        xlim = [v / m.xf for v in view["xlim"]]
        if s.kind == "heatmap":
            ylim = [v / m.yf for v in view["ylim"]]
    if not _operated(s) and s.kind == s.base_kind:
        traces = _chosen(s)
        t = tables.from_model(s.data, s.spec, m, numbers=numbers, xlim=xlim, ylim=ylim, units=units, traces=traces)
        if traces is not None:
            t.comments.append(f"chosen traces only ({len(traces)})")
    else:
        t = _operated_table(s, numbers, xlim, ylim, units)
    if s.summarised:
        t.comments.append("read from the file part by part (too big for memory)")
    return t


def _slug(text: str) -> str:
    """A column name from a label: letters, digits and _ only (what numpy's names keep)."""
    name = re.sub(r"[^0-9A-Za-z_]+", "_", text).strip("_")
    return name or "value"


def _operated_table(s: "ExploreSession", numbers: str, xlim, ylim, units: str) -> Table:
    """After operations or equations: the grid they made (operations.py, stored units)."""
    g, shown_info, m, spec = s.ops_result.grid, s.ops_shown, s.model, s.spec
    shown = units == "shown"
    fx = m.xf if shown else 1.0
    ft = m.yf if shown and g.kind == "heatmap" else 1.0
    fv = shown_info.value_factor if shown else 1.0
    x_name = _slug(g.xq.label) if shown_info.x_changed else spec["x"]
    x_col = Column(x_name, g.xq.label, tables.prefixed(g.xq.unit, fx))
    x: Any = [tables.scaled(np.asarray(a, dtype=float), fx) for a in g.x] if g.ragged \
        else tables.scaled(np.asarray(g.x, dtype=float), fx)
    value = Column(spec["values"][0] if len(spec["values"]) == 1 else _slug(g.value.label), g.value.label,
                   tables.prefixed(g.value.unit, fv))
    a = np.asarray(g.a, dtype=float)
    traces = list(range(a.shape[0]))
    if g.kind == "curve" and len(s.visible) == a.shape[0]:
        traces = [k for k, v in enumerate(s.visible) if v]
    elif g.kind == "heatmap" and s.base_kind == "heatmap" and _chosen(s) is not None:
        traces = _chosen(s)
    if g.t is None and a.shape[0] > 1 and not g.ragged:
        # several lines without a common coordinate (several values): a column each
        labels = g.labels or [f"trace {k + 1}" for k in range(a.shape[0])]
        values = [(Column(_slug(labels[k]), labels[k], value.unit), Rows(a[k], scale=fv)) for k in traces]
        out = Table(x=x, x_col=x_col, values=values, kind=g.kind)
    else:
        t, t_col = None, None
        if g.t is not None:
            t_name = _slug(g.tq.label) if shown_info.t_changed else (spec.get("series") or spec.get("y") or "trace")
            t, t_col = tables.scaled(np.asarray(g.t, dtype=float), ft), Column(t_name, g.tq.label,
                                                                           tables.prefixed(g.tq.unit, ft))
        elif a.shape[0] > 1:                                     # ragged lines: numbered
            t, t_col = np.arange(1.0, a.shape[0] + 1), Column("trace", "trace number")
        values = [(value, Rows(a, scale=fv))] if numbers != "stored" else []
        if numbers in ("stored", "both"):
            v = s.data.values[spec["values"][0]]
            cols, rows = (spec["x"], spec["y"]) if s.base_kind == "heatmap" else (spec.get("along", spec["x"]), spec.get("series"))
            values += tables.stored_columns(v.name, v, numbers == "both" and v.name == value.name,
                                            lambda part: ValueRows(v, cols, rows, spec["index"], part))
        out = Table(x=x, x_col=x_col, values=values, t=t, t_col=t_col, kind=g.kind)
        out.traces = np.asarray(traces, dtype=int) if len(traces) != a.shape[0] else None
    if xlim is not None:
        if g.ragged:
            raise ExploreError("each trace has its own x here, so a range of x can't be kept: save everything")
        out.points = tables._inside(np.asarray(g.x, dtype=float), xlim)
    if ylim is not None and out.t is not None:
        inside = tables._inside(np.asarray(g.t, dtype=float), ylim)
        out.traces = inside if out.traces is None else np.intersect1d(out.traces, inside)
    out.comments = tables._comments(s.data, spec, "shown" if numbers == "shown" else numbers, shown)
    out.comments.append("after: " + "; ".join(_ops_text(s)))
    return out


def _ops_text(s: "ExploreSession") -> List[str]:
    out = []
    for op in s.ops_list:
        if not op.get("on", True):
            continue
        extra = ", ".join(f"{k} {v}" for k, v in op.items() if k not in ("op", "on"))
        out.append(op["op"].replace("_", " ") + (f" ({extra})" if extra else ""))
    eqs = {k: v for k, v in (s.settings.get("equations") or {}).items() if v.strip()}
    out += [f"equation {k} = {v}" for k, v in eqs.items()]
    return out or ["complex corrections"]


# ---- several panels ----------------------------------------------------------------


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, (list, tuple)) or isinstance(b, (list, tuple)):
        return False
    if a is None or b is None:
        return a is None and b is None
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    return a.shape == b.shape and bool(np.array_equal(a, b, equal_nan=True))


def join(ts: Sequence[Table]) -> List[Table]:
    """Panels' tables in as few files as possible: those sharing their axes (same coordinates,
    the same points and traces kept) become one table with each panel's columns; others stay apart."""
    groups: List[List[Table]] = []
    for t in ts:
        for g in groups:
            h = g[0]
            if (_same(h.x, t.x) and _same(h.t, t.t) and _same(h.points, t.points) and _same(h.traces, t.traces)
                    and h.x_col.unit == t.x_col.unit):
                g.append(t)
                break
        else:
            groups.append([t])
    out = []
    for g in groups:
        if len(g) == 1:
            out.append(g[0])
            continue
        first, names, values, comments = g[0], set(), [], []
        for n, t in enumerate(g):
            for col, rows in t.values:
                name = col.name if col.name not in names else f"{col.name}_{n + 1}"
                names.add(name)
                values.append((Column(name, col.label, col.unit), rows))
            comments += [c for c in t.comments if c not in comments]
        out.append(Table(x=first.x, x_col=first.x_col, values=values, t=first.t, t_col=first.t_col,
                         comments=comments, kind=first.kind, points=first.points, traces=first.traces))
    return out


# ---- the file ----------------------------------------------------------------------


def suggest_path(s: "ExploreSession", extra: str = "") -> Path:
    """A new file name next to the data: <file>_<value>[_<complex mode>].csv, never an existing one."""
    v = s.spec["values"][0]
    mode = f"_{s.spec['complex']}" if np.iscomplexobj(np.empty(0, dtype=s.data.values[v].dtype)) else ""
    base = f"{s.path.stem}_{v}{mode}{extra}"
    path = s.path.with_name(base + ".csv")
    n = 2
    while path.exists():
        path = s.path.with_name(f"{base} ({n}).csv")
        n += 1
    return path


def check_target(path: Path) -> None:
    if path.suffix.lower() != ".csv":
        raise ExploreError(f"the numbers are saved as a .csv file, not '{path.name}'")
    if path.exists():
        raise ExploreError(f"'{path.name}' exists already; choose another name")
    if not path.parent.is_dir():
        raise ExploreError(f"the folder '{path.parent}' doesn't exist")


def files_for(path: Path, n: int) -> List[Path]:
    """The file names for n tables: the name chosen, then '<name> – panel k.csv'."""
    return [path if k == 0 else path.with_name(f"{path.stem} – part {k + 1}{path.suffix}") for k in range(n)]


def plan(ts: Sequence[Table], layout: str, rows_are: str) -> Dict[str, Any]:
    """Size and warnings of writing these tables (nothing read in full)."""
    if layout == "matrix":
        for t in ts:
            t.check_matrix()
    sizes = [t.estimate(layout) for t in ts]
    rows = max((e["rows"] for e in sizes), default=0)
    cols = max((e["columns"] for e in sizes), default=0)
    if layout == "matrix" and rows_are == "x":
        rows, cols = cols, rows
    total = sum(e["bytes"] for e in sizes)
    warnings = []
    if total > WARN_BYTES:
        warnings.append(f"The file will be about {_size(total)}.")
    if rows > EXCEL_ROWS:
        warnings.append(f"Excel opens only the first {EXCEL_ROWS:,} rows (this has {rows:,}).")
    if cols > EXCEL_COLUMNS:
        warnings.append(f"Excel opens only the first {EXCEL_COLUMNS:,} columns (this has {cols:,}); "
                        "turn the table the other way, or save rows.")
    return {"bytes": total, "rows": rows, "columns": cols, "files": len(ts), "warnings": warnings,
            "big": total > WARN_BYTES}


def _size(n: float) -> str:
    for unit in ("bytes", "kB", "MB", "GB", "TB"):
        if n < 1000 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "bytes" else f"{n:.3g} {unit}"
        n /= 1000
    return ""


class Exports:
    """CSV files being written in the background, one thread each: progress, cancel, and the
    outcome (kept a little while so the page can say "Saved" or what went wrong)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: Dict[str, Dict[str, Any]] = {}

    def start(self, work: List[Tuple[Table, Path]], layout: str, rows_are: str) -> str:
        job_id = secrets.token_urlsafe(6)
        job = Job(str(work[0][1]), f"saving {', '.join(p.name for _, p in work)}")
        rec = {"job": job, "paths": [str(p) for _, p in work], "state": "writing", "error": None, "ended": None}
        with self._lock:
            self._forget_old()
            self._jobs[job_id] = rec

        def run() -> None:
            try:
                for k, (t, path) in enumerate(work):
                    t.to_csv(path, layout, rows_are, progress=lambda f, k=k: job.step((k + f) / len(work)))
                rec["state"] = "done"
            except Cancelled:
                rec["state"] = "cancelled"
                for _, path in work:                   # the files already complete are removed too
                    try:
                        path.unlink()
                    except OSError:
                        pass
            except Exception as e:                     # shown to the user: nothing fails silently
                known = isinstance(e, (ValueError, OSError))      # ExploreError is a ValueError
                rec["state"], rec["error"] = "failed", str(e) if known else f"{type(e).__name__}: {e}"
            rec["ended"] = time.monotonic()

        threading.Thread(target=run, name=f"export-{job_id}", daemon=True).start()
        return job_id

    def _forget_old(self) -> None:
        now = time.monotonic()
        for k in [k for k, r in self._jobs.items() if r["ended"] is not None and now - r["ended"] > KEEP_DONE]:
            del self._jobs[k]

    def info(self) -> List[Dict[str, Any]]:
        with self._lock:
            self._forget_old()
            return [{"id": k, **r["job"].info(), "paths": r["paths"], "state": r["state"], "error": r["error"]}
                    for k, r in self._jobs.items()]

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            rec = self._jobs.get(job_id)
        if rec is None or rec["state"] != "writing":
            return False
        rec["job"].cancel()
        return True

    def wait(self, job_id: str, timeout: float = 30.0) -> Dict[str, Any]:
        """For tests: until the job has ended; its info."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            info = next(i for i in self.info() if i["id"] == job_id)
            if info["state"] != "writing":
                return info
            time.sleep(0.01)
        raise TimeoutError(job_id)
