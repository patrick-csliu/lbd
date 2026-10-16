# LBD — Lab Data format and viewer

[![Tests](https://github.com/patrick-csliu/lbd/actions/workflows/tests.yml/badge.svg)](https://github.com/patrick-csliu/lbd/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**One data format for every program, and one viewer for every figure.**

Lab data comes from many programs: MATLAB scripts, Python notebooks, Julia simulations,
instrument software. Each plots with its own library, so figures from different programs, or
from last year and this year, never look alike and are hard to compare. LBD fixes this:

- Every program saves its data as an **`.lbd` file**, using a small module for **Python,
  MATLAB or Julia**. The same file reads back identically in all three languages.
- **LBD Viewer** opens every `.lbd` file and draws it with **one** matplotlib style system. A
  figure looks the same whichever program made the data, and what you see is exactly what
  exports to PDF for your paper.

## Features

- **The `.lbd` format:** plain HDF5 inside, so HDFView and h5py can also open it.
  - Axes with units and labels; N-D values; complex and boolean data; nested metadata.
  - The same array shape in every language: no transposing.
  - Version checks, so old tools never misread new files.
- **Language modules:** the same API in Python (`lbd`), MATLAB (`lbd.*`) and Julia (`LBD`),
  verified by a cross-language test matrix.
- **`lbd.plot` for Python:** the viewer's styles and plot types in your own scripts:
  - plot data straight from memory, without saving it first;
  - make your own matplotlib figures with the same size, fonts, colours and line widths;
  - annotations (lines, text, arrows, shapes) as matplotlib calls, saved with the file's view.
- **Styles shaped like matplotlib** (Figure → Axes → frame, axis, ticks, legend, …):
  - presets shared between the viewer and Python;
  - style files (`*.lbd.json`) to keep with a paper;
  - `.mplstyle` export for plain matplotlib users.
- **LBD Viewer** (Windows and Linux):
  - a folder panel with search and a right-click menu (show in Explorer, copy path, rename,
    move to the Recycle Bin);
  - curves, scatter plots (also value vs value, the complex I/Q plane, colour by a third
    quantity) and heat maps; complex data as magnitude/dB/phase; sliders for higher dimensions;
  - style presets, with fixed colour scales per quantity for fair comparisons;
  - save a view (plot settings, style, annotations) into the file;
  - export PDF/SVG/PNG/JPG at an exact physical size, with a Save as dialog;
  - images (PNG, JPEG, TIFF, SVG, …) shown with their metadata, view only;
  - double-click any `.lbd` file to open it.

## Quick start

### 1. Install the viewer

- **Windows:** run `LBDViewer-Setup-<version>.exe`. No admin rights are needed.
- **Linux:** unpack the archive and run `./install.sh`.

After that, double-click any `.lbd` file. See [Install](docs/getting-started/install.md).

### 2. Install the module for your language

The viewer's **Language modules** page shows the exact command for your computer:

| Language | Install |
|---|---|
| Python | `pip install "<sdk>/python/lbd-<version>-py3-none-any.whl[plot]"` (`[plot]` adds `lbd.plot`) |
| MATLAB | double-click `<sdk>/matlab/LBD.mltbx` |
| Julia | `using Pkg; Pkg.develop(path="<sdk>/julia")` |

### 3. Write data

**Python**
```python
import numpy as np, lbd

f = np.linspace(4e9, 8e9, 401); p = np.arange(-40, 1, 4.0)
d = lbd.Dataset(title="Resonator power sweep")
d.add_axis("power", p, unit="dBm", label="Power")
d.add_axis("freq", f, unit="Hz", label="Frequency")
d.add_value("S21", np.exp(1j * np.outer(p, f) * 1e-10), axes=["power", "freq"])
d.meta["T_mK"] = 12
d.save("sweep.lbd")                      # lbd.load("sweep.lbd")["S21"].data -> (11, 401)
```

**MATLAB**
```matlab
f = linspace(4e9, 8e9, 401); p = -40:4:0;
d = lbd.Dataset("Resonator power sweep");
d.addAxis("power", p, Unit="dBm", Label="Power");
d.addAxis("freq", f, Unit="Hz", Label="Frequency");
d.addValue("S21", exp(1i * (p' * f) * 1e-10), ["power" "freq"]);
d.Meta.T_mK = 12;
d.save("sweep.lbd");                     % lbd.load("sweep.lbd").Values.S21.Data -> 11 x 401
```

**Julia**
```julia
using LBD
f = collect(range(4e9, 8e9, 401)); p = collect(-40.0:4:0)
d = LBD.Dataset("Resonator power sweep")
add_axis!(d, "power", p; unit="dBm", label="Power")
add_axis!(d, "freq", f; unit="Hz", label="Frequency")
add_value!(d, "S21", exp.(1im .* (p * f') .* 1e-10), ["power", "freq"])
d.meta["T_mK"] = 12
LBD.save("sweep.lbd", d)                 # size(LBD.load("sweep.lbd")["S21"].data) -> (11, 401)
```

### 4. Look at it

Double-click `sweep.lbd`, or add its folder to the viewer's folder panel. Choose how to plot
it, then export the figure or save the view into the file.

Or plot it in Python with the same styles, from memory or from the file:

```python
import lbd.plot as lp
fig = lp.plot(d, "heatmap", "S21", complex="db", style="default")   # d: the Dataset above
lp.save(fig, "sweep.pdf")

import matplotlib.pyplot as plt
with lp.use("default"):                 # your own figure, same look
    fig, ax = plt.subplots()
    ax.plot(f, np.abs(d["S21"].data[0]))
    fig.savefig("my_figure.pdf")
```

## Documentation

The full documentation is a searchable website built from `docs/` with
[MkDocs](https://www.mkdocs.org/) and Material for MkDocs. LBD Viewer ships a copy that works
offline: use **Help** in the viewer's top bar. To build or preview it from the repository:

```bash
uv sync --all-packages --group docs
uv run mkdocs serve              # live preview at http://127.0.0.1:8000
uv run mkdocs build --strict     # the site in site/ (open site/index.html)
```

The Python API reference and the style settings tables are generated from the code's
docstrings, so they always match the code. Good starting points (Markdown sources):

| | |
|---|---|
| [Quick start](docs/getting-started/quickstart.md) | Write a file, look at it, make matching figures: Python, MATLAB, Julia. |
| [Concepts](docs/getting-started/concepts.md) | What a file contains, dimension order, types, names, versions. |
| [Install](docs/getting-started/install.md) | Viewer and modules: install, upgrade, uninstall. |
| [Examples](docs/examples/index.md) | Short scripts with their figures, explained step by step, and a "find an example by task" table. |
| [LBD Viewer](docs/viewer/index.md) | Every feature of the viewer. |
| [Styles](docs/styles/index.md) | How styles work, every setting, fixed scales, style files. |
| Languages | [Python](docs/python/files.md) · [lbd.plot](docs/python/plotting.md) · [MATLAB](docs/matlab.md) · [Julia](docs/julia.md) |
| [Developers](docs/developers/index.md) | Architecture, tests, HTTP API, extending, building releases. |
| [File format spec](spec/LBD-v1.md) | The exact HDF5 layout. |

## Project layout

```
spec/                 file format specification (the contract every language follows)
languages/            one folder per language, all with the same shape + a language.toml manifest
  python/               Python module `lbd`
  matlab/               MATLAB package `+lbd`
  julia/                Julia package `LBD`
  _template/            starting point for a new language (see languages/README.md)
viewer/               LBD Viewer
  src/lbd_viewer/       backend (Python package `lbd-viewer`, command `lbd-view`)
  web/                  user interface (React + TypeScript)
tests/crosslang/      every language reads every language's files (discovered from the manifests)
examples/             example .lbd files and the script that makes them
  python/               example scripts + explanations (scripts/make_gallery.py builds docs/examples/)
packaging/            installer build files (PyInstaller, Inno Setup, Linux install scripts)
scripts/              test runner, version check, release build scripts
docs/                 documentation sources (MkDocs; mkdocs.yml at the root)
```

Adding a language means adding a folder under `languages/`; the tests, the version check, the
installer and the viewer pick it up from its `language.toml`. See
[Adding a language](docs/developers/adding-a-language.md).

## Development quick start

Keep the virtual environment outside synced folders, and exclude `viewer/web/node_modules` from
sync:

```bash
export UV_PROJECT_ENVIRONMENT=~/.venvs/lbd-dev
uv sync --all-packages --group docs            # the lbd module, the viewer, dev and docs tools
(cd viewer/web && npm ci && npm run build)     # the viewer's user interface
uv run python scripts/test_all.py              # every test suite, every language
uv run lbd-view --dev examples/data            # http://127.0.0.1:8765/?token=dev
```

The full test and release instructions are in the [developer guide](docs/developers/index.md).

## Requirements

| Part | Requirement |
|---|---|
| Viewer | 64-bit Windows 10/11 or Linux desktop |
| Python module | Python 3.9+ (numpy, h5py; `[plot]` adds matplotlib, pydantic, platformdirs) |
| MATLAB module | MATLAB R2021b+ |
| Julia module | Julia 1.9+ (HDF5.jl, JSON3.jl) |

## License

MIT, see [LICENSE](LICENSE). Each language folder carries a copy, since a module can be
installed from its folder alone.
