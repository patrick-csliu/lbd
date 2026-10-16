"""Build the documentation's Examples section from examples/python/*.py.

    uv run python scripts/make_gallery.py           # run every example, write figures, output and pages
    uv run python scripts/make_gallery.py --check   # only check that the pages match the scripts

For each example it writes, under docs/examples/:
- img/<name>.png    the figure the script saved as <name>.png,
- output/<name>.txt what the script printed (empty if nothing),
- <name>.md         the page: title, text and "Figure/Code" lines from the script's docstring,
                    the script itself, its output and its explanation (all three included from
                    their files, so they never go stale), and links to the functions it uses,
and index.md (a table of tasks, then the gallery), plus the Examples entries of the nav in
mkdocs.yml.

Each example is two files in examples/python/: the script <name>.py, and <name>.md, the
"How it works" explanation shown on its page (Markdown; link functions to the reference, e.g.
[lp.plot][lbd.plot.plot]). The script's docstring is:

    Title line

    One or more paragraphs.

    Figure: what the figure shows.
    Code: what the code teaches.
    Tasks: Save data to a file; Record measurement settings (metadata)   (names from TASKS)
    Uses: lbd.Dataset, lbd.plot.plot, ...
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "python"
DOCS = ROOT / "docs" / "examples"
MKDOCS = ROOT / "mkdocs.yml"
NAV_START, NAV_END = "      # gallery:start  (written by scripts/make_gallery.py)", "      # gallery:end"

# The order in the gallery: figures first, the style example last.
ORDER = ["curves_resonator", "heatmap_single_shot", "scatter_iq_readout", "subplots_wigner",
         "box_power_sweep", "logscale_noise", "quick_look", "styles_and_presets"]

# The tasks of the index table, in its order, with the functions that do them. An example's
# "Tasks:" line must use these names, so the same task is always found under one name.
TASKS = {
    "Save data to a file": ["lbd.Dataset", "lbd.Dataset.save"],
    "Record measurement settings (metadata)": ["lbd.Dataset"],
    "Read a file back (all of it, or only the header)": ["lbd.load", "lbd.info"],
    "Plot a file like the viewer": ["lbd.plot.plot"],
    "Plot data in memory (without a file)": ["lbd.Dataset", "lbd.plot.plot"],
    "Plot numpy arrays quickly": ["lbd.plot.quick"],
    "Mark points, lines and regions (annotations)": ["lbd.plot.plot"],
    "Store the plot with the file (saved view)": ["lbd.set_plot"],
    "Export PDF, SVG and PNG": ["lbd.plot.save"],
    "Fix a unit prefix (MHz, mV, …)": ["lbd.plot.prefix"],
    "Override the style for one figure": ["lbd.plot.plot", "lbd.plot.load_style"],
    "Your own matplotlib figure in the house style": ["lbd.plot.use", "lbd.plot.axis_label", "lbd.plot.save"],
    "Combine panels with a shared axis": ["lbd.plot.subplots"],
    "Colour points by group with a legend": ["lbd.plot.plot"],
    "Log axes": ["lbd.plot.use"],
    "Make and share a style (preset, style file, .mplstyle)": ["lbd.plot.PresetStore", "lbd.plot.Style"],
}

# Runs one example like a user would, but with LBD's warnings as errors: an example must be clean.
RUNNER = ("import runpy, sys, warnings, lbd; warnings.simplefilter('error', lbd.LBDWarning); "
          "runpy.run_path(sys.argv[1], run_name='__main__')")


class Example:
    def __init__(self, path: Path):
        self.path = path
        self.name = path.stem
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        doc = ast.get_docstring(tree)
        # The page shows the code from the first line after the docstring (the docstring is the
        # page's text already); blank lines right after it are skipped too.
        lines_all = source.splitlines()
        first = tree.body[0].end_lineno if doc else 0
        while first < len(lines_all) and not lines_all[first].strip():
            first += 1
        self.code_lines = (first + 1, len(lines_all))
        if not doc:
            raise SystemExit(f"{path.name}: needs a docstring (title, text, Figure:, Code:, Tasks:, Uses:)")
        lines = doc.splitlines()
        self.title = lines[0].strip()
        fields, text = {}, []
        for line in lines[1:]:
            key, _, value = line.partition(":")
            if key in ("Figure", "Code", "Tasks", "Uses") and value:
                fields[key] = value.strip()
            else:
                text.append(line)
        missing = [k for k in ("Figure", "Code", "Tasks", "Uses") if k not in fields]
        if missing:
            raise SystemExit(f"{path.name}: docstring needs the line(s) {', '.join(m + ':' for m in missing)}")
        self.text = "\n".join(text).strip()
        self.figure, self.code = fields["Figure"], fields["Code"]
        self.uses = [u.strip() for u in fields["Uses"].split(",") if u.strip()]
        self.tasks = [t.strip() for t in fields["Tasks"].split(";") if t.strip()]
        unknown = [t for t in self.tasks if t not in TASKS]
        if unknown:
            raise SystemExit(f"{path.name}: unknown task(s) {unknown}; use the names in TASKS in make_gallery.py")
        self.explanation = path.with_suffix(".md")
        if not self.explanation.is_file():
            raise SystemExit(f"{path.name}: needs its explanation {self.explanation.name} next to it")

    def printed(self) -> bool:
        out = DOCS / "output" / f"{self.name}.txt"
        return out.is_file() and bool(out.read_text(encoding="utf-8").strip())

    def page(self) -> str:
        rel = self.path.relative_to(ROOT).as_posix()
        links = ", ".join(f"[`{u.replace('lbd.plot.', 'lp.')}`][{u}]" for u in self.uses)
        output = f"""
