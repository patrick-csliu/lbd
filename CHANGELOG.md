# Changelog

All components (the viewer and the Python, MATLAB and Julia modules) share one version number.
The file format has its own version (`lbd_version`, currently 1.0).

## 1.0.0 (2026-10-16)

The first release.

**File format and languages**

- The LBD file format 1.0: a plain HDF5 file with axes, values (real, complex, integer, boolean),
  units and labels, free metadata with nested groups, and an optional saved view and style.
- Modules for Python, MATLAB and Julia that write and read it identically, checked by a
  cross-language test matrix.
- A saved view records the matplotlib version that wrote it (`/plot/matplotlib`).

**Styles**

- Style settings organised like matplotlib's objects: Figure → font, Axes → frame, title, axis
  (label, ticks, minor ticks), x-/y-axis overrides, grid, legend, colours, lines, scatter, image
  and colour bar.
- Presets, shared between the viewer and Python; style files (`<name>.lbd.json`) to save,
  import and export; `.lbd.json` files in your folders can be previewed and imported.
- Export a style as a matplotlib `.mplstyle` file for people without LBD.
- One built-in preset, `default`, with a description of what it is for; make your own presets
  for anything else (two-column figures, slides).
- Fixed scales per quantity (limits, colour map, log scale) and unit prefixes: automatic for
  base units (q … Q), or fixed per quantity (`quantities.freq.prefix = "M"` always shows MHz).
- The built-in `default` style follows the figure rules of APS and AIP journals: 85 × 64 mm,
  Arial 10 pt for all text, 600 dpi, every line ≥ 0.5 pt, colours ordered to stay
  distinguishable in greyscale.

**Python: `lbd.plot`** (install with `pip install "lbd[plot]"`)

- Plot datasets in memory or `.lbd` files exactly like the viewer (`lbd.plot.plot`), quick plots
  of plain arrays (`lbd.plot.quick`).
- Make your own matplotlib figures in the same style: `lbd.plot.use`, `activate`, `subplots`,
  `apply`, `prefix`, `axis_label`, `save`.
- `lbd.plot.prefix` puts a unit prefix on data like the viewer does (7e9 Hz → 7 GHz), or the
  prefix you choose, for any unit (`to="M"`, `to="m"`, `to="c"`, …).

**Plots**

- Curves, heat maps, scatter plots (value against an axis, value against value, the complex I/Q
  plane) and single numbers; complex data as magnitude, dB, phase, real or imaginary part.
- Curve families and scatter points coloured by a short axis get one colour each and a legend
  (with a real minus sign, *Power = −60 dBm*); longer axes and values get a colour bar.
- Annotations: a plot's `annotations` setting draws lines, text, arrows and shapes as matplotlib
  calls (`{"method": "axvline", "args": [7.0]}`, `{"patch": "Rectangle", ...}`). They can be
  saved in the file's view, edited in the viewer (Annotations box) and passed to `lp.plot`.

**Nothing fails silently**

- Invalid input raises an error that names the problem and the valid choices: unknown style
  settings (with a "did you mean" suggestion), unknown values or axes in plot settings, indexes
  out of range, lossy `dtype` conversions, invalid colours, colour maps and markers, unknown
  annotation methods, a font that isn't installed (the message lists the fonts that are),
  unknown request fields in the viewer's HTTP API, broken settings files.
- Input that is used but changed or partly ignored gives a warning (`lbd.LBDWarning` and its
  subclasses): settings that don't apply to a plot type, styles from newer versions, unsorted
  axes, unreadable metadata, annotations on an axis whose unit prefix may change. The viewer
  shows these as notes.
- The folder panel lists entries it can't read instead of hiding them; search reports folders it
  couldn't search.

**Viewer**

- Folder panel with search, plot controls, style presets and the Styles page, saving a view into
  the file, PDF/SVG/PNG/JPG export with a Save as dialog (starts in the data file's folder, name
  filled in; JPG with a warning about its blurred lines), and a Language modules page with the
  Python, MATLAB and Julia modules.
- Folder panel: right-click menu (show in Explorer, copy path, rename, move to the Recycle Bin;
  rename and delete ask first and only work on data, style and image files), collapse all, a line
  between listed folders, and an adjustable width (drag the edge, double-click to fit). Right-click
  a tab to close others or all.
- The Styles page offers the fonts installed on this computer; the file details show which
  matplotlib version saved a file's view.
- Images (PNG, JPEG, GIF, BMP, TIFF, WebP, SVG) in the folder panel, view only, with metadata:
  pixels, dpi, printed size, embedded text.
- **Help**: the documentation ships with the viewer and opens from the top bar, without
  internet. Small **?** buttons open the matching page.

**Documentation**

- A searchable documentation site (MkDocs + Material) with a quick start for all three
  languages, guides, and dark mode.
- An Examples section: eight short scripts with their figures, a "find an example by task"
  table, and a step-by-step explanation on every page with links to the API reference.
- The Python API reference and the style settings tables are generated from the code.
- Every code example in the documentation is run by the test suite.
- Every function documents when to use it, its errors and warnings; a "Which function do I need?"
  page maps tasks to functions.

**Tests**

- Tests for every part: the Python modules, the viewer's HTTP API and helpers, the command
  line, the scripts and packaging tools, the documentation examples, plus robustness tests in
  the MATLAB and Julia suites.

**Project and installers**

- MIT License. Tests run on GitHub on every push (Linux and Windows; MATLAB in its own job).
- Releases: `scripts/bump_version.py` sets the version everywhere and dates the CHANGELOG; a
  version tag makes GitHub test, build and smoke-test the Windows installer, the Linux package
  and the MATLAB toolbox, then create a draft release to check and publish.
- macOS: tests run on macOS too; the viewer installs as two Python wheels with `uv tool install` (with its
  Help and language modules inside); the folder and Save as dialogs use macOS's own dialogs.
- macOS app: LBD Viewer.app in a disk image, for Apple Silicon and Intel, opens `.lbd` files by
  double-click (not signed by a registered developer: approve it once in System Settings).
- Repository organised into `languages/<id>/` with a `language.toml` manifest per language;
  tests, version checks, packaging and the viewer discover languages automatically.
- Installers for Windows (Inno Setup, per user, no admin rights) and Linux (tarball with
  `install.sh`). The Windows installer stops a running viewer before installing or
  uninstalling, and removes its whole folder on uninstall. Uninstalling asks whether to remove
  the presets and settings too (default: keep them; removed ones go to the Recycle Bin). The
  Linux installer checks for Arial, the default style's font, and offers to install it.
