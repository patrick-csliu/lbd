# Changelog

All components (the viewer and the Python, MATLAB and Julia modules) share one version number.
The file format has its own version (`lbd_version`, currently 1.0).

## Unreleased

**Changes to how things behave** (read these when upgrading)

- `lbd.plot` and the viewer no longer plot single numbers: the "single number" plot type
  (`kind="scalar"`) is removed and gives an error that names the valid kinds. The viewer lists
  a file's single numbers with their value (`T1 = 21 µs`), and a file with only single numbers
  shows that list. An old saved view with `kind: "scalar"` falls back to the default, with a
  note.
- An axis with a single point is a fixed parameter (a setting that wasn't swept). A 1 × N
  value is now drawn as curves; it was a heat map one row high, or N one-point curves. The
  viewer shows `Power = -40 dBm (fixed)` instead of a slider.
- Files double-clicked in Explorer / Finder (or `lbd-view file.lbd`) open as tabs in the
  viewer page you used last, instead of a new browser tab each time. **⚙** switches back to
  new browser tabs.

**Viewer: several browser tabs**

- Several browser tabs work together. Each is a numbered page (a new page takes the lowest
  free number). Select tabs (Ctrl/⌘+click, Shift+click) and right-click → **Move to Page N** or
  **Move to a new browser tab**, unsaved settings included.
- A file is open in one page at a time. A rename, deletion, folder or preset change shows in
  every page.
- Robust moves: a closed page leaves the other pages' menus within seconds, even without
  saying goodbye (a crash, a killed browser), and an open menu updates itself ("Page 2 was
  closed"). A move to a page that is gone is refused with a clear message, and closing the new
  browser tab of a move cancels it at once. Messages to a page are sent again if the
  connection dropped, so a file never ends up in two pages. A closing tab can no longer leave a
  ghost page behind that others offered as a target.
- **Open in new browser tab** for files in the folder panel (also Ctrl/⌘+click or middle-click),
  and **◧ Folders** to hide the panel.

**Viewer: plotting**

- Changing the plot type no longer shows a misleading note such as "saved view: 'I' can't be
  used as horizontal axis": settings that belong to the saved plot type are no longer borrowed
  by another type (`lbd.plot` too).
- A value on another axis (e.g. a noise spectrum next to a decay) can be chosen: **On other
  axes** switches the plot to it, instead of the error "can't share the x axis".
- Type the axis value next to a slider (e.g. Power `-42`): it goes to the nearest measured
  point.
- **DPI (PNG/JPG)** next to Width/Height, for this file's raster exports.
- Saving a view into a file that changed since you opened it asks first: Overwrite or Reload.

**Viewer: settings and starting**

- A **Theme** choice under **⚙**: System (follows the light or dark mode of Windows, macOS or
  Linux), Light or Dark. Saved, and every open viewer tab follows at once.
- Starting LBD Viewer from the Start menu (or a shortcut, or with only a folder) while it
  already runs opens a viewer tab. Before, only the open tab's title flashed, because browsers
  don't let a page come to the front.

**Installers**

- Shortcuts: on Windows the installer asks for a **Start menu** shortcut (default yes) and a
  **desktop** shortcut (default no); on Linux `install.sh` asks the same about the applications
  menu and the desktop. On macOS the app is in Launchpad by itself.
- The Windows installer is named `LBD-Viewer-<version>-windows-x64-setup.exe`, like the macOS and
  Linux files.
- The uninstall question is now "Keep your LBD presets and settings…?" (Yes, the default,
  keeps them), on Windows and Linux. "Also remove…? No" was easy to read as "don't keep".
- The Windows uninstaller also removes the empty `.lbd` and `Applications\lbd-view.exe` registry
  keys and the "running viewer" record, so nothing is left behind.
- Linux: `uninstall.sh` ended with an error code when no settings folder existed.

**Documentation**

- **How LBD works**: the core idea in one page, with a diagram: a data file (what you
  measured) + a style (how figures look) → a figure, so one style makes every figure match.
  Also on the home page and in the README.
- The LBD Viewer pages describe every part of the window, with numbered screenshots, and a
  "Common tasks" table for plotting.
- The Quick start is rewritten as six short steps with pictures; its example resonance now
  moves with power, so the plots show something.
- General pages no longer list the supported languages; they link to the one list (Install).
  The format specification says any language with HDF5 can implement LBD.

**For developers**

- Browser tests (Playwright, headless Chromium) of the viewer: several pages, moving tabs in
  unusual ways, a seeded random "chaos" run, the plot controls, the theme. Part of
  `scripts/test_all.py` and CI.
- `scripts/make_screenshots.py` makes the documentation's screenshots;
  `tests/scripts/test_screenshots.py` checks they are all used and exist.
- HTTP API: `GET /api/axis`; the page list (`pages_changed`) and `settings_changed` events;
  `GET /api/pages/{id}/next?after=` confirms commands; `theme` in `/api/settings`. See
  *HTTP API* in the developer docs.
- `LBD_RUNTIME_DIR` moves the "running viewer" record; tests and the smoke test use their own,
  so they never touch an installed viewer's.

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
