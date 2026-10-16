# Testing

```bash
uv run python scripts/test_all.py          # everything; prints a passed / skipped / failed table
uv run python scripts/test_all.py --fast   # without the cross-language matrix
```

`test_all.py` runs, in order:
1. each language's unit tests, as given by `[test]` in its `language.toml`;
2. the viewer tests;
3. the tests of `scripts/`, `packaging/` and `examples/` (`tests/scripts`, `tests/packaging`);
4. the web UI type check;
5. the documentation: a strict site build (broken links, missing anchors or bad API
   references fail it) and every code example in the docs;
6. the cross-language matrix.

A suite whose program (e.g. `matlab`) isn't on `PATH` is reported as skipped, not failed.

To run single suites:

| Suite | Command |
|---|---|
| Python `lbd` | `uv run pytest languages/python/tests` |
| Viewer | `uv run pytest viewer/tests` |
| Scripts and packaging | `uv run pytest tests/scripts tests/packaging` |
| All Python suites | `uv run pytest` (the root `pyproject.toml` lists every test folder) |
| MATLAB | `cd languages/matlab && matlab -batch "r = runtests('tests'); assert(~any([r.Failed]))"` |
| Julia | `cd languages/julia && julia --project=. -e 'using Pkg; Pkg.test()'` |
| Cross-language | `uv run python tests/crosslang/run_all.py [--only python julia] [--keep DIR]` |
| Web UI types | `cd viewer/web && npm run typecheck` |
| Docs build | `uv run mkdocs build --strict` |
| Doc examples | `uv run python scripts/check_doc_examples.py [--lang python matlab julia] [-v]` |

The fixture content is defined in [the cross-language fixture](#cross-language-fixture).
Run the cross-language matrix after any change to a module or the spec.

## Rules the Python tests follow

- **No test touches your real settings.** The root `conftest.py` points `LBD_CONFIG_DIR` at a
  fresh temporary folder for every test and closes all matplotlib figures afterwards.
- **An unexpected LBD warning fails the test.** `pyproject.toml` turns `lbd.LBDWarning` (and
  its subclasses) into errors; a test that expects one uses `pytest.warns(...)`. Because nothing
  in LBD may change or drop input silently, every such case is either an error or a warning, and
  both are tested.
- Scripts are imported by path with the `load_module` fixture (`load_module("scripts/languages.py")`).

## Coverage

```bash
uv run coverage run --source=lbd,lbd_viewer -m pytest
uv run coverage report -m
```

(`coverage run` rather than `pytest --cov`, because pytest imports `lbd` while reading the
warning filter, before `--cov` starts measuring.) The Python modules are covered to about 96 %;
what is left is mostly platform-specific branches (frozen app, missing optional packages).

## Examples in the docs

The Examples section is made from the scripts in `examples/python/`. After changing one, run
`uv run python scripts/make_gallery.py`: it runs every script in an empty folder and writes the
figures, the printed output and the pages (`docs/examples/`), and the Examples entries of the
nav in `mkdocs.yml`. The code on a page is included from the script itself, so it is never out
of date. A new example `<name>.py` also needs:

- its name in `ORDER` in `make_gallery.py`;
- a docstring with a title line, a paragraph, and `Figure:`, `Code:`, `Tasks:` and `Uses:`
  lines. `Tasks:` uses the task names of `TASKS` in `make_gallery.py`, which make the "Find an
  example by task" table;
- `<name>.md` next to it: the "How it works" explanation shown on its page, with the
  functions linked to the reference (`[lp.plot][lbd.plot.plot]`).

`tests/scripts/test_examples.py` runs every example (LBD warnings count as errors) and checks
that the pages match the scripts (`make_gallery.py --check`).

## Documentation examples

`scripts/check_doc_examples.py` runs every Python, MATLAB and Julia code block in `README.md`,
`languages/*/README.md` and `docs/`, including the ones inside content tabs. Each block runs in
a fresh temporary folder after a short prelude (`scripts/doc_examples/`) that defines the sample
data examples may use: `f`, `p`, `s21`, `t`, `v`, a dataset `d`, files such as `sweep.lbd`,
and the presets `thesis` and `paper`.

Signature blocks (`name(args) -> T`) are skipped automatically. To skip another block, for
example one with placeholder paths, put `<!-- no-check -->` on the line before its fence.

## Cross-language fixture

Every language's `crosslang/` scripts write and check this fixture. It is defined in
`tests/crosslang/README.md`, shown here:

--8<-- "tests/crosslang/README.md:fixture"
