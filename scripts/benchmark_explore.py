"""How fast the Explore view draws large data, compared with earlier runs on this computer.

    uv run python scripts/benchmark_explore.py            # measure, print a table, compare
    uv run python scripts/benchmark_explore.py --accept   # a slowdown is intended: start a new baseline
    uv run python scripts/benchmark_explore.py --history  # earlier runs on this computer

Three files are made once (in the temp folder) and drawn as the Explore view draws them: 1000
traces of 10 000 points, a 4001 × 4001 map, and one curve of 1 000 000 points. For each, the times
of opening it, the full view, zooming in (drafts, as while the mouse moves), the sharp picture at
the end, panning, picking a point, and moving a cursor (on maps with the cuts beside it) (milliseconds, each the fastest of
several repeats: a busy computer only ever adds time, so the fastest is the steadiest).

Times depend on the computer, so each run is compared only with earlier runs on the same computer
(their median, kept in .benchmarks/explore.jsonl, which isn't committed). A time more than 30 %
and 10 ms slower than that, also when its file is measured once more, fails the run. A failed
run isn't used as a baseline; run it again
when the computer was busy, and use --accept when the slowdown is the price of a wanted change.

`scripts/test_all.py` runs this when the drawing code changed since the last run here (see
DRAWING_CODE), or always with --perf; never on GitHub, whose shared machines vary too much.
"""

import argparse
import json
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np

REPO = Path(__file__).resolve().parents[1]
HISTORY = REPO / ".benchmarks" / "explore.jsonl"
DATA = Path(tempfile.gettempdir()) / "lbd-benchmark" / "v1"
# A change here since the last run on this computer makes test_all.py run the benchmark.
DRAWING_CODE = ["languages/python/src/lbd/plot", "viewer/src/lbd_viewer/explore.py", "uv.lock",
                "scripts/benchmark_explore.py"]
SLOWER = 1.30          # fails when more than 30 % slower ...
AT_LEAST_MS = 10.0     # ... and at least 10 ms slower than the baseline
BASELINE_RUNS = 5      # the baseline: the median of this computer's last 5 passed runs
WIDTH, HEIGHT = 900, 600


# -- the data -------------------------------------------------------------------------------------

def make_data() -> Dict[str, Path]:
    """The three benchmark files (made on first use, ~10 s; the same numbers every time)."""
    import lbd

    files = {"traces": DATA / "traces.lbd", "map": DATA / "map.lbd", "points": DATA / "points.lbd"}
    if all(p.is_file() for p in files.values()):
        return files
    DATA.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(0)
    print("making the benchmark files in", DATA, flush=True)

    nt, n = 1000, 10_000                            # traces: one dip per trace, moving
    f = 4 + 2 * np.arange(n) / (n - 1)
    y = -20 / (1 + ((f[None, :] - (4.5 + np.arange(nt)[:, None] / (nt - 1))) / 0.01) ** 2) \
        + 0.3 * (rng.random((nt, n)) - 0.5)
    d = lbd.Dataset(title="benchmark: 1000 traces x 10000 points")
    d.add_axis("trace", np.arange(float(nt)))
    d.add_axis("freq", f * 1e9, unit="Hz")
    d.add_value("S21", y, axes=["trace", "freq"], unit="dB")
    d.save(files["traces"])

    n = 4001                                        # map: a resonance bending with flux
    f = 4 + 2 * np.arange(n) / (n - 1)
    flux = -1 + 2 * np.arange(n) / (n - 1)
    z = -20 / (1 + ((f[None, :] - (5 + 0.5 * np.cos(np.pi * flux))[:, None]) / 0.02) ** 2) \
        + 0.5 * (rng.random((n, n)) - 0.5)
    d = lbd.Dataset(title="benchmark: map 4001 x 4001")
    d.add_axis("flux", flux * 1e-3, unit="A")
    d.add_axis("freq", f * 1e9, unit="Hz")
    d.add_value("S21", z, axes=["flux", "freq"], unit="dB")
    d.save(files["map"])

    n = 1_000_000                                   # points: one long noisy curve with a spike
    x = np.arange(n) / (n - 1)
    y = np.sin(2 * np.pi * 3 * x) + 0.02 * (rng.random(n) - 0.5)
    y[731_234] = 5
    d = lbd.Dataset(title="benchmark: 1 curve x 1000000 points")
    d.add_axis("x", x)
    d.add_value("signal", y, axes="x")
    d.save(files["points"])
    return files


