# Changelog

All components (the viewer and every language module) share one version number.
The file format has its own version (`lbd_version`, currently 2.0; files without an axis group
are still written as 1.2).

## 1.3.0 (in development)

**Changes to how things behave** (read these when upgrading)

- **File format 2.0: variable sweeps** (axis groups, spec §1.8; every language). A sweep whose
  inner points depend on the outer ones (frequencies chosen per power, a different number of
  points per row, adaptive points) is stored as an axis group: only the measured points, level
  by level. Writers write 2.0 only for a file with an axis group; **every other file is still
  written as 1.2**, so older LBD keeps reading it. **LBD older than 1.3 can't open 2.0 files**
  ("please update"). `lbd.version()` gives `"2.0"`, the newest format read and written. See
  *Concepts → Variable sweeps* and *Grid or group?*.

- **A value's `axes` are what was swept** (every language). The dimensions of a data point
  (`shape=`, format 1.2) are no longer axes of the dataset: `d.axes` holds only sweep axes, and
  the value describes its data point with `point_shape` and `elements`; new is `dims`, how the
  sweep part is stored (`[("amp",)]`, or `[("A", "B")]` for a group's points). Gone: Python
  `v.point_axes` and `d.axes["bloch_dim1"]`; MATLAB `PointAxes` and `Axes.bloch_dim1` (new
  `PointShape`, `Dims`); Julia `v.point_axes` and `d.axes["bloch_dim1"]` (`v.point_shape` is a
  field now, `v.dims` new). `data` and the file are unchanged (the file still stores a data
  point's dimensions as axes with `role="point"`).

- **File format 1.1: every file gets an `id`** (every language). It is the measurement's
  identity, so LBD can recognise the same measurement in two places: a UUID version 7 (RFC 9562)
  made at the first save from the time and the operating system's random bits, with nothing to
  set up or coordinate. Saving again to the same file keeps it; **saving to another file gives
  that file a new id**, with `parent_id` naming the one it was made from (`new_id()` /
  `newId()` / `new_id!` does it on purpose). 1.0 files stay valid (they get an id at their next
  save); readers for 1.0 read 1.1 files with a warning. Explore's saved cuts record their
  source's id as `parent_id`.

- **`created` is when the data was created, and saving again keeps it** (every language).
  Before, each save set it to the time of that save, so a file loaded and saved again got a new
  date. Now it can be given (`lbd.Dataset(created=...)`, MATLAB `Created=`, Julia `created=`; a
  datetime or ISO-8601 text), is filled with the time of the first save when not given, and is
  written unchanged afterwards. Files and readers are unchanged (format 1.0).

- The viewer has three workspaces, switched at the top left: **Library** (find files), **Explore**
  (look at data) and **Figure** (what the Data page was: figures, styles, export). Double-clicking
  a data file opens it in Explore now; data files opened from Explorer / Finder too, unless
  **⚙ → Data files … open in → Figure** is chosen. **Styles** and **Language modules** moved to
  the right of the header. Each browser tab keeps the workspace it shows across a reload.

**Viewer**

- **Values bigger than the memory available open**: a value that fits is read whole as before;
  a bigger one is read by part, only the map or curves shown. Parts read are kept while memory
  is free, the next slider positions are read ahead, and LBD always leaves some memory for the
  rest of the computer. ⚙ Settings → *Memory for data*: how much to leave free (automatic: 2 GB
  or 10% of the memory, whichever is more) and an optional most to use.

- **Maps bigger than the memory available open too**: such a map is summarised once (its blocks'
  max, min and mean, made by reading the file strip by strip, with progress and Cancel) and the
  summary is kept on disk, so it opens at once next time. Zooming, panning and the reductions work
  as on any map; clicks, cursors, cuts and max/min/peak read the exact stored numbers from the
  file; the contrast histogram is counted from the summary and says so. Operations and choosing
  rows are refused on such a map, with a message. ⚙ Settings → *Memory for data*: how much disk
  the summaries may take (20 GB; the least recently used go first) and *Empty*. Library previews
  of such maps say to open them in Explore.

- **Files with variable sweeps open** (format 2.0): a value on a group's points is drawn against
  its point number for now, with a notice (drawing against the coordinates comes later); the
  file page names the group, and the Library counts the points ("44 points (variable)").

- **Files being written** (`name.lbd.writing`, from `lbd.Writer` in any language) are listed in
  folders and the Library, marked **measuring…** while their measurement writes them, or
  **stopped before finishing** with a **Recover** button that makes them an `.lbd` file. Explore
  opens them as they are now (with a notice). LBD doesn't save views into them, rename, recycle
  or copy them, and draws no preview until they are finished.

- **Elements and data points** (format 1.2): an axis's elements are shown instead of its numbers
  (tick labels, legends, cursor read-outs, sliders — type an element to choose it — and the
  axes table). A value whose data points are vectors or matrices is drawn as curves against its
  sweep (one per element: Bloch vector x, y, z), not as a map; the Library's sweep size counts
  sweep axes only.
- **Previews in the Library:** the selected file shows a picture of its data, as Explore first
  shows it, and the files near it are drawn ahead, so stepping with the arrow keys shows them at
  once. **Pictures** shows the list as a grid of pictures. Explore's **Library preview** button
  makes the panels as shown the file's picture (kept as a picture; Reset in the Library).
  **⚙ → Library → Previews:** every file drawn in the background (the default; needs the files'
  details read), only the selected file and those near it, or only on request. Drawn in the
  background at low priority, as small WebP pictures kept on this computer.
- **Labels in the Library:** a star, a project, users and tags (all nested, like
  `Qubit A/Device 3`) and a comment, set on one file or many at once (Space stars), filtered
  on the left and searched. Kept in a small label file in each folder: data files are never
  changed for a label, and labels travel with the folder; edits from two computers are merged
  without losing anything, and sync conflict copies are merged and recycled.
- **The same measurement in two places:** identical copies share their labels; files renamed or
  moved outside LBD keep them (labels that lose their file are listed as Missing); copies that
  differ are shown side by side, explained in plain words, and the user chooses: make one a new
  measurement, keep them as the same, or recycle one. **Duplicate as new measurement** makes a
  separate copy without touching the original.

- **Explore**: zoom with the wheel (around the mouse), drag a box, pan with the right or middle
  button, double-click for everything; click a point or cell to read its stored value. Curves or
  maps, the values, axes, one curve per …, complex modes and sliders, typed limits, log scales,
  colour maps (with invert, a log colour scale and a colour range), and a list to choose which
  traces are drawn (in a map, left-out rows stay empty in their place). Drawn by the same engine
  as the figures, so both look alike.
- Large data stays fast and honest: a map with more cells than the screen has pixels shows the
  max, min or mean of the cells under each pixel (chosen above the plot; a single hot cell stays
  visible with max), and curves keep the lowest and highest point of each pixel column, so a
  one-point spike shows. The note above the plot says what is shown.
- **Reading values in Explore**: a click puts a cursor on the nearest stored point or cell
  (Alt: anywhere), Shift+click a second one with differences and means. Crosshair, vertical
  (every trace's value at one x) or horizontal cursors; positions can be typed. **Max**, **Min**
  and **Peak** (farthest from the median: a dip or a spike), between the cursors or in view.
  Beside a map, the row and column through the cursor follow it while you drag. A row, column
  or trace can be shown as a curve or saved as its own `.lbd` file (with where it came from). A
  histogram with draggable limits sets a map's colour range (**Auto** leaves out outliers).
  Keys for all of it; **?** lists every mouse action and key. Clicking the chosen cursor type again
  (or key K) switches cursors off, so a click does nothing.
- **Operations in Explore**: subtract the mean, normalize, derivative, smoothing (running mean,
  Gaussian or median), subtract the first or previous trace, average or std of the traces, FFT
  and histogram, in any order, along the horizontal axis or across the traces (a map's
  background along its other axis). A unit stays where the operation keeps it; otherwise none is
  shown and the label says what was done. Cursors read the shown value and the stored one. An
  operation that can't apply says why. For complex values: electrical delay and rotation, each
  with **Calculate** (from the data between the cursors), auto-rotate each trace, and an I/Q
  histogram (a map of counts). Explore only: never written into the file.
- **Equations in Explore**, as in Labber: `x =`, `y =` (maps also `z =`) after the operations,
  using the other values and axes of the file by name, `pi`, `e`, and functions such as `sqrt`,
  `log10`, `abs` and per-trace `mean`. A legend above the fields says what each name stands for
  and in which unit. Only formulas are read (never run as a program); a field that can't be used
  says why; points without a value become gaps and are counted.
- **Several values at once in Explore** (Labber's log channels are LBD's values): a file with
  several values opens with one panel each (up to four; up to six with **+ Panel**), side by side
  or stacked. Click a panel to make it active: the side panel shows its controls. Panels are
  added, removed, duplicated and moved; a value is dragged onto a panel to join it. Panels with
  the same horizontal axis zoom together, sliders of the same axis move together, and one cursor
  sits at the same x in every panel, with their values listed in the Cursors section (each can be
  switched off). Two values of different units in one panel get a right-hand axis.
- Explore: a narrow plot no longer cuts off its last horizontal tick label, and never shows the
  stand-in tick numbers ("−8.888888") it uses to lay itself out.
- Explore: cursors switched off (key K) or removed (Escape) just as a new picture arrives stay
  off; before, the cursors read for that picture could bring them back, as if the key was lost.
- Explore views remembered before panels open as one panel; a panel that no longer fits a
  changed file is left out with a note, the others stay.
- Nothing in Explore is hidden silently: points a log scale can't show are counted in a note above
  the plot, a log scale with nothing above 0 stays linear and says so, an empty result says why,
  and an unexpected error says it's a bug and where the details are (`viewer.log`, next to LBD's
  database), keeping the last picture.
- Explore remembers, per file, what you showed (plot, chosen traces, operations, colours, scales, zoom, cursors), in
  the viewer's own database on this computer, never in the file. **Forget this view** starts
  afresh. A file that grows while it is shown (a running measurement) keeps the zoom and choices.
- **Library**, like Labber's Log Browser: every data file under your folders as one list (or
  under one folder), with a date tree (year → month → day, from when each file's data was
  created), search inside the files (names, descriptions, values, axes, units, metadata),
  sortable columns (name, date, sweep size; more from the header's menu), the keyboard, and the
  selected file's axes, values, description and metadata on the right; open it in Explore or
  Figure. An index on this computer (`library.sqlite`) keeps it fast with thousands of files and
  up to date by itself; files that can't be read are listed with the reason. For folders in cloud
  storage, **⚙ → Library** can switch off reading each file's details (reading a cloud-only file
  downloads it).
- After the viewer is updated, the browser loads the new viewer page at once (it no longer keeps
  an old copy of the page). The folder panel's right-click menu has **Open in Explore** and **Open in Figure**.

**Plotting (Figure, `lbd.plot`)**

- Curves can use a value as the horizontal axis (one with the same axes as the plotted value):
  each trace is drawn at its own x, e.g. a frequency span that changes with power.
- Complex modes `phase_unwrap` and `phase_deg_unwrap`: the phase without its 2π jumps along the
  horizontal axis (missing points are skipped).
- New module `lbd.plot.reduce`: reduce maps and curves to a screen's pixels without losing peaks.
- Choosing the saved "one curve per" axis (or a map's vertical axis) as the horizontal axis swaps
  the two, instead of warning that the saved view can't be used.

**File format and languages**

- **`lbd.open`: read only what is needed** (every language). `with lbd.open("big.lbd") as d:`
  reads the structure; each value's `data` is an on-disk array: `d.values["S21"].data[3]` reads
  row 3 only, `np.asarray(...)` all of it, and `rows`, `coords`, `to_dense` read only what they
  need. In MATLAB: `d = lbd.open("big.lbd", Mode="r")`, `d.Values.S21.Data(4, :)` reads row 4
  only (`Data` is an `lbd.OnDisk`), `d.close()`. In Julia: `LBD.open("big.lbd"; mode="r") do d …
  end`, `d["S21"].data[4, :]` reads row 4 only (`data` is an `LBD.OnDisk`, an `AbstractArray`).
  `mode="r"` (default) only reads; `mode="r+"` writes into the file at points that exist and
  saves (in place, or a copy piece by piece). A file being written opens too, as it was at that
  moment.

- **Variable sweeps** (every language, format 2.0): make a group and its axes, outer to inner,
  and values on its points; `write` takes a group axis's coordinate (the same coordinates are
  the same point, found or added; a new point that differs from one there only by rounding is
  warned about) or the outer point's index, which `write` returns. Reading: each point's
  coordinates, the value row by row (each row a dataset), and the full rectangle (gaps `NaN`;
  merging coordinates that differ only by rounding on request; a size limit). The Writer does
  the same while measuring, each level growing in the file.
  - Python: `d.add_group("scan")`, `add_axis(name, group="scan")`, `i = d.write(A=3)`,
    `d.write(parent=i, B=25, f=x)`; `v.coords()`, `v.rows(by="A")`,
    `v.to_dense(round=, rtol=, atol=, limit=)` (also `d.coords("f")` …).
  - MATLAB: `d.addGroup`, `d.addAxis(name, [], Group=)`, `i = d.write(A=3)`,
    `d.write(Parent=i, B=25, f=x)` (indices from 1); `d.coords("f")`, `d.rows("f", By="A")` (a cell
    `{key, dataset}`), `d.toDense("f", Round=, RTol=, ATol=, Limit=)`.
  - Julia: `add_group!`, `add_axis!(d, name; group=)`, `i = write!(d; A=3)`,
    `write!(d; parent=i, B=25, f=x)` (indices from 1); `coords(d, "f")`, `rows(d, "f"; by="A")`
    (`key => dataset`), `to_dense(d, "f"; round=, rtol=, atol=, limit=)`.

- Reading a file being written no longer fails now and then at the moment its writer finishes it
  (every language): the writer rewrites the description and metadata then, and the reader reads again
  a moment later, or says the file was finished.

- **File format 1.2: elements and the shape of a data point** (every language). An axis's
  positions can have names: `add_axis("state", elements=["ground", "excited"])` (numbered 0, 1
  by itself). A value's data point can be a vector or a matrix, said like numpy:
  `add_value("bloch", b, axes="amp", shape=(3,), elements=["x", "y", "z"])` — the data's
  dimensions are the value's axes first, then the data point's; LBD makes an axis for each
  dimension of the data point (`bloch_dim1`, marked `role="point"`), so earlier readers still
  read these files. Data with more dimensions than axes needs `shape=` (a clear error says so).
  1.1 files stay valid; readers for 1.1 read 1.2 files with a warning.

- **Filling a file piece by piece** (every language): `add_value("S21", axes=["power", "freq"],
  dtype="complex128")` without data makes a value that is "not measured yet" (`NaN`; for
  integers and booleans a `measured` mask, saved as `/measured/<value>` when something is
  missing), and `d.write(power=i, S21=trace)` puts a point, a trace or a whole map in its place —
  fixed axes by index or element, several values at once. `add_axis("time", grows=True)` makes
  an axis of unknown length whose points `write` adds (`d.write(time=t, T=x)`). In MATLAB:
  `d.addValue("S21", [], ["power" "freq"], Dtype="complex128")`, `d.write(power=i, S21=trace)`
  (indices count from 1), `d.addAxis("time", [], Grows=true)`. In Julia:
  `add_value!(d, "S21"; axes=["power", "freq"], dtype=ComplexF64)`, `write!(d; power=i, S21=trace)`
  (from 1), `add_axis!(d, "time"; grows=true)`.

- **Writing while measuring** (every language): `lbd.Writer("rabi.lbd")` takes the same calls
  (`add_axis`, `add_value`, `write`) and writes `rabi.lbd.writing` as the data comes, so the
  data so far can be read at any time (`lbd.load` reads such a file, with a warning); when the
  measurement ends (`close()`, or leaving the `with` block) it becomes `rabi.lbd`. A crash or an
  error leaves the `.writing` file with everything written up to then: `lbd.writing_status`
  tells "measuring" from "stopped", and `lbd.recover` makes a stopped one an `.lbd` file. Other
  programs opening it while it is written are refused without disturbing the measurement.
  Saving at the end with `Dataset.save` is unchanged. In MATLAB: `w = lbd.Writer("rabi.lbd")`
  … `w.close()`, with `w.abort()` on an error; `lbd.writingStatus`, `lbd.recover`. In Julia:
  `lbd_writer("rabi.lbd") do w … end`; `writing_status`, `recover`.

**Documentation**

- **Variable sweeps**: *Concepts* explains axis groups (sweep axes, dimensions, data points) and
  **Grid or group?**, the pros and cons of each; the Python, MATLAB and Julia pages show building,
  writing (by coordinates and by the outer point), `to_dense`, `rows` and `coords`; *Writing
  while measuring* shows a variable sweep written live. `viewer/tests/mock_values.py` writes a
  variable sweep, a triangle and an adaptive map.

- A new page, **Writing while measuring** (Getting started): the Writer in every language, what
  `write` takes, growing axes, points not measured, what other programs see, and Recover.
  `viewer/tests/mock_live.py` writes a file slowly (and leaves a stopped one) to try the viewer.

**For developers**

- `scripts/test_all.py` runs the suites side by side (`--jobs`, default 4), the longest first:
  a whole run takes about as long as the browser tests instead of the sum of all. `--changed
  [REF]` runs only the suites the changed files can affect, `--only` names suites. Viewer and
  browser tests that fail side by side run again alone, and the summary says so.

## 1.2.0 (2026-10-28)

**Changes to how things behave** (read these when upgrading)

- A file written again while the viewer shows it (e.g. by a simulation you run over and over)
  updates by itself within about two seconds. Unsaved plot settings of its tab are dropped,
  with a message, since they were made for the data before; save a view into the file to keep
  it across runs.

**Viewer**

- Files that change on disk: open tabs (data, images, style files) show the new version; the
  Folders panel shows new and deleted files without ⟳. A file that is gone, or still being
  written, stays shown as it was, with a note, until it can be read again. The viewer only
  reads sizes and times to notice changes, and doesn't check while its browser tab is in the
  background.
- The tab row: right-click on its empty part, or the new **⋯** button at its end (always in
  reach, however many tabs are open), for **Close all** and **Move all tabs to Page N / a new
  browser tab**. A tab's menu also has these, plus **Show in Explorer**, **Copy path** and
  **Rename…** for its file. Right-click on a file's name above its plot opens its tab's menu.

**File format and languages**

- Saving on Windows waits up to 3 seconds when another program (e.g. LBD Viewer reading the
  previous version) has the file open, then fails with a message naming the file. Every
  language module alike.

**Documentation**

- The documentation is online at [patrick-csliu.github.io/lbd](https://patrick-csliu.github.io/lbd/),
  for the latest release: it is published from the release's tag each time a release is
  published (`.github/workflows/docs.yml`).

**For developers**

- Between releases every component says `X.Y.Z-dev` (Python `1.2.0.dev0`, npm `1.2.0-dev.0`),
  so a build from the repository is never mistaken for a release. `bump_version.py 1.2.0 --dev`
  starts it, `bump_version.py 1.2.0` releases it; the Release workflow refuses a development
  version. The viewer shows `1.2.0-dev`.

## 1.1.0 (2026-10-17)

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
- Windows: renaming a file, or moving it to the Recycle Bin, failed if the file was open at that
  moment, even briefly (the viewer drawing it in another page, an antivirus scan). The viewer
  now waits a few seconds for it, and otherwise says the file is open in another program.

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
