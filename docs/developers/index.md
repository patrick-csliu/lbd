# Architecture and setup

This page is for working on LBD itself: the format, the language modules, the viewer and the
installers.

## Repository layout

```
pyproject.toml, uv.lock     uv workspace: one lock and one dev environment for all Python parts
spec/LBD-v1.md              the file format specification (the contract between all parts)
languages/                  one folder per language module, same shape, plus a language.toml manifest
  README.md                   short pointer to the "Adding a language" guide
  _template/                  starting point for a new language
  python/                     package `lbd`: src/lbd/io.py (files), tests/, crosslang/, example.py
    src/lbd/plot/               lbd.plot (extra [plot]): styles and the plotting engine, used by the viewer too
      style.py                    Style schema (matplotlib tree), to_rcparams, font check, .lbd.json, .mplstyle
      presets.py                  preset store shared by viewer and Python (<config dir>/styles)
      render.py                   plot specs -> matplotlib figures: curve, scatter, heatmap
      units.py                    unit prefixes and axis labels
      api.py                      public functions: use, activate, subplots, apply, si, axis_label, save, plot, quick
  matlab/                     package `+lbd`: +lbd/ (private/ = HDF5 helpers), tests/, crosslang/, build_mltbx.m
  julia/                      package `LBD`: Project.toml, src/LBD.jl, test/, crosslang/
viewer/                     LBD Viewer
  pyproject.toml              package `lbd-viewer` (depends on `lbd`), command `lbd-view`
  src/lbd_viewer/
    cli.py                      `lbd-view`: start or reuse a server, open the browser
    server.py                   FastAPI app: HTTP API, security checks, static web UI, /docs/ (Help)
    config.py                   viewer settings (folders, default preset); styles via lbd.plot
    scan.py                     folder listing and search (.lbd, .lbd.json, images)
    images.py                   image metadata and display (view only)
    sdk.py                      Language modules page, built from the language.toml manifests
    static/                     built web UI (generated; not in git)
  tests/test_viewer.py        pytest
  web/                        React + TypeScript UI, built with Vite into src/lbd_viewer/static
    src/App.tsx                 shell: pages, tabs, heartbeat
    src/FolderPanel.tsx         folder tree, add/remove, search
    src/FileView.tsx            file details, plot controls, figure, export, save view
    src/StylesPage.tsx          preset editor (form generated from the Style JSON schema)
    src/SdkPage.tsx             Language modules page (one tab per language)
    src/api.ts                  typed client for the HTTP API
    src/help.tsx                Help links into /docs/
tests/crosslang/            fixture definition + run_all.py (N x N matrix over the discovered languages)
examples/                   sample .lbd files and make_examples.py
  python/                   the scripts of the docs' Examples section (scripts/make_gallery.py)
docs/examples/              generated Examples pages, figures (img/) and printed output (output/)
packaging/                  PyInstaller spec, frozen entry point, SDK staging, icons, installers
scripts/                    languages.py (manifest discovery), test_all.py, check_versions.py,
                            build_windows.ps1, build_linux.sh, check_doc_examples.py (+ doc_examples/),
                            mkdocs_hooks.py (version in the title, generated style tables),
                            make_gallery.py (the Examples section)
mkdocs.yml                  documentation site configuration (MkDocs + Material)
docs/                       documentation pages; reference/python/ is generated from docstrings
site/                       built documentation (generated; not in git)
CHANGELOG.md                release notes, also shown in the documentation
```

## Architecture

```
  program in any language ──writes──►  file.lbd  (HDF5, spec/LBD-v1.md)
                                          ▲
  browser tab (viewer/web) ──HTTP + token──►  lbd-view server (viewer/src/lbd_viewer)
        ▲                                  │  scan.py         lists folders
        │ SVG / downloads                  │  lbd             reads files; set_plot writes /plot
        └──────────────────────────────────┤  lbd.plot        resolves the style (presets) and
                                           │                  draws with matplotlib
  Python script ──── lbd.plot ─────────────┘  (the same style and drawing code)
```

- The **format spec** is the only contract between the language modules. The cross-language
  tests check that every module agrees with it and with every other module.
- **Language manifests** (`languages/<id>/language.toml`) are how the rest of the repository
  knows about a language. `scripts/languages.py` discovers and validates them for the test
  runners, the version check and the SDK packaging. The viewer reads the same files, either
  from `languages/` or from the installed `sdk/` folder, to build its Language modules page.
- The **viewer** is a client of the `lbd` Python module like any other program. It never draws
  in the browser: matplotlib renders every figure on the server, so the screen image and the
  exported PDF come from the same code with the same style. The browser only shows the
  resulting SVG.
