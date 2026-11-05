"""Run the test suites and print a summary table.

    uv run python scripts/test_all.py [--fast] [--changed [REF] | --only SUITE ...] [--jobs N]
                                      [--workers N] [--shard I/N] [--record-durations]

The suites (names for --only in brackets):
  1. each language's unit tests ([test] in languages/<id>/language.toml) [python, matlab, julia …],
  2. the viewer's Python tests [viewer], the tests of scripts/ and packaging/ [tools], and the web UI
     type check [web],
  3. the documentation: strict site build [docs] and every code example [examples],
  4. the cross-language round-trip matrix [crosslang] and the viewer's end-to-end tests in a real
     browser [e2e] (viewer/tests/e2e/, Playwright with Chromium), both skipped with --fast,
  5. the Explore benchmark [benchmark] (scripts/benchmark_explore.py), only when the drawing code
     changed since its last run on this computer, or always with --perf; never with --fast or on
     GitHub. It runs alone, after the others: it measures time.

The suites run side by side (--jobs, default 4; --jobs 1: one after the other), so the whole run
takes about as long as its longest suite. The viewer's tests depend on timing; a test of theirs
that fails while other suites load the computer runs again alone at the end, and the summary
names it ("passed alone").

Inside the viewer's suites the tests run in parallel too (pytest-xdist, whole test files per
process): --workers N for the browser tests (default: as many as the computer has cores and
memory for, one Chromium each; the viewer's other tests get 2). --workers 1 runs them one by one.
Tests marked `serial` (they need the computer to themselves) run after the others, one by one.
--shard I/N runs one part of the browser tests (shards.py: whole files, balanced by the times in
viewer/tests/e2e/durations.json), as each CI job does; --record-durations rewrites that file from
this run's times. --changed runs only the suites that the files changed
since REF (default: the last commit, plus files not committed yet) can affect; --only names them.
A suite whose required program (e.g. matlab, or Playwright's Chromium) is missing is reported as skipped.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Set

sys.path.insert(0, str(Path(__file__).resolve().parent))
from languages import REPO, discover  # noqa: E402


def _escape(text: str, title: bool = False) -> str:
    """Escape text for a GitHub Actions workflow command (`::error title=...::message`)."""
    text = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return text.replace(":", "%3A").replace(",", "%2C") if title else text


def run(cmd, cwd: Path, env=None):
    exe = shutil.which(cmd[0])
    if exe:
        cmd = [exe, *cmd[1:]]
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)


E2E_JUNIT = Path(tempfile.gettempdir()) / "lbd-e2e-times.xml"


def workers_for(asked: str):
    """(processes for the browser tests, for the viewer's other tests). auto: one per core but one,
    and no more than the memory holds (about 2 GB each: Chromium, a viewer, its preview workers)."""
    try:
        import xdist  # noqa: F401
    except ImportError:
        return 1, 1
    cores = os.cpu_count() or 1
    if asked != "auto":
        n = max(1, int(asked))
        return n, min(n, 2)
    try:
        import psutil

        ram_gb = psutil.virtual_memory().total / 2**30
    except Exception:
        ram_gb = 8.0
    n = max(1, min(cores - 1 if cores > 2 else cores, int(ram_gb // 2)))
    return n, (2 if cores >= 4 else 1)


def parallel_pytest(where: List[str], workers: int, env=None, junit: Optional[Path] = None):
    """pytest in `workers` processes (whole files each), then the tests marked serial one by one."""
    base = [sys.executable, "-m", "pytest", "-q", *where] + ([f"--junitxml={junit}"] if junit else [])
    if workers <= 1:
        r = run(base, REPO, env)
        return ("passed" if r.returncode in (0, 5) else "FAILED", r.stdout + r.stderr)
    a = run([*base, "-n", str(workers), "--dist", "loadfile", "-m", "not serial"], REPO, env)
    b = run([*[x for x in base if not x.startswith("--junitxml")], "-m", "serial"], REPO, env)
    ok = a.returncode in (0, 5) and b.returncode in (0, 5)      # 5: nothing collected (no serial tests)
    out = a.stdout + a.stderr + ("" if b.returncode == 5 else "\n" + b.stdout + b.stderr)
    return ("passed" if ok else "FAILED", out)


def record_durations(junit: Path) -> Path:
    """Each browser-test file's total time, from a JUnit report, into durations.json."""
    import json
    import xml.etree.ElementTree as ET

    sys.path.insert(0, str(REPO / "viewer" / "tests" / "e2e"))
    import shards

    times: Dict[str, float] = {}
    for case in ET.parse(junit).iter("testcase"):
        name = case.get("classname", "").split(".")[-1] + ".py"
        times[name] = times.get(name, 0.0) + float(case.get("time") or 0)
    old = shards.durations()
    old.update({k: round(v, 1) for k, v in times.items()})
    shards.DURATIONS.write_text(json.dumps(dict(sorted(old.items())), indent=1) + "\n", encoding="utf-8")
    return shards.DURATIONS


def _e2e_missing() -> str:
    """Why the browser tests can't run here, or "" if they can."""
    if not (REPO / "viewer/src/lbd_viewer/static/index.html").is_file():
        return "web UI not built: npm run build in viewer/web"
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "Playwright not installed: uv sync --all-packages"
    with sync_playwright() as p:
        if not Path(p.chromium.executable_path).is_file():
            return "no browser: uv run playwright install chromium"
    return ""


# What a change can affect: the first matching path prefix gives the suites (a language's own
# folder is handled in `affected`). A path that matches nothing runs everything.
AFFECTS = [
    ("planning/", set()), ("CLAUDE.md", set()), (".claude/", set()), (".gitignore", set()),
    ("viewer/tests/e2e/", {"e2e"}), ("viewer/tests/", {"viewer"}), ("viewer/src/", {"viewer", "e2e"}),
    ("viewer/web/", {"web", "e2e"}),
    ("docs/", {"docs", "examples"}), ("mkdocs.yml", {"docs"}), ("spec/", {"docs"}),
    ("CHANGELOG.md", {"docs"}), ("README.md", {"docs"}),
    ("tests/crosslang/README.md", {"crosslang", "docs"}), ("tests/crosslang/", {"crosslang"}), ("scripts/languages.py", {"tools", "crosslang"}),
    ("scripts/check_doc_examples.py", {"tools", "examples"}), ("scripts/", {"tools"}),
    ("packaging/", {"tools"}), ("tests/", {"tools"}), ("examples/", {"tools", "viewer"}),
]


def changed_files(ref: str) -> List[str]:
    """Files changed since `ref`, committed or not, and files git doesn't know yet."""
    out = subprocess.run(["git", "diff", "--name-only", ref], cwd=REPO, capture_output=True, text=True, check=True)
    new = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], cwd=REPO,
                         capture_output=True, text=True, check=True)
    return sorted({p for p in (out.stdout + new.stdout).splitlines() if p.strip()})