SPECS = {"traces": {"kind": "curve", "x": "freq", "series": "trace"},
         "map": {"kind": "heatmap", "x": "freq", "y": "flux"},
         "points": {"kind": "curve", "x": "x"}}


# -- measuring ------------------------------------------------------------------------------------

def timed(fn: Callable[[], object]) -> float:
    t = time.perf_counter()
    fn()
    return (time.perf_counter() - t) * 1000


def zoom_views(full, steps: int):
    """Views zooming in by 10 % per step towards a point off the centre (as a mouse wheel does)."""
    (x0, x1), (y0, y1) = full
    cx, cy = x0 + 0.3 * (x1 - x0), y0 + 0.7 * (y1 - y0)
    return [((cx - (cx - x0) * 0.9 ** k, cx + (x1 - cx) * 0.9 ** k),
             (cy - (cy - y0) * 0.9 ** k, cy + (y1 - cy) * 0.9 ** k)) for k in range(1, steps + 1)]


def measure_file(name: str, path: Path, repeats: int) -> Dict[str, float]:
    import lbd
    from lbd.plot.style import Style
    from lbd_viewer import reading
    from lbd_viewer.explore import ExploreSession

    def open_it():
        return ExploreSession(path, "bench", SPECS[name], Style(), WIDTH, HEIGHT, 1.0)

    opens = [timed(open_it) for _ in range(2)]
    s = open_it()
    s.render(None, None)                            # warm up (first draw sets up fonts and caches)
    zoom = zoom_views(s.full, 24)
    mid = zoom[11]
    (x0, x1), (y0, y1) = mid
    pan = [((x0 + k * 0.02 * (x1 - x0), x1 + k * 0.02 * (x1 - x0)), (y0, y1)) for k in range(1, 11)]
    full, steps, panned, sharp_end, sharp_mid = [], [], [], [], []
    for _ in range(repeats):
        full.append(timed(lambda: s.render(None, None)))
        steps.append([timed(lambda v=v: s.render(*v, draft=True)) for v in zoom])
        sharp_end.append(timed(lambda: s.render(*zoom[-1])))
        sharp_mid.append(timed(lambda: s.render(*mid)))
        panned.append([timed(lambda v=v: s.render(*v, draft=True)) for v in pan])
    _, meta = s.render(*mid)
    left, top, w, h = meta["plot"]
    pick = min(timed(lambda: s.pick(left + w * 0.4, top + h * 0.6)) for _ in range(5))
    # a cursor dragged across the view (plot area 800 x 500): one answer per mouse position
    (vx0, vx1), (vy0, vy1) = mid
    first = reading.cursors(s, [{"x": vx0 + 0.3 * (vx1 - vx0), "y": (vy0 + vy1) / 2}], "cross",
                            {"xlim": [vx0, vx1], "ylim": [vy0, vy1]}, (800, 500))["cursors"][0]

    def drag(kind):
        return [min(timed(lambda k=k: reading.cursors(
            s, [{"x": vx0 + (0.3 + 0.02 * k) * (vx1 - vx0), "y": vy0 + (0.5 + 0.01 * k) * (vy1 - vy0),
                 "trace": first.get("trace")}], kind, {"xlim": [vx0, vx1], "ylim": [vy0, vy1]}, (800, 500)))
                    for _ in range(repeats)) for k in range(20)]

    cursor_cross, cursor_vertical = drag("cross"), drag("vertical")
    per_step = [min(col) for col in zip(*steps)]     # each step: its fastest repeat
    per_pan = [min(col) for col in zip(*panned)]
    del lbd
    return {
        "open": min(opens),
        "full view": min(full),
        "zoom draft median": statistics.median(per_step),
        "zoom draft worst": max(per_step),
        "zoomed sharp": min(sharp_mid),
        "deep zoom sharp": min(sharp_end),
        "pan draft median": statistics.median(per_pan),
        "pick": pick,
        "cursor move": statistics.median(cursor_cross),
        "vertical cursor move": statistics.median(cursor_vertical),
    }