- **Styles and drawing live in `lbd.plot`**, not in the viewer, so a Python script and the
  viewer draw with literally the same code and give pixel-identical results (tested). The
  viewer is a client of `lbd` and `lbd.plot` like any other program.
- **Styles** are pydantic models (`lbd.plot.style.Style`) shaped like matplotlib's object tree.
  `Style.to_rcparams()` is the single translation to matplotlib; the renderer, `lbd.plot.use()`
  and the `.mplstyle` export all use it. The UI builds its form from the model's JSON
  schema (`GET /api/style-defaults`), so adding a field to an existing section needs no UI code.

## Setting up

Keep virtual environments, `node_modules` and build output out of a synced folder (Synology
Drive, OneDrive, Dropbox). They are large, change often, and sync clients lock files during
builds. Set `UV_PROJECT_ENVIRONMENT` to a path outside the repository:

```bash
export UV_PROJECT_ENVIRONMENT=~/.venvs/lbd-dev   # PowerShell: $env:UV_PROJECT_ENVIRONMENT = "$HOME\.venvs\lbd-dev"
uv sync --all-packages                           # Python 3.12 (.python-version): lbd, lbd-viewer, dev tools
cd viewer/web
npm ci
npm run build                                    # builds the UI into viewer/src/lbd_viewer/static
```

A fresh clone has no built UI; until you run `npm run build`, `lbd-view` shows a short notice
instead of the app. The same goes for **Help**: build the documentation once (below). Exclude `viewer/web/node_modules` from your sync client.

Each language's own tools need no extra setup. The Julia tests instantiate their environment
themselves, and the MATLAB tests add their folder to the path. Check that every language is
discovered with `uv run python scripts/languages.py`.

Tools: [uv](https://docs.astral.sh/uv/), Node.js 20+, and the language tools you work on:
Julia 1.9+, and MATLAB R2021b+ (R2023a+ to build the `.mltbx`). Building the Windows
installer also needs Inno Setup 6.

## Working on the documentation

The documentation is a [MkDocs](https://www.mkdocs.org/) site with the Material theme;
`mkdocs.yml` is at the repository root and the pages are in `docs/`.

```bash
uv sync --all-packages --group docs
uv run mkdocs serve              # live preview at http://127.0.0.1:8000
uv run mkdocs build --strict     # into site/; lbd-view --dev serves it at /docs/
```

- The **Python API reference** (`docs/reference/python/`) is generated from the docstrings by
  mkdocstrings. Write docstrings in NumPy style; `[lbd.load][]` links to a documented object.
- The **style settings tables** come from the pydantic models in `lbd/plot/style.py`: a line
  `{{ style_table("FrameStyle") }}` in a page becomes the table of that model's fields, with
  type, default, limits and the field's `description` (`scripts/mkdocs_hooks.py`).
- `spec/LBD-v1.md`, `CHANGELOG.md` and the cross-language fixture are included into pages
  with snippets (`--8<--`), so each has one source.
- The site must work offline: no CDN scripts or web fonts. The search shim the offline plugin
  needs is vendored in `docs/assets/vendor/`.
- `uv run python scripts/test_all.py` builds the site in strict mode and runs every code
  example; see [Testing](testing.md#documentation-examples).
- **The public site**, [patrick-csliu.github.io/lbd](https://patrick-csliu.github.io/lbd/),
  shows the latest release. The **Docs** workflow (`.github/workflows/docs.yml`) builds it from
  the release's tag and publishes it to GitHub Pages whenever a release is published. Changes on
  `main` reach it with the next release. **Actions → Docs → Run workflow** publishes it again
  (the latest release, or a tag you enter). One-time setup: **Settings → Pages → Source:
  GitHub Actions**.

## Working on the viewer

1. Start the backend in development mode: port 8765, session code `dev`, never stops by itself.
   It serves the last built UI at http://127.0.0.1:8765/?token=dev.
   ```bash
   uv run lbd-view --dev examples/data
   ```
2. For live UI editing, also run the Vite dev server. It forwards `/api` and `/docs` to the
   backend.
   ```bash
   cd viewer/web && npm run dev     # http://localhost:5173
   ```

Point the viewer at a scratch settings folder with `LBD_CONFIG_DIR=<dir>`, so your real presets
aren't touched, and `LBD_RUNTIME_DIR=<dir>` keeps its "running viewer" record (`server.json`)
apart from an installed viewer's. `python -m lbd_viewer` is the same as `lbd-view`.
