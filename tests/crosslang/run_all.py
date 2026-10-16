"""Cross-language round trip: every language writes the fixture, every language reads all of them.

    uv run python tests/crosslang/run_all.py [--keep OUTDIR] [--only ID ...]

Languages are discovered from languages/*/language.toml ([crosslang] section); a language whose
required program is not on PATH is skipped with a notice. The fixture is defined in README.md
next to this script.
"""

import argparse
import shutil
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
    if not args.keep:
        shutil.rmtree(root, ignore_errors=True)
    n = len(langs)
    print(f"{'ALL OK' if ok else 'FAILURES'} ({n} languages, {n}x{n} reads)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