<!-- no-check -->
```text title="Printed output"
--8<-- "docs/examples/output/{self.name}.txt"
```
""" if self.printed() else ""
        return f"""# {self.title}

{self.text}

- **Figure:** {self.figure}
- **Code:** {self.code}

<!-- no-check -->
```python title="{self.path.name}"
--8<-- "{rel}:{self.code_lines[0]}:{self.code_lines[1]}"
```

## Result

![{self.title}](img/{self.name}.png)
{output}
## How it works

--8<-- "{self.explanation.relative_to(ROOT).as_posix()}"

**Functions used:** {links}

<small>To run it, copy the code into a file and run it with Python in an empty folder: it writes
its figure and files there. This page is made from `{rel}` by `scripts/make_gallery.py`.</small>
"""


def examples() -> list:
    found = {p.stem: p for p in EXAMPLES.glob("*.py")}
    unknown = sorted(set(found) - set(ORDER))
    missing = [n for n in ORDER if n not in found]
    if unknown or missing:
        raise SystemExit(f"examples and ORDER in make_gallery.py differ: not in ORDER {unknown}, "
                         f"missing files {missing}")
    return [Example(found[n]) for n in ORDER]


def _ref(u: str) -> str:
    return f"[`{u.replace('lbd.plot.', 'lp.')}`][{u}]"


def task_table(exs) -> str:
    rows = ["| I want to … | Example | Functions |", "|---|---|---|"]
    for task, funcs in TASKS.items():
        users = [e for e in exs if task in e.tasks]
        if not users:
            continue
        pages = ", ".join(f"[{e.title.split(':')[0]}]({e.name}.md)" for e in users)
        rows.append(f"| {task} | {pages} | {', '.join(_ref(f) for f in funcs)} |")
    return "\n".join(rows)


def index(exs) -> str:
    cards = []
    for e in exs:
        cards.append(f"""-   [![{e.title}](img/{e.name}.png)]({e.name}.md)

    **[{e.title}]({e.name}.md)**

    {e.code}
""")
    return """# Examples

Each example is one short Python script that you can copy and run. Every page shows the code,
what it makes, and how it works step by step, with links to the functions it uses.

## Find an example by task

""" + task_table(exs) + """