def affected(paths: List[str], every: Set[str], languages: List[str]) -> Dict[str, Set[str]]:
    """Suite → the changed files that make it run."""
    why: Dict[str, Set[str]] = {}

    def add(suites, path):
        for s in suites:
            why.setdefault(s, set()).add(path)

    for p in paths:
        parts = p.split("/")
        if parts[0] == "languages" and len(parts) > 2 and parts[1] in languages:
            if parts[2] == "crosslang":
                add({"crosslang"}, p)
            else:
                # a language module: its tests, the files every language reads, its doc examples;
                # the viewer and the tools are built on the Python one
                add({parts[1], "crosslang", "examples"}, p)
                if parts[1] == "python":
                    add({"viewer", "e2e", "tools", "docs"}, p)
            continue
        for prefix, suites in AFFECTS:
            if p == prefix or p.startswith(prefix):
                add(suites, p)
                break
        else:
            add(every, p)                     # not known: everything
    return {s: why[s] for s in why if s in every}


def main(argv=None) -> int:
    # Child programs print any character (e.g. Julia's ✓); never crash on a narrow console encoding.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true", help="skip the cross-language matrix and the browser tests")
    ap.add_argument("--perf", action="store_true", help="also run the Explore benchmark, changed drawing code or not")
    ap.add_argument("--changed", nargs="?", const="HEAD", metavar="REF",
                    help="only the suites the files changed since REF (default HEAD) can affect")
    ap.add_argument("--only", nargs="+", metavar="SUITE", help="only these suites (names: see the top of this file)")
    ap.add_argument("--jobs", type=int, default=4, help="suites run side by side (default 4; 1: one after the other)")
    ap.add_argument("--workers", default="auto",
                    help="processes for the browser tests (default auto: cores and memory allow; 1: one by one)")
    ap.add_argument("--shard", metavar="I/N", help="only part I of N of the browser tests (CI runs the parts side by side)")
    ap.add_argument("--record-durations", action="store_true",
                    help="write each browser-test file's time to viewer/tests/e2e/durations.json (for --shard)")
    args = ap.parse_args(argv)
    sys.path.insert(0, str(REPO / "viewer" / "tests" / "e2e"))
    import shards

    try:
        shard = shards.parse(args.shard)
    except ValueError as e:
        ap.error(str(e))
    e2e_workers, viewer_workers = workers_for(args.workers)

    suites = []   # (name, title, fn), in the order the summary shows them
    e2e_env = {**os.environ, "LBD_SHARD": f"{shard[0]}/{shard[1]}"} if shard else None

    for lang in discover():
        test = lang.section("test")

        def lang_test(lang=lang, test=test):
            if not test.get("command"):
                return ("skipped", "no [test].command in language.toml")
            missing = lang.missing_tool("test")
            if missing:
                return ("skipped", f"{missing} not on PATH")
            r = lang.run(test["command"])
            return ("passed" if r.returncode == 0 else "FAILED", r.stdout + r.stderr)

        suites.append((lang.id, f"{lang.name} tests", lang_test))

    def pytest_suite(*where, workers=1, env=None, junit=None):
        def go():
            return parallel_pytest(list(where), workers, env, junit)
        return go

    def web_typecheck():
        if not shutil.which("npm"):
            return ("skipped", "npm not on PATH")
        if not (REPO / "viewer/web/node_modules").is_dir():
            return ("skipped", "run `npm ci` in viewer/web first")
        r = run(["npm", "run", "typecheck"], REPO / "viewer/web")
        return ("passed" if r.returncode == 0 else "FAILED", r.stdout + r.stderr)

    def docs_build():
        import importlib.util

        if importlib.util.find_spec("mkdocs") is None:
            return ("skipped", "run `uv sync --all-packages --group docs` first")
        with tempfile.TemporaryDirectory() as site:
            r = run([sys.executable, "-m", "mkdocs", "build", "--strict", "-q", "-d", site], REPO)
        return ("passed" if r.returncode == 0 else "FAILED", r.stdout + r.stderr)

    def doc_examples():
        r = run([sys.executable, "scripts/check_doc_examples.py"], REPO)
        return ("passed" if r.returncode == 0 else "FAILED", r.stdout + r.stderr)

    def crosslang():
        r = run([sys.executable, "tests/crosslang/run_all.py"], REPO)
        return ("passed" if r.returncode == 0 else "FAILED", r.stdout + r.stderr)

    def viewer_e2e():
        missing = _e2e_missing()
        if missing:
            return ("skipped", missing)
        # short tracebacks: a failure's reason fits in the lines shown below the summary
        return parallel_pytest(["--tb=short", "viewer/tests/e2e"], e2e_workers, e2e_env,
                               E2E_JUNIT if args.record_durations else None)

    suites += [
        ("viewer", "Viewer tests", pytest_suite("viewer/tests", "--ignore=viewer/tests/e2e", workers=viewer_workers)),
        ("tools", "Script and packaging tests", pytest_suite("tests/scripts", "tests/packaging")),
        ("web", "Web UI type check", web_typecheck),
        ("docs", "Docs build (strict)", docs_build),
        ("examples", "Doc examples", doc_examples),
    ]
    if not args.fast:
        suites += [("crosslang", "Cross-language matrix", crosslang),
                   ("e2e", "Viewer in a browser (e2e)", viewer_e2e)]

    names = {name for name, _, _ in suites}
    chosen: Optional[Set[str]] = None
    if args.only:
        unknown = sorted(set(args.only) - names - {"benchmark"})
        if unknown:
            ap.error(f"unknown suite(s) {unknown}; the suites: {sorted(names | {'benchmark'})}")
        chosen = set(args.only)
    elif args.changed:
        paths = changed_files(args.changed)
        why = affected(paths, names, [n for n, _, _ in suites if n not in
                                      ("viewer", "tools", "web", "docs", "examples", "crosslang", "e2e")])
        chosen = set(why)
        print(f"{len(paths)} file(s) changed since {args.changed}; running: "
              + (", ".join(f"{n} ({sorted(why[n])[0]}{' …' if len(why[n]) > 1 else ''})" for n in sorted(why))
                 or "nothing"), flush=True)
    run_now = [(n, t, fn) for n, t, fn in suites if chosen is None or n in chosen]

    results: Dict[str, tuple] = {}   # title → (status, seconds, output)

    def timed(fn):
        t0 = time.time()
        r = fn()
        status, out = r if r is not None else ("skipped", "")
        return status, time.time() - t0, out

    # the longest suites first, so the whole run takes about as long as the longest one
    longest_first = sorted(run_now, key=lambda s: ["e2e", "viewer", "julia", "crosslang"].index(s[0])
                           if s[0] in ("e2e", "viewer", "julia", "crosslang") else 9)
    if args.jobs <= 1:
        for _, title, fn in run_now:
            print(f"... {title}", flush=True)
            results[title] = timed(fn)
    else:
        print(f"... {len(run_now)} suite(s), {min(args.jobs, len(run_now)) or 1} at a time", flush=True)
        with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
            futures = {pool.submit(timed, fn): title for _, title, fn in longest_first}
            for f in as_completed(futures):
                title = futures[f]
                results[title] = f.result()
                print(f"    {title}: {results[title][0]} ({results[title][1]:.0f}s)", flush=True)

    # timing-sensitive suites: their failed tests run again alone after the others (pytest --lf)
    rerun = {"Viewer tests": ["viewer/tests", "--ignore=viewer/tests/e2e"],
             "Viewer in a browser (e2e)": ["--tb=short", "viewer/tests/e2e"]}
    notes: Dict[str, str] = {}
    if args.jobs > 1 or e2e_workers > 1 or viewer_workers > 1:
        for title, where in rerun.items():
            if title not in results or results[title][0] != "FAILED":
                continue
            failed_tests = [ln.split()[1] for ln in results[title][2].splitlines() if ln.startswith("FAILED ")]
            if not failed_tests:
                continue
            print(f"... {title}: {len(failed_tests)} failed side by side; running them again alone", flush=True)
            t0 = time.time()
            r = run([sys.executable, "-m", "pytest", "-q", "--lf", *where], REPO, e2e_env)
            secs = results[title][1] + time.time() - t0
            if r.returncode == 0:
                results[title] = ("passed", secs, results[title][2])
                notes[title] = f"{', '.join(t.split('::')[-1] for t in failed_tests)} failed side by side, passed alone"
            else:
                results[title] = ("FAILED", secs, r.stdout + r.stderr)

    if args.record_durations and E2E_JUNIT.is_file():
        print(f"    wrote {record_durations(E2E_JUNIT)}", flush=True)

    def benchmark():
        import benchmark_explore

        if os.environ.get("GITHUB_ACTIONS") == "true":
            return ("skipped", "not on GitHub: its shared machines vary too much")
        why = "asked for (--perf)" if args.perf else benchmark_explore.why_run()
        if why is None:
            return ("not needed", "drawing code unchanged since the last run here; --perf runs it anyway")
        print(f"    ({why})", flush=True)
        r = run([sys.executable, "scripts/benchmark_explore.py"], REPO)
        print(r.stdout, flush=True)                 # its table, passed or not
        return ("passed" if r.returncode == 0 else "FAILED", r.stdout + r.stderr)

    wants_bench = chosen is None or "benchmark" in chosen or args.changed is not None
    if (args.perf or (not args.fast and wants_bench)):
        print("... Explore benchmark (alone)", flush=True)
        results["Explore benchmark"] = timed(benchmark)

    order = [t for _, t, _ in run_now] + (["Explore benchmark"] if "Explore benchmark" in results else [])
    print()
    if not order:
        print("nothing to run")
        return 0
    width = max(len(t) for t in order)
    for title in order:
        status, secs, out = results[title]
        note = f"  ({out})" if status in ("skipped", "not needed") and out else ""
        note = f"  ({notes[title]})" if title in notes else note
        print(f"  {title:{width}s}  {status:10s} {secs:6.1f}s{note}")
    failed = [(t, results[t][2]) for t in order if results[t][0] == "FAILED"]
    skipped = [t for t in order if results[t][0] == "skipped"]
    for suite, out in failed:
        lines = out.strip().splitlines()
        tail = "\n".join(lines[-40:])
        print(f"\n===== {suite} output (last 40 lines) =====")
        print(tail)
        if os.environ.get("GITHUB_ACTIONS") == "true":
            # A GitHub annotation: shown on the run's page and readable without signing in. It
            # starts with pytest's list of failed tests (the end of the output may be a long page
            # snapshot that hides which test failed).
            which = [ln for ln in lines if ln.startswith(("FAILED ", "ERROR "))][:20]
            summary = "\n".join(which + (["..."] if which else []) + lines[-25:])
            print(f"::error title={_escape(suite, title=True)} failed::{_escape(summary)}")
    if failed:
        print(f"\n{len(failed)} SUITE(S) FAILED")
    elif skipped:
        print(f"\nPASSED, but {len(skipped)} suite(s) skipped: {', '.join(skipped)}")
    elif chosen is not None:
        print(f"\nPASSED ({len(order)} of {len(suites) + 1} suites; the others weren't affected)")
    else:
        print("\nALL PASSED")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
