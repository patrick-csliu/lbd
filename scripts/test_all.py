"""Run every test suite and print a summary table.

    uv run python scripts/test_all.py [--fast]

Runs, in order:
  1. each language's unit tests ([test] in languages/<id>/language.toml),
  2. the viewer's Python tests, the tests of scripts/ and packaging/, and the web UI type check,
  3. the documentation: strict site build and every code example (scripts/check_doc_examples.py),
  4. the cross-language round-trip matrix (skipped with --fast).
A suite whose required program (e.g. matlab) is not on PATH is reported as skipped.
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from languages import REPO, discover  # noqa: E402


def run(cmd, cwd: Path):
    exe = shutil.which(cmd[0])
    if exe:
        cmd = [exe, *cmd[1:]]
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def main(argv=None) -> int:
    # Child programs print any character (e.g. Julia's ✓); never crash on a narrow console encoding.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true", help="skip the cross-language matrix")
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
        r = run([sys.executable, "-m", "pytest", "-q", "viewer/tests"], REPO)
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

    print()
    width = max(len(s) for s, *_ in results)
    for suite, status, secs, out in results:
        note = ""
        if status == "skipped" and out:
            note = f"  ({out})"
        print(f"  {suite:{width}s}  {status:8s} {secs:6.1f}s{note}")
    failed = [r for r in results if r[1] == "FAILED"]
    skipped = [r for r in results if r[1] == "skipped"]
    for suite, _, _, out in failed:
        print(f"\n===== {suite} output (last 40 lines) =====")
        print("\n".join(out.strip().splitlines()[-40:]))
    if failed:
        print(f"\n{len(failed)} SUITE(S) FAILED")
    elif skipped:
        print(f"\nPASSED, but {len(skipped)} suite(s) skipped: {', '.join(r[0] for r in skipped)}")
    else:
        print("\nALL PASSED")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