## Gallery

<div class="grid cards" markdown>

""" + "\n".join(cards) + """
</div>
"""


def nav(exs) -> str:
    # The part of the title before ':' ("Heat map: single-shot ..." -> "Heat map"), quoted for YAML.
    return "\n".join(f"      - {json.dumps(e.title.split(':')[0])}: examples/{e.name}.md" for e in exs)


def set_nav(text: str, entries: str) -> str:
    start, end = text.index(NAV_START), text.index(NAV_END)
    return text[: start + len(NAV_START)] + "\n" + entries + "\n" + text[end:]


def run(e: Example, tmp: Path) -> str:
    folder = tmp / e.name
    folder.mkdir()
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "LBD_CONFIG_DIR": str(tmp / "config" / e.name),
           "MPLBACKEND": "Agg"}
    r = subprocess.run([sys.executable, "-c", RUNNER, str(e.path)], cwd=folder, env=env,
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode:
        raise SystemExit(f"{e.path.name} failed:\n{r.stdout}{r.stderr}")
    png = folder / f"{e.name}.png"
    if not png.is_file():
        raise SystemExit(f"{e.path.name} must save its figure as {e.name}.png")
    shutil.copy(png, DOCS / "img" / png.name)
    return r.stdout


def check(exs) -> list:
    """Problems: pages, index or nav that don't match the scripts, or missing figures/output."""
    problems = []
    for e in exs:
        page = DOCS / f"{e.name}.md"
        if not page.is_file() or page.read_text(encoding="utf-8") != e.page():
            problems.append(f"{page.relative_to(ROOT)} is out of date")
        for f in (DOCS / "img" / f"{e.name}.png", DOCS / "output" / f"{e.name}.txt"):
            if not f.is_file():
                problems.append(f"{f.relative_to(ROOT)} is missing")
    idx = DOCS / "index.md"
    if not idx.is_file() or idx.read_text(encoding="utf-8") != index(exs):
        problems.append("docs/examples/index.md is out of date")
    text = MKDOCS.read_text(encoding="utf-8")
    if set_nav(text, nav(exs)) != text:
        problems.append("the Examples nav in mkdocs.yml is out of date")
    pages = {p.stem for p in DOCS.glob("*.md")} - {"index"}
    stale = sorted(pages - {e.name for e in exs})
    if stale:
        problems.append(f"pages without an example: {stale}")
    # The docs home page shows some examples by hand: their figures and pages must exist.
    home = (ROOT / "docs" / "index.md").read_text(encoding="utf-8")
    for link in sorted(set(re.findall(r"\(examples/([\w/.-]+\.(?:png|md))", home))):
        if not (DOCS / link).is_file():
            problems.append(f"docs/index.md links to examples/{link}, which doesn't exist")
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="only check that the pages match the scripts")
    args = ap.parse_args(argv)
    exs = examples()
    if args.check:
        problems = check(exs)
        for p in problems:
            print("out of date:", p)
        if problems:
            print("run: uv run python scripts/make_gallery.py")
        return 1 if problems else 0

    for sub in ("img", "output"):
        (DOCS / sub).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lbd-gallery-") as tmp:
        for e in exs:
            print(f"running {e.path.name}", flush=True)
            out = run(e, Path(tmp))
            (DOCS / "output" / f"{e.name}.txt").write_text(out, encoding="utf-8")
            (DOCS / f"{e.name}.md").write_text(e.page(), encoding="utf-8")
    for old in [*DOCS.glob("*.md"), *DOCS.glob("img/*.png"), *DOCS.glob("output/*.txt")]:
        if old.stem != "index" and old.stem not in ORDER:     # an example that was removed
            old.unlink()
    (DOCS / "index.md").write_text(index(exs), encoding="utf-8")
    MKDOCS.write_text(set_nav(MKDOCS.read_text(encoding="utf-8"), nav(exs)), encoding="utf-8")
    print(f"{len(exs)} examples -> docs/examples/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
