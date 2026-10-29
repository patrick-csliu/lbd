"""Run every test suite and print a summary table.

    uv run python scripts/test_all.py [--fast]

Runs, in order:
  1. each language's unit tests ([test] in languages/<id>/language.toml),
  2. the viewer's Python tests, the tests of scripts/ and packaging/, and the web UI type check,
  3. the documentation: strict site build and every code example (scripts/check_doc_examples.py),
  4. the cross-language round-trip matrix and the viewer's end-to-end tests in a real browser
     (viewer/tests/e2e/, Playwright with Chromium), both skipped with --fast,
  5. the Explore benchmark (scripts/benchmark_explore.py), only when the drawing code changed since
     its last run on this computer, or always with --perf; never with --fast or on GitHub.
A suite whose required program (e.g. matlab, or Playwright's Chromium) is missing is reported as skipped.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from languages import REPO, discover  # noqa: E402


def _escape(text: str, title: bool = False) -> str:
    """Escape text for a GitHub Actions workflow command (`::error title=...::message`)."""
    text = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return text.replace(":", "%3A").replace(",", "%2C") if title else text


def run(cmd, cwd: Path):
    exe = shutil.which(cmd[0])
    if exe:
        cmd = [exe, *cmd[1:]]
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")


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


def main(argv=None) -> int:
    # Child programs print any character (e.g. Julia's ✓); never crash on a narrow console encoding.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true", help="skip the cross-language matrix and the browser tests")
    ap.add_argument("--perf", action="store_true", help="also run the Explore benchmark, changed drawing code or not")
    args = ap.parse_args(argv)

    results = []  # (suite, status, seconds, output)

    def record(suite: str, fn):
        print(f"... {suite}", flush=True)
        t0 = time.time()
        r = fn()
        if r is None:
            results.append((suite, "skipped", 0.0, ""))
            return
        status, out = r
        results.append((suite, status, time.time() - t0, out))

    for lang in discover():
        test = lang.section("test")
        if not test.get("command"):
            record(f"{lang.name} tests", lambda: ("skipped", "no [test].command in language.toml"))
            continue

        def lang_test(lang=lang, test=test):
            missing = lang.missing_tool("test")
            if missing:
                return ("skipped", f"{missing} not on PATH")
            r = lang.run(test["command"])
            return ("passed" if r.returncode == 0 else "FAILED", r.stdout + r.stderr)

        record(f"{lang.name} tests", lang_test)

    def viewer_tests():
        r = run([sys.executable, "-m", "pytest", "-q", "viewer/tests", "--ignore=viewer/tests/e2e"], REPO)
        return ("passed" if r.returncode == 0 else "FAILED", r.stdout + r.stderr)

    def tools_tests():
        r = run([sys.executable, "-m", "pytest", "-q", "tests/scripts", "tests/packaging"], REPO)
        return ("passed" if r.returncode == 0 else "FAILED", r.stdout + r.stderr)

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

    record("Viewer tests", viewer_tests)
    record("Script and packaging tests", tools_tests)
    record("Web UI type check", web_typecheck)
    record("Docs build (strict)", docs_build)
    record("Doc examples", doc_examples)
    if not args.fast:
        def crosslang():
            r = run([sys.executable, "tests/crosslang/run_all.py"], REPO)
            return ("passed" if r.returncode == 0 else "FAILED", r.stdout + r.stderr)

        record("Cross-language matrix", crosslang)

        def viewer_e2e():
            missing = _e2e_missing()
            if missing:
                return ("skipped", missing)
            # short tracebacks: a failure's reason fits in the lines shown below the summary
            r = run([sys.executable, "-m", "pytest", "-q", "--tb=short", "viewer/tests/e2e"], REPO)
            return ("passed" if r.returncode == 0 else "FAILED", r.stdout + r.stderr)

        record("Viewer in a browser (e2e)", viewer_e2e)

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

    if args.perf or not args.fast:
        record("Explore benchmark", benchmark)

    print()
    width = max(len(s) for s, *_ in results)
    for suite, status, secs, out in results:
        note = ""
        if status in ("skipped", "not needed") and out:
            note = f"  ({out})"
        print(f"  {suite:{width}s}  {status:10s} {secs:6.1f}s{note}")
    failed = [r for r in results if r[1] == "FAILED"]
    skipped = [r for r in results if r[1] == "skipped"]
    for suite, _, _, out in failed:
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
        print(f"\nPASSED, but {len(skipped)} suite(s) skipped: {', '.join(r[0] for r in skipped)}")
    else:
        print("\nALL PASSED")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
