"""Cross-language round trip: every language writes the fixture, every language reads all of them.

    uv run python tests/crosslang/run_all.py [--keep OUTDIR] [--only ID ...]

Languages are discovered from languages/*/language.toml ([crosslang] section); a language whose
required program is not on PATH is skipped with a notice. The fixture is defined in README.md
next to this script. Then a Python measurement is written slowly, and every language with a
`read_live` command reads it while it is written.
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from languages import discover  # noqa: E402


def show(result) -> None:
    text = (result.stdout + result.stderr).strip()
    if text:
        print("\n".join("    " + line for line in text.splitlines()))


def main(argv=None) -> int:
    # Child programs print any character (e.g. Julia's ✓); never crash on a narrow console encoding.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", type=Path, help="write fixtures here and keep them")
    ap.add_argument("--only", nargs="+", metavar="ID", help="run only these languages")
    args = ap.parse_args(argv)

    known = discover()
    if args.only:
        unknown = set(args.only) - {lang.id for lang in known}
        if unknown:
            print(f"--only: unknown language id(s) {sorted(unknown)}; known: {[lang.id for lang in known]}",
                  file=sys.stderr)
            return 2
    langs = []
    for lang in known:
        if not lang.section("crosslang") or (args.only and lang.id not in args.only):
            continue
        missing = lang.missing_tool("crosslang")
        if missing:
            print(f"{lang.name}: skipped ({missing} not on PATH)")
            continue
        langs.append(lang)

    if not langs:
        print("no language could be tested (all skipped)", file=sys.stderr)
        return 1
    root = args.keep or Path(tempfile.mkdtemp(prefix="lbd-crosslang-"))
    root.mkdir(parents=True, exist_ok=True)
    print(f"fixtures in {root}")
    ok = True
    for lang in langs:
        print(f"[write] {lang.name}")
        r = lang.run(lang.section("crosslang")["write"], out=root / lang.id, root=root)
        show(r)
        ok &= r.returncode == 0
    for lang in langs:
        print(f"[check] {lang.name}")
        r = lang.run(lang.section("crosslang")["check"], root=root)
        show(r)
        ok &= r.returncode == 0
    ok &= read_while_measuring(langs, root)
    if not args.keep:
        shutil.rmtree(root, ignore_errors=True)
    n = len(langs)
    print(f"{'ALL OK' if ok else 'FAILURES'} ({n} languages, {n}x{n} reads)")
    return 0 if ok else 1


LIVE_ROWS = 200        # written at about 20 rows per second


def read_while_measuring(langs, root: Path) -> bool:
    """A Python measurement read by every language while it is written (needs Python's Writer)."""
    readers = [lang for lang in langs if lang.section("crosslang").get("read_live")]
    if not readers or not any(lang.id == "python" for lang in langs):
        return True
    print(f"[live] {', '.join(lang.name for lang in readers)} reading a Python measurement while it is written")
    folder = root / "live-reading"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "measuring.lbd"
    procs = [subprocess.Popen(lang.command(lang.section("crosslang")["read_live"], file=target, root=root),
                              cwd=lang.dir, env=lang.env(file=target, root=root), stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
             for lang in readers]
    python = next(lang for lang in langs if lang.id == "python")
    writer = python.run(["{python}", "crosslang/write_live.py", str(target), str(LIVE_ROWS),
                         *(lang.id for lang in readers)])
    show(writer)
    ok = writer.returncode == 0
    for lang, proc in zip(readers, procs):
        try:
            out, _ = proc.communicate(timeout=180)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()
            out += f"\n{lang.name}: still reading after 180 s"
        print("\n".join("    " + line for line in out.strip().splitlines()))
        ok &= proc.returncode == 0
    return ok


if __name__ == "__main__":
    sys.exit(main())
