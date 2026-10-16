"""Run the code examples in the documentation.

    uv run python scripts/check_doc_examples.py [--lang python matlab julia] [-v]

Every fenced code block of a language in README.md, languages/*/README.md and docs/ (also the
indented ones inside content tabs) is run in a fresh temporary folder after a small prelude that
defines the sample data the examples use (`f`, `p`, `s21`, `d`, `sweep.lbd`, presets
`thesis`/`paper`, ...). See scripts/doc_examples/.

Blocks that are signatures rather than runnable code (`def f(x) -> T`, `name(args) -> T`) are
skipped automatically. To skip any other block, put `<!-- no-check -->` on the line before its
opening fence.

A language whose program (matlab, julia) is not on PATH is reported as skipped.
Exit code 1 if any example fails.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RUNNERS = Path(__file__).resolve().parent / "doc_examples"
LANGS = ("python", "matlab", "julia")
NO_CHECK = "<!-- no-check -->"
_SUMMARY = re.compile(r"^(\d+)/(\d+) ok$", re.M)
_FENCE = re.compile(r"^(?P<indent>[ \t]*)```(?P<lang>\w+)[^\n]*\n(?P<body>.*?)^(?P=indent)```", re.S | re.M)


def doc_files():
    return [REPO / "README.md", *sorted(REPO.glob("languages/*/README.md")), *sorted((REPO / "docs").rglob("*.md"))]


def extract(lang: str):
    """[{where, code}] for every block of `lang`."""
    blocks = []
    for f in doc_files():
        text = f.read_text(encoding="utf-8")
        for m in _FENCE.finditer(text):
            if m.group("lang") != lang:
                continue
            before = text[: m.start()].rstrip("\n").rsplit("\n", 1)[-1]
            if before.strip() == NO_CHECK:
                continue
            indent = len(m.group("indent"))
            code = "\n".join(line[indent:] for line in m.group("body").split("\n"))
            line = text[: m.start()].count("\n") + 1
            blocks.append({"where": f"{f.relative_to(REPO).as_posix()}:{line}", "code": code})
    return blocks


def run_lang(lang: str, blocks, verbose: bool):
    """(status, output) for one language."""
    work = Path(tempfile.mkdtemp(prefix=f"lbd-doc-{lang}-"))
    blocks_file = work / "blocks.json"
    blocks_file.write_text(json.dumps(blocks), encoding="utf-8")
    env = dict(os.environ, LBD_DOC_BLOCKS=str(blocks_file), LBD_CONFIG_DIR=str(work / "config"),
               LBD_LANG_DIR=str(REPO / "languages" / lang), PYTHONIOENCODING="utf-8")
    if lang == "python":
        cmd = [sys.executable, str(RUNNERS / "run_python.py")]
    elif lang == "matlab":
        exe = shutil.which("matlab")
        if not exe:
            return "skipped", "matlab not on PATH"
        runners = str(RUNNERS).replace("'", "''")
        cmd = [exe, "-batch", f"addpath('{runners}'); run_matlab(getenv('LBD_DOC_BLOCKS'), getenv('LBD_LANG_DIR'))"]
    else:
        exe = shutil.which("julia")
        if not exe:
            return "skipped", "julia not on PATH"
        cmd = [exe, f"--project={REPO / 'languages' / 'julia'}", "--startup-file=no",
               str(RUNNERS / "run_julia.jl"), str(blocks_file)]
    r = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = r.stdout + r.stderr
    shutil.rmtree(work, ignore_errors=True)
    if verbose:
        print(out)
    else:
        print("\n".join(line for line in out.splitlines() if line.startswith("FAIL") or " ok" in line[-6:]))
    summary = _SUMMARY.search(out)
    # A runner that crashes before its summary line must not count as passed.
    ok = (r.returncode == 0 and summary is not None and summary.group(1) == summary.group(2)
          and not any(line.startswith("FAIL") for line in out.splitlines()))
    if summary is None:
        out += "\n(the runner ended without its 'N/M ok' summary line)"
    return ("passed" if ok else "FAILED"), out


def main(argv=None) -> int:
    # Child programs print any character (e.g. Julia's ✓); never crash on a narrow console encoding.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--lang", nargs="+", choices=LANGS, default=list(LANGS))
    ap.add_argument("-v", "--verbose", action="store_true", help="show every block, not only failures")
    args = ap.parse_args(argv)
    failed = False
    for lang in args.lang:
        blocks = extract(lang)
        print(f"== {lang}: {len(blocks)} blocks", flush=True)
        status, out = run_lang(lang, blocks, args.verbose)
        print(f"   {status}" + (f" ({out})" if status == "skipped" else ""))
        failed |= status == "FAILED"
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