def reference_ms() -> float:
    """This computer's speed now, from work like a frame's but without LBD's code: reducing 4 M
    numbers with numpy, then matplotlib drawing an image and a line of 4000 points at the same size
    (fastest of 10). Slower than usual means the computer is busy (or slowed), not LBD."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    rng = np.random.default_rng(1)
    data = rng.random((2000, 2000))
    fig = Figure(figsize=(WIDTH / 96, HEIGHT / 96), dpi=96)
    FigureCanvasAgg(fig)
    ax = fig.add_subplot()
    image = ax.imshow(np.zeros((500, 800)), aspect="auto", interpolation="nearest")
    ax.plot(np.linspace(0, 800, 4000), 250 + 200 * rng.random(4000), lw=0.8)

    def work():
        image.set_data(np.fmax.reduceat(np.fmax.reduceat(data, np.arange(0, 2000, 4), axis=0), np.arange(0, 2000, 2.5).astype(int), axis=1)[:500, :800])
        fig.canvas.draw()

    work()
    return min(timed(work) for _ in range(10))


# -- history --------------------------------------------------------------------------------------

def machine() -> str:
    return platform.node() or "unknown"


def git(*args: str) -> Optional[str]:
    r = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def history(here_only: bool = True) -> List[dict]:
    if not HISTORY.is_file():
        return []
    runs = [json.loads(line) for line in HISTORY.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r for r in runs if r.get("machine") == machine()] if here_only else runs


def baseline(runs: List[dict]) -> Dict[str, float]:
    """Per measurement, the median of the last passed runs since the last --accept."""
    start = max((i for i, r in enumerate(runs) if r.get("accepted")), default=0)
    used = [r for r in runs[start:] if r.get("passed") or r.get("accepted")][-BASELINE_RUNS:]
    keys = {k for r in used for k in r["times"]}
    return {k: statistics.median(r["times"][k] for r in used if k in r["times"]) for k in keys}


def why_run() -> Optional[str]:
    """Why test_all.py should run the benchmark now, or None: the drawing code changed since the
    last run on this computer (or there is none yet)."""
    runs = history()
    if not runs:
        return "no earlier run on this computer"
    last = runs[-1].get("commit")
    if not last or git("cat-file", "-e", f"{last}^{{commit}}") is None:
        return "the last run's commit is unknown here"
    changed = git("diff", "--name-only", last, "--", *DRAWING_CODE)
    if changed is None:
        return "git could not compare with the last run"
    changed += "\n" + (git("ls-files", "--others", "--exclude-standard", "--", *DRAWING_CODE) or "")
    files = [f for f in changed.splitlines() if f.strip()]
    if files:
        return f"drawing code changed since the last run ({', '.join(files[:3])}{', ...' if len(files) > 3 else ''})"
    return None


# -- main -----------------------------------------------------------------------------------------

def show_history(last: int = 8) -> int:
    """The last runs on this computer: one column per run, newest on the right."""
    runs = history()[-last:]
    if not runs:
        print(f"no runs on this computer ({machine()}) yet")
        return 0
    keys = list(dict.fromkeys(k for r in runs for k in r["times"]))
    status = ["accepted" if r.get("accepted") else "passed" if r.get("passed") else "FAILED" for r in runs]
    print(f"{'':34}" + "".join(f"{r['when'][5:16]:>13}" for r in runs))
    print(f"{'commit':34}" + "".join(f"{(r.get('commit') or '?')[:7] + ('+' if r.get('changed_files') else ''):>13}"
                                     for r in runs))
    print(f"{'result':34}" + "".join(f"{x:>13}" for x in status))
    for k in keys:
        print(f"{k:34}" + "".join(f"{r['times'][k]:13.1f}" if k in r["times"] else f"{'-':>13}" for r in runs))
    print("\n(ms; commit+: with uncommitted changes to the drawing code)")
    return 0


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--accept", action="store_true", help="keep this run as the new baseline, even if slower")
    ap.add_argument("--repeats", type=int, default=3, help="repeats of each sequence (default 3)")
    ap.add_argument("--no-save", action="store_true", help="measure and compare, but don't record the run")
    ap.add_argument("--history", action="store_true", help="list the earlier runs on this computer")
    args = ap.parse_args(argv)
    if args.history:
        return show_history()

    files = make_data()
    ref = reference_ms()
    times: Dict[str, float] = {"reference work": ref}
    for name, path in files.items():
        print(f"... {name}", flush=True)
        for k, v in measure_file(name, path, args.repeats).items():
            times[f"{name}: {k}"] = v

    runs = history()
    base = baseline(runs)

    def too_slow(k: str, v: float) -> bool:
        b = base.get(k)
        return b is not None and k != "reference work" and v > b * SLOWER and v - b > AT_LEAST_MS

    # A single frame's time jumps now and then: a file with a time over the limit is measured
    # once more, and each time keeps its faster value, so only a slowdown that repeats fails.
    again = sorted({k.split(":")[0] for k, v in times.items() if too_slow(k, v)})
    for name in again:
        print(f"... {name} again (a time over the limit: measuring once more)", flush=True)
        for k, v in measure_file(name, files[name], args.repeats).items():
            times[f"{name}: {k}"] = min(times[f"{name}: {k}"], v)
    slower = []
    print(f"\nExplore benchmark on {machine()}, plot {WIDTH} x {HEIGHT} px (ms; baseline: median of "
          f"{min(len(runs), BASELINE_RUNS)} earlier run(s) here)\n")
    print(f"  {'':34} {'now':>8} {'baseline':>9} {'change':>8}")
    for k, v in times.items():
        b = base.get(k)
        if b is None:
            print(f"  {k:34} {v:8.1f} {'-':>9} {'':>8}")
            continue
        change = (v - b) / b * 100 if b else 0.0
        bad = too_slow(k, v)
        if bad:
            slower.append(k)
        print(f"  {k:34} {v:8.1f} {b:9.1f} {change:+7.0f}%{'  SLOWER' if bad else ''}")
    rb = base.get("reference work")
    if rb and abs(ref - rb) / rb > 0.1:
        print(f"\nNote: the reference work (numpy and matplotlib without LBD's code) is {(ref - rb) / rb * 100:+.0f}% compared with earlier runs: the "
              "computer is busier or faster than usual, so every time is affected.")

    passed = not slower
    import matplotlib

    run = {"when": time.strftime("%Y-%m-%d %H:%M:%S"), "machine": machine(), "commit": git("rev-parse", "HEAD"),
           "changed_files": bool(git("status", "--porcelain", "--", *DRAWING_CODE)),
           "python": platform.python_version(), "numpy": np.__version__, "matplotlib": matplotlib.__version__,
           "passed": passed, "accepted": args.accept, "times": {k: round(v, 1) for k, v in times.items()}}
    if not args.no_save:
        HISTORY.parent.mkdir(exist_ok=True)
        with HISTORY.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(run) + "\n")
    if passed:
        print("\nNo slowdown." if base else "\nFirst run on this computer: it is the baseline from now on.")
        return 0
    print(f"\n{len(slower)} time(s) more than {round((SLOWER - 1) * 100)} % and {AT_LEAST_MS:.0f} ms slower than "
          "before. If the computer was busy, run this again. If the slowdown is intended, run with --accept "
          "to make it the new baseline. Otherwise find the change that caused it (--history lists the runs "
          "and their commits).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
