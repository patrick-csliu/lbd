# Changelog

All components (the viewer and every language module) share one version number.
The file format has its own version (`lbd_version`, currently 2.1; a file is written with the
lowest version its content needs: 1.2 for most files, 1.3 with labels, 2.0 with an axis group).

## 2.0.0 (2026-11-16)

**Changes to how things behave** (read these when upgrading)

- **A Library preview stays when its file changes.** It is no longer drawn again when data is
  added: right-click → **Update preview** draws it again (it asks first for a picture chosen in
  Explore). An automatic preview is now **one panel**: the plot saved in the file (Save view,
  `lbd.set_plot`) when it has one, else its first value that isn't a single number (before: up to
  four values side by side, ignoring the saved plot). Several panels come only from Explore's
  **Use as Library picture**, now with a thin frame around each and a gap between them. A file
  being measured shows **Live** in place of its preview. Pictures drawn before are kept as they are.
- **Explore's numbers get a unit prefix by the plots' rule.** Only a unit on the plots' list
  (`Hz s V A W Ω Ohm F H T K m g J C S Pa N eV Wb`, compared whole) gets a prefix; every other
  unit is shown as stored. Before, the cursor read-outs and tables put a prefix on almost any
  unit: 0.75 mm read "750 mmm", 5000 kHz "5 kkHz", 1500 counts "1.5 kcounts". Now K gets one
  (2 mK), as on the plots; rad, ppm and V*s no longer do. Very large or small numbers of a unit
  without a prefix are written as 2e−7 V/cm.
- **A value on two levels of an axis group opens as a map**, no longer against its point number.
- **The Library's dates are in one time zone.** Date, the pictures and the Files sidebar show every
  file's time in this computer's time zone, so they can be compared; before, each date was as
  written in its file, with the file's zone when it differed. **Settings → Library → Show dates
  in** chooses another zone or **As written in the file**, and a date's tooltip gives the other
  form. A file's Created line, the date tree and the date filter stay as written.
- **Saving asks where, with the system's Save dialog** (Explore's Save as CSV and Save picture as
  PNG; before: always next to the data file, or the browser's Downloads). Save as CSV has two
  steps: the choices, then **Next** shows the size, the columns and any warnings before **Save…**.
  **Every save writes one file**: "all panels" holds the panels with the same axes, the others are
  left out and named (before: one file per set of axes).

- **CSV files always have the units stored in the file** (Hz, not GHz). Save as CSV no longer
  has a Units choice, and `lbd.plot.table` no longer takes `units=`: a script still passing it
  gets an error saying to remove it. Each choice of the Save as CSV dialog says what it does when
  you point at it.

- **A save never loses the measurement** (every language). Metadata, the saved view, the style
  and `created` are checked when they are set, so a mistake shows before measuring. Python and
  Julia: a setting that still can't be stored (changed by hand afterwards) is left out with a
  warning, everything else is saved, and its text is kept in the file's `/extra/not_saved`;
  data that can't make a valid file is kept as it is in `name.lbd.rescue`, which `recover`
  reads back. `check()` (Python `d.check()`, MATLAB `d.check()`, Julia `LBD.check(d)`) lists
  what a save would refuse, and a dry run (`dry_run=True`, `DryRun=true`) checks the folder too,
  writing nothing. Python's `d.save` returns the path with `left_out`.

- **The Library writes labels into the data files.** A star, project, users, tags or comment
  set in the Library is written into the `.lbd` file about 2 s after the last edit (and before
  the viewer closes), so labels go with a file that is copied or moved. Labels already given
  are written in once, in the background. Labels a script wrote into a file show in the Library;
  label by label, the newer change wins. A file that can't be changed now (being measured,
  read-only, open elsewhere) gets them later, and the Library says why they aren't in it yet. Only
  the computer that made a change writes it, so two computers on one synced folder never both
  write a file. Copies of one measurement are compared by their data, so different labels don't
  make them "copies that differ". The label file stays, and keeps an entry whose labels were all
  removed (the removal counts).

- **Settings → Library → Edit data files: In place or Copy and swap.** Every change LBD makes
  to a finished data file (giving it an id, New measurement, Save view, its labels) follows it.
  In place (the default) takes about 10 ms at any size. Copy and swap writes a complete copy and
  puts it in the file's place, so even a power cut can't damage the file; it needs room on the
  disk for the copy (and says so if there isn't any) and takes about 1 s per GB.

- **Labels in the data file** (file format 1.3 / 2.1, spec §1.9). A file can hold its labels:
  star, project, users, tags and comment, so they go wherever the file is copied or moved.
  Python: `d.labels` (`d.labels.star = True`, `d.add_tags("calibration")`, or a dict), also on
  `lbd.Writer`; `lbd.set_labels`, `lbd.remove_labels` and `lbd.labels` for an existing file,
  without loading or rewriting its data. MATLAB: `d.Labels` (a struct), `d.addTags`,
  `lbd.setLabels`, `lbd.removeLabels`, `lbd.labels`. Julia: `d.labels`, `add_tags!`,
  `LBD.set_labels`, `LBD.remove_labels`, `LBD.labels`. Each label is checked when it is set.
  Every language keeps a file's labels when it saves it again. A file with labels is written as
  format 1.3 (2.1 with an axis group); older LBD reads it and ignores the labels.

- **File format 2.0: variable sweeps** (axis groups, spec §1.8; every language). A sweep whose
  inner points depend on the outer ones (frequencies chosen per power, a different number of
  points per row, adaptive points) is stored as an axis group: only the measured points, level
  by level. Writers write 2.0 only for a file with an axis group; **every other file is still
  written as 1.2**, so older LBD keeps reading it. **LBD older than 2.0 can't open file format 2.0 files**
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

- **The Folders panel of Explore and Figure is now the Files sidebar.** It lists the Library's
  files with this browser tab's filters (folder, date, search, labels): narrow them down in the
  Library, then step through them with ↑ ↓ in Explore or Figure. Its search narrows only the
  sidebar; **Edit ↗** goes to the Library. The folder tree is still there as a list to switch on
  (**⚙ → Files sidebar → Folders**; in Figure with images and style files, in Explore with data
  files only), with **Starred** and **Recent**. Folders are added and removed in the Library
  only (**Filters → + Add folder**). The sidebar's toggle is ◧‹ inside it and ◧› at the left
  of the tab row. **⋯** next to its search shows each file on **two lines** (the default: the
  fields you tick on a second line), **one line**, or as **columns** that sort the sidebar only,
  with column widths dragged and kept; the name is the title or the file name.

- **The installers refuse an older version.** On Windows and Linux, installing a version older
  than the one installed stops with a message: to go back, uninstall first, then install the
  older one (settings and Library are kept). On macOS, an older app started after a newer one
  says so once, and carries on. Settings that only a newer version knows are now kept when an
  older one saves its settings.

**Viewer**

- **Values & axes of a variable sweep say what they are.** A value shows its real axes (A, B,
  not only B) and its shape in steps ("40 steps × 1–40 (820 points)"); the inner axis counts its
  points per step ("1–40 per step (820 in all)"), its From and To are its real values over the
  file, and a short note says what it depends on ("variable sweep: depends on A"). Before, the
  inner axis showed its total like a number of steps, and a note about point numbers that is no
  longer true.
- **Curves of a variable sweep use its real axes** (Explore, Figure, `lp.plot`, CSV). Against
  the inner coordinate (Frequency chosen per Power) there is one curve per outer step, each with
  its own points; against the outer axis, one curve per position in a step ("point 3 of each
  step"); the position inside a step is last in Horizontal. A value with one number per step (Q
  per power) joins with Power horizontal, and says why it can't against Frequency. Before, these
  curves were drawn against the point number. Groups of three levels still are, with a note.
- **Clearer section titles in Values & axes** (Explore's inspector at the right or below, the
  Library, the Figure page). Values, Axes and Metadata are a little larger, in the text colour,
  with a line under them and more space above each section; in the narrow list at the right the
  names are no longer bold and the lines between them are lighter, so the sections stand out.
- **New files appear in the Library in about a second**, told by the system's notifications,
  no longer by looking through every open folder every 3 seconds (60 when the Library isn't
  shown). Every folder is still looked through at start and every 7 minutes, in case a notice was
  lost. A folder on a network drive is looked through every 60 seconds instead, and one where
  notifications can't be had every 10 seconds; the status line says how the folders are watched
  (point at it for each folder and why).
- **Check folders now** in the Library (next to the search box) looks through the open folders
  at once, for a file that should be listed but isn't yet. It says what it found ("3 new files",
  "Nothing new", changed, moved and gone files) and names every folder it couldn't read, with why.
- **Row as curve and Save row on a variable sweep's map** (Explore, drawn as Rows). The row
  through the cursor is its step: shown as a curve against the real inner coordinate, or saved
  (.lbd and CSV) with that step's stored points; a column is the cursor's place in each step,
  against the outer axis. Drawn as nearest points or smooth, they stay greyed, now with a tip
  saying why; the plot's right-click menu greys them the same way (before, it didn't).
- **Equal axes no longer starts on for the I/Q plane.** Tick it under Display. It now counts
  stored units, so a circle stays a circle when the two axes show other prefixes.
- **Grid and Equal axes on Curves and Scatter** (Display, Explore and Figure; `options.grid`,
  `options.equal` in `lp.plot`). Grid starts as the style says and can be turned on or off per
  plot. With Sync x, a panel with Equal axes widens only its own view.
- **Operations per plot type, and three on Scatter** (Explore). Each plot type lists only the
  operations it offers: Curves and Map all; Matrix, Bars and 3D bars Subtract the mean and
  Normalize (before: also Derivative, Smooth, Subtract the first and previous trace); Histogram
  the complex ones, Subtract the mean, Normalize, Derivative and Smooth; Scatter now Rotation,
  Auto-rotate (on the I/Q plane) and Subtract the mean. An operation a type doesn't offer, from a
  view made on another type, is left out with a note instead of an error.
- **A scatter plot too large to hold can be saved as CSV** (Explore): its points are read from
  the file part by part while the file is written, with progress and Cancel. Before, it was
  refused.
- **Legend dots are big enough to see their colour**, whatever the size of the plotted points (a
  scatter plot of small points, the strips beside it, curves with points): at least 6 pt.
- **A new page starts on the Library**, not on an empty Explore. A page opened for a file still
  starts on that file, and a reload stays where it was. Going to Explore or Figure with nothing
  open there shows the Files bar (in a narrow window, its drawer), even if it was hidden.
- **Explore opens a new file with its first value**, not four panels: **Settings → Explore →
  Panels for a new file** chooses first value only, at most 2 … 5, or all (up to six). **+ Panel →
  Open all** adds the values not shown, and a panel's menu has **Move left** and **Move right**.
- **A file opened again in Explore keeps what you choose.** **Settings → Explore → Kept when a
  file is opened again**: by default panels, plot, traces, colours and scales, colour limits and
  sliders come back; operations and equations, zoom, sync and cursor options start afresh
  (before, everything came back, cursors too). Cursor positions always start afresh; a kept zoom
  is not used once the file changed. **Forget this view** is now **Reset all**.
- **The first start asks what matters for your data**: your folders; for each, whether it is on this
  computer only, synced with other computers, or in the cloud with files kept online only (which
  turns off reading each file's details); for a synced folder, how data files are edited (in place
  or copy and swap, both explained); which previews the Library draws (every file reads every
  file); and whether to check online for new versions. It asks until
  answered. After an upgrade only the last question is asked. It replaces the Library's notice about
  cloud folders. Each question starts with its first answer chosen; a folder added by mistake can be
  removed; nothing is saved, and no folder is read, until **Start**.
- **A fast measurement's status line no longer shows "0 of 50 points"** next to "60 %": the
  count, rounded to the measurement's pace, now keeps at least its leading digit.
- **Dates and times are written one way everywhere** (2026-03-14 23:30), also when the browser is
  set to another language: the Library's "Drawn on", a measurement's status line, "Updated" after a
  change on disk and Settings → About were written in the browser's language (e.g. "2026年11月13日
  下午5:46" in English text).
- **A question asked while the last one's change was still being made** (two settings changed
  quickly) could keep its button greyed out, or close by itself; it now starts afresh.
- **The check for new versions can be turned off** (Settings → About → Check for new versions
  online), and it runs only when allowed: asked at the first start, not before.
- **Settings that change a lot ask first** and say what will happen: how data files are edited, reading
  each file's details, previews of every file, less room for summaries than they take, and emptying
  the picture cache or the summaries. A reset names those it would switch; a risky memory limit is
  warned about under its field.
- **Settings → Explore → Reset this section** puts the Explore settings back; it did nothing.
- **Settings → Explore → New plots start with**: Grid on Curves, Show points on Curves, Grid on
  Scatter, each on its own. On: a new plot in Explore starts with it; off: as before (Grid as the
  style says). A tick under Display still changes one plot; the Figure page is not affected.
- **A cursor shows in its colour on a dark Scatter, Histogram or Bars picture** (dark theme). Its
  edge was white and wider than its red line, so the cursor looked white.
- **Project, Users and Tags line up with "Starred only"** in the Library's Labels, instead of
  looking like items inside it.
- **A label change no longer makes others wait on a busy computer.** The first change in a
  program loaded the plotting code while it held the folder's labels lock; on a busy computer that
  took seconds, and other programs changing the same folder's labels could give up after 15 s.
- **A Labels tab in Explore** (the inspector, or the tag button beside ⓘ): the file's star,
  project, users, tags and comment, edited as in the Library, which shows a change at once. The
  inspector's tabs wrap rather than being cut in a narrow panel, and a label picker stays inside
  the window.
- **Look options are under Display.** Data says what is plotted, Display how it looks: a
  histogram's Bins, Draw and Vertical axis; Scatter's Equal axes and Histograms beside the plot;
  a map's Cells; a matrix's Numbers, Significant digits, Row sums and Colour range; Bars' Bars and
  Values on the bars; 3D bars' angle. The Figure page has a Display section for them too.
  Histogram's second log switch (**Log**, the same as **Log vertical**) is gone.
- **All of an axis on Bars** (Explore, Figure, `lp.plot`). An axis that isn't Groups or Bars in a
  group can be **All** instead of a slider, as on Histogram and Scatter: each bar then stands for
  all its numbers, and **Bar shows** chooses Mean (the default), Median, Max, Min or Sum; empty
  points are left out, and the vertical axis says which ("Mean of |S21|"). **Error bars** (under
  Display, off at first) draw one standard deviation on each bar. In `lp.plot`: `all=[...]`,
  `options={"stat": "median", "errors": True}`.
- **Show points on curves** (Display, Explore and Figure; `options={"points": True}` in
  `lp.plot`). A small dot on the stored points, off by default; Open in Figure keeps it. Explore
  draws one stored point per pixel that holds points, at every zoom: dots in one pixel would cover
  each other, so it looks the same, and a one-point spike keeps its dot. Where a curve has more
  than two points per pixel column the dots shrink to the line's width; with more than 1.5
  million points in view they are left out, with a note.
- **No value is locked in Curves** (Explore). A value on another axis, or with a third unit, used
  to be greyed out, and with one value ticked nothing could be changed; now clicking it shows it in
  that panel instead (its tip says so), as Histogram and Scatter already did.
- **Fixed: a right-hand axis squashed its curves** (Explore, two units in one panel). On a linear
  vertical scale each side now fills the height with its own range (temperatures beside a
  pressure no longer use 2 % of it); on **Log vertical** the middles of the two ranges line up as
  before. **Fixed:** two units in one Explore panel no longer show a red "the vertical axis shows
  no unit": each has its own axis there (the Figure page, with one axis, still says so in its
  notes).
- **A slider no longer moves the plot** (Explore, curves and scatter). While a slider steps
  through a measurement, the unit prefix, the plot's size and (until you zoom) its limits stay the
  same at every step, so the steps can be compared; before, a step could change the unit (mV to V)
  and leave the old limits, showing the points as a dot, and Equal axes widened the view a little
  more at each step.
- **Fixed: the Display controls jumped while a measurement grew** (a map's colour range shrank
  for a moment each time the file was read again).

- **A plot's layout depends only on its panel's size** (Explore). Two panels of one size have
  plots of one size, whatever came before (the window resized, F12 opened and closed, another
  value or slider step), and a colour bar is never pushed out of the picture. The margins are
  worked out from the style's font sizes; a label too long for its room ends in "…" instead of
  being cut off.

- **Fixed: a red "This file can't be read" when a measurement finished** while it was selected in
  the Library. The selection now follows the finished file, as open tabs do; a file that is
  briefly gone (renamed, moved) says so plainly instead of being called a bad file.

- **Fixed: a red "This plot can't be shown" after leaving Explore idle.** The server closes a view
  unused for 10 minutes; the first click, key, zoom, cursor, Peak or size change after that opened
  it again but showed an error on every panel. Now the view opens again quietly ("Drawing…"), the
  request is done on it, and several requests share one reopening.

- **LBD tells you when a new version is out.** At most once a day, when the viewer starts, it
  asks GitHub for the latest release (5 s at most, in the background, sending only the program's
  name and version; quiet without internet). **Settings → About** shows *"LBD X is available"*
  with its release page, the install command and **Check now**. On the first start of a day with
  a newer version, one page shows a reminder: Remind later, Install… (Settings → About) or Never
  remind (this version only). LBD never downloads or installs anything by itself. `--dev` skips
  the check.

- **Install with one command**, on every system: `install.ps1` (Windows, PowerShell),
  `install.sh` (Linux) and `install-macos.sh` (macOS) come with each release. Each downloads the
  latest release's installer, checks its SHA-256 checksum against the release's new
  `SHA256SUMS` file, and runs it (on macOS: copies the app to Applications). The commands are
  in the README and *Install*. The Linux package's `install.sh` takes `--desktop`, `--no-desktop`,
  `--menu` and `--no-menu` to answer its shortcut questions.

- **The installers stop a running viewer gently** before replacing it: `lbd-view --stop` asks
  the viewer to stop (labels still waiting are written into their files first) and waits up to
  10 s; only then is it stopped by force. The Linux install keeps `uninstall.sh` next to the
  app (`~/.local/share/lbd-viewer/uninstall.sh`).

- **Fixed: changing the plot type while a picture was drawn** (for example a map to Scatter on a busy
  computer) could show "This plot can't be shown". Each Explore view now finishes one change before
  the next step reads it.
- **Fixed: Settings broke after "Another time zone"** (Library → Show dates in). The time zone list
  stood beside the first one and squeezed the setting's name and help into a strip of single
  letters, with the list at the window's edge. It now goes under the first list, and every
  setting's name and help keep a minimum width.
- **Fixed: label changes refused on a busy computer.** When several programs change labels in one
  folder, a change now waits its turn for up to 15 s (before: 3 s), and the Library shows
  "Saving labels…" while it waits. A change that is refused in the end is shown as an error that
  says it was not made, and why. A program that works long keeps its lock fresh, so it is never
  mistaken for one that crashed, and a lock left behind is recognised by its time not changing,
  so clocks that differ between computers no longer matter.

- **Ctrl+C stops the viewer within a second or two**, and it prints one line, "LBD viewer
  stopped", not error text (before: 8 to 15 s with a page open, and three `Traceback` blocks). A
  save in progress finishes first, and labels still waiting are written into their files.
- **The viewer stays up under an open page after the computer slept.** On waking, the open
  pages get 15 seconds to say they are there before the viewer counts them as closed; before, it
  could stop at once, as the sleep counted as time without a page.
- **A preview worker no longer stays behind** when the viewer is killed or crashes: it stops by
  itself within a few seconds (before, it kept running, holding memory and keeping files open).

- **⚙ Settings are a dialog with sections** (General, Library, Files sidebar, Memory,
  Measurements) instead of one long menu: each setting with its name, a line about it and its
  control (switches, choices side by side); **Find a setting…**; a dot on a section that was
  changed and **Reset this section…**; Esc or a click beside it closes it (moving the mouse away
  no longer does). `#settings/memory` in the address opens a section.
- **Library: removing a folder asks first.** The **×** on the folders is gone (it moved the
  counts); right-click a folder or its **⋯** → **Remove from the Library…** says how many files
  leave the Library, how many have labels, the labels only they have, and open tabs showing
  them. Nothing on disk changes. The same menu shows the folder in Explorer / Finder and copies
  its path.
- **Explore: files open on a computer short of memory.** With little memory free (other
  programs open), small files were refused ("small enough to show without a summary", "show one
  value at a time"), and the equations' list of names was empty. Now a value under 64 MB is
  always read whole, **Leave free** is 0 unless set (the automatic 2 GB / 10 % reserve is gone; a
  number you set is kept), and a plot summarised only for lack of free memory says so once.
- **Explore: a steady tab bar.** It is 30 px high with or without files (it grew by 34 px when
  the first file opened); right-click on its empty part lists the tabs and has **Close all**.
  The copy icon sits right after the file's path.
- **Explore: resizable columns.** Drag the inner edge of the controls or of the inspector (on
  the right, or the strip below) to resize it; double-click it for the default size.
- **Explore: a map's axes as one block.** Horizontal and vertical are two drop-downs of the same
  width, with the swap button ⇅ beside both; curves keep the horizontal one in the same place.
- **Explore: a cursors sync, and syncs that line up at once.** A fourth chip, **cursors**, shares
  the cursors between panels with the same horizontal axis; **x** and **y** now only zoom and pan
  together (a view saved before keeps sharing its cursors as its x did). Turning a chip on lines
  the panels up with the active one at once, not only from the next zoom.
- **Explore: Names and functions** is a short table: the names and what they stand for, the
  functions in groups, examples; a click puts one into the equation field used last.
- **Explore: the cursors.** Cursor 2 has a **×**; **Remove** is now **Remove cursors**, beside the
  cursor types (with Undo), apart from **Move cursor 1 to the Max / Min / Peak**. The line under
  a panel's title has a row per cursor (nothing cut off in a usual panel; the whole text when you
  point at it), "Click the plot …" shows only in the active panel, the inspector's numbers wrap
  to its width, and a mean that is zero up to rounding reads 0 (not 2.8e−17).
- **CSV files name the measurement's id** (Save as CSV, `lbd.plot.table`): `# id: …` (and
  `# made from: …`) in the comments, so a CSV found later can be traced back to its `.lbd` file.
- **Library: find a file by its id.** Paste an id, its start, or the `# id: …` line of a CSV into
  the search box: the file, its copies and the files made from it. A file's details show its id
  with a copy button.
- **The whole file as CSV.** Save as CSV's **How much → the whole file** (also in the file's **⋯**
  menu and the Library's right-click menu) saves every point as stored, for any number of axes:
  you choose one group of values on the same axes, a file bigger than memory is read part by
  part. For scripts: `lbd.plot.groups(d)` and `lbd.plot.table(d, group="S21")`.
- **Explore: a row, column or trace as CSV.** The Cursors tab's buttons save the line through
  cursor 1 as CSV, for this panel or all panels with the same cut (one file, a column each). The
  `.lbd` cut is in the plot's right-click menu, and asks where with the Save dialog too.
- **Explore: the sync toggles are explained**: their tooltips say what each links and between
  which panels (sliders: what a slider is), and *Explore → Sync* in the Help has examples.
- **Explore: Values & axes as a list.** In the narrow side panel each value and axis is a small
  block of lines, so nothing needs sideways scrolling (a wide panel keeps the tables).
- **Library: labels look like what they are.** Project, Users and Tags sit indented under **Labels**,
  without lines between them; they looked like sections of their own.
- **Library: the label pop-out stays inside the pane.** It moves left at the window's edge; it went
  past it, and the right pane scrolled sideways.
- **Files tab: sort by name or date**, with two buttons in every layout (Explore and Figure); only
  the Columns layout could sort before. It never changes the Library's order.
- **Library: a more useful Pictures view.** **Name** and **Date** sort the pictures (one order with
  the list), and **⋯** chooses what each picture shows: its title or file name, and any of the
  fields, such as sweep size, project or tags.
- **The version is in Settings → About**, no longer in the header.
- **Explore: two cursors, both cuts.** With two cursors, the cuts beside a map show two curves in the
  cursors' colours, on one scale.
- **Explore: move two cursors together.** The tick box **Move both cursors together** in the Cursors
  tab: dragging either cursor, or the arrow keys, moves both by the same amount, each on its own
  trace, and both stop at the data's edge, so the distance between them stays.
- **Explore: the Cuts button changes the plot in one go.** The strips, the plot and the picture change
  together when the new picture is here; before, the strips went first and the picture followed
  half a second later.
- **Variable sweeps are maps.** A value on two levels of an axis group draws with its real coordinates,
  in Explore, on the Figure page and from scripts: as **Rows** (each stored point owns a cell, nothing
  is drawn where nothing was measured) or **Nearest point** for scattered points, or **Smooth** when
  asked for. Cursors read the stored points, rows have cuts, Save as CSV gives every point.

- **Open in Figure** takes a plot type of its own along with its choices.
- New plot type **Bars**, in Explore and Figure: bars with labels, grouped or stacked, for short axes, a vector in each data point, several values, or several single numbers. Two units get a second vertical axis. A click reads a bar; a horizontal cursor is a level to compare them with.
- New plot type **Matrix**, in Explore and Figure: cells with their numbers, for two axes or a matrix in each data point. A click reads a cell; complex values show Re and Im side by side; the colour range can be fixed to 0 to 1 or −1 to 1.

- New plot type **3D bars**, in Explore and Figure, for the data of Matrix: a bar per cell, up to 64 × 64. Complex values show Re and Im side by side on one scale, or height the magnitude and colour the phase. In Explore a drag turns the picture, the wheel zooms, the arrow keys turn, and a click reads a bar; on the Figure page the angle is in boxes.

- **A new plot type: Histogram, in Explore and Figure.** It counts how many numbers fall in each bin.
  Each axis is a slider or All, one axis can give an outline per step (**Colour by**), and values of one
  unit are overlaid. Bins Auto or a number, Bars or Outline, Count, Fraction or Density, linear or log.
  Complex values are counted after the complex choice, and operations and equations come first. Large
  files are counted part by part in the background, the bars growing. A cursor reads a bin's range and
  counts; two cursors the count and fraction between them. Save as CSV and Open in Figure take it along.
  The bars' opacity and the outlines' width are in the style.

- **Explore: scatter plots.** A marker per point: an axis against a value, a value against a value, or the
  I/Q plane. **Colour by** gives one axis's steps a colour each, every other axis is a slider or All, and
  **Equal axes** keeps circles round. Above 200 000 points each pixel shows how many points are there, none
  dropped, and a file larger than memory is counted part by part. A cursor chooses the nearest point on
  the screen and reads its stored index; two cursors give the difference and mean.
- **Explore: histograms beside a scatter plot.** The strips show histograms of the points in view, per group,
  with the button **Histograms** or key C.
- **Figure: scatter plots** have the same **Colour by** and a slider or All per axis, and an option
  **Histograms beside the plot**.
- **Changes to how things behave:** a file whose saved view is a scatter plot now opens as one in Explore,
  instead of offering Figure or curves. A saved scatter view keeps drawing all its points in Figure.

- **Explore: the preview tab's name** (one click, in italics) is at the same height as the other
  tabs' names; it took the Library preview's margins before.
- **Explore: a map's colours can mean the same at every slider position.** Display → Colour →
  **Colour range over: All slices** (the default for new panels) takes the colour range from
  every slider position (complex mode, operations and equations applied), worked out once in the
  background; **This slice** keeps each position's own range, as before (and for panels set up
  before). The Contrast histogram counts the same values.
- **Explore: every trace at a cursor line.** On curves, a vertical or horizontal cursor marks where
  it meets each visible trace and lists the numbers in a table under the cursors, one line per
  trace in the file's order, the cursors' traces marked: a vertical cursor
  each trace's value (with two cursors both and Δ), a horizontal cursor every crossing and, for
  two, the distance between them. **Interpolated** (default) or **Nearest stored point**; **Copy**
  and **Save as CSV…**; a tick box turns it off, and **Settings → Explore** sets how many traces
  it marks at most (20).
- **Explore: cursors show on any map.** Their lines, circles and numbers have a white edge (a blue
  cursor on a blue map was lost), the numbers are small badges that keep apart when two cursors
  are close, and share one badge at the same point.
- **Explore: a new equation shows that axis whole.** Changing the x (or y) equation, or an
  operation that changes what an axis measures (FFT, d/dx, normalize), shows all of that axis and
  keeps the other's zoom; the cursors, at the old numbers, are removed; a new z equation clears
  typed colour limits. Before, the plot kept the old limits and showed an empty or tiny part.
- **Explore: Max, Min and Peak on one line.** "Move cursor 1 to: Max Min Peak" fits the
  inspector's default width; a narrower inspector puts the three buttons together on the next line.
- **Explore: plainer pixel note**: "average of 5×8 cells per pixel" (was "mean of …"), "lowest
  and highest point per pixel column"; its tooltip says what it means and where to change it.
- **Explore is a workbench that fills the window.** The controls, the plots and a new
  inspector each scroll on their own, so the page never scrolls and changing a control or reading
  a cursor never moves the plot. The controls fold into **Data**, **Display** and **Processing**;
  the inspector has **Cursors**, **Values & axes** (the file's tables and facts) and **Metadata**
  (with its filter). Every panel has a one-line read-out of its cursors under its title. In
  narrower windows the inspector becomes a strip under the plots and the controls a drawer
  (**⚙** in the panel bar); panels too narrow side by side are stacked for that size only.
- **Explore: icon buttons.** A panel's toolbar is one row: ⟲ Reset view, ⇔ Limits (a popover),
  ✂ Cuts, ⤓ Data, ⋯; the layout is ▥ ▤, the syncs are toggle chips. Each has its name and key in
  its tooltip. The header is one line: the path (shortened in the middle, with ⧉ copy),
  **Open in Figure**, Show in folder, File info and ⋯ (Use as Library picture, Forget this view,
  with Undo).
- **Explore: plainer messages.** Esc closes the help or a popover first; it removes the cursors
  only when nothing is open, with Undo. A saved scatter view offers **Open in Figure** or **Show
  as curves**; a damaged file says so, with Show in folder; a variable sweep's note shows in the
  panel, not as a red message. Tabs show the file's title, the active tab is scrolled into view,
  ⋯ lists all Explore tabs, and ← → move along them.
- **Library: columns in any order and any width.** Drag a column title to move the column (★
  first, say), drag its edge to resize it; right-click → Move left / right / to the start, and
  Reset columns. The Files sidebar's columns move the same way.
- **Library: a clearer sidebar.** Tree rows line up level by level with guide lines and one
  column of counts; Project, Users and Tags have headings with their number of labels, stay at
  the top while their labels scroll, and fold away; a level shows its 12 most used labels, then
  **Show N more…**; **Find a label…** with many labels.
- **Labels as pills.** Each project, user and tag is one pill with its × inside, `›` between
  levels, on one line (a long one shortened in the middle) — in the selected file, the list's
  label columns and the filters above the list.
- **Long label lists are typed into, not scrolled.** New label, Move into and the Set / + Add
  pickers take a path (`Lab A/`) and suggest the next level, at most 8 at a time (Tab goes into a
  group); the pickers show the labels used most first. The pickers close on a click elsewhere and
  on Esc.

- **The Library in narrower windows and its filters.** The filters on the left (folders, dates,
  labels) can be hidden (◧‹ in their sidebar, ◧› to show them again; the number of filters in
  use on it) and dragged wider, as can the selected file's side; they stay while you go to Explore or
  Figure and back; a new browser tab made from a page (Open in new browser tab, Move to a new
  browser tab) starts with its filters. Below about 1280 pixels the filters (and Explore's and
  Figure's Files sidebar) slide over the content when asked for; below about 900 pixels the
  Library shows the list or the selected file, with ← Back. No more sideways scrolling: columns
  that don't fit are left out (a **+N** says which), and the date's time zone is shortened
  (`+08`, none when it is the computer's own).
- **Library: the selected file shows as much as it can without scrolling, on any screen.** It
  works out its layout from its own width: from about 650 pixels the preview and the file's
  facts sit side by side (the description, created, size, and its labels one row per kind:
  project, users, tags, comment); the star is ☆/★ in front of the title; the Values and Axes
  tables follow (columns empty in every row left out), then the metadata in columns, and at the
  end, folded, what wrote the file. Tested from 1280×720 to 3440×1440 and on 2× screens.
- **Library labels, managed.** Project, Users and Tags are always on the left, with **+ New**: a
  label can be kept before any file has it (in the folder's label file, new key `labels`).
  Right-click a label to make one under it, rename it, move it into another group or remove it
  from all files; drag a label onto another to move it, or files onto a label to give it to
  them. Each asks first, saying how many files it changes. A new label given to a file can be
  put under a group.
- **Previews are the data only** (no axes, numbers, colour bar or legend), drawn at 2× for
  high-density screens; the automatic ones are drawn again once.
- **Library: the selected file.** The title, the path (one line, cut in the middle; ⧉ copies it)
  and the date use the whole width, with the buttons below; a stopped or measuring file shows
  its state and **Recover…** above its preview; a preview with nothing to show takes one line.
  The preview no longer stays pinned over the labels when the right side scrolls. Shift-click no
  longer selects page text; the selected row is easier to see. An unreadable file says why in
  plain words (⚠ in its row; the technical message under Details). No matches: **Clear the
  search**, **Clear all filters**; filter chips say what they are ("Date: 2026").

- **Files being measured: a status line, and the finished file takes over.** A file being
  written (`name.lbd.writing`, ● on its tab) shows where it is measured and how far: *Measuring
  · power 23 of 90 · 26 % · 47 069 of 180 090 points · about 12 min left*, in Explore, Figure and
  the Library; the numbers keep their place while they change. ⚙ Measurements chooses the parts,
  and can turn on a browser notification when a measurement finishes or stops while the viewer
  is in the background. When it finishes, its tabs move to the finished file (panels, zoom,
  cursors and the remembered view kept) with a message, instead of staying on a name that is
  gone. The "still being written" message no longer repeats with every update; a cursor on a
  cell not measured yet says so.
- **Measured on another computer:** a file being written that comes through a synced folder
  shows *Measuring on LAB-PC*, or *No sign from LAB-PC since 10:06* (it probably stopped, or the
  sync is paused) instead of always "stopped"; **Recover a copy…** makes `name (recovered).lbd`
  and leaves the file being written alone. New page *Several computers*: what is safe to sync
  and what to watch out for (LBD has no sync of its own).
- **Getting data out of Explore** (each panel's **Data ▾** menu, and the right-click menu):
  **Save as CSV…** writes the numbers the panel shows (complex mode, operations, equations and
  chosen traces applied) into a new file next to the data. You choose the numbers (as shown,
  stored, or both), everything or the zoomed range, one data point per row or a table (matrix)
  for 2-D data, stored units or those on screen, and this panel or all panels. The dialog says
  how big the file will be and warns above 100 MB or beyond what Excel opens; large data is
  written part by part with progress and Cancel. The file reads back with `numpy.loadtxt`.
  **Copy picture** puts a PNG of the panel (or all panels) on the clipboard, as on screen or
  the plot alone; Figure has **Copy picture** too.
- **Values bigger than the memory available open**: a value that fits is read whole as before;
  a bigger one is read by part, only the map or curves shown. Parts read are kept while memory
  is free, the next slider positions are read ahead, and LBD always leaves some memory for the
  rest of the computer. ⚙ Settings → *Memory for data*: how much to leave free (automatic: 2 GB
  or 10% of the memory, whichever is more) and an optional most to use.

- **Maps and curves bigger than the memory available open too**: they are summarised once (a
  map's blocks' max, min and mean; each trace's min and max over blocks of points), reading the
  file part by part with progress and Cancel, and the summary is kept on disk, so they open at
  once next time. Zooming, panning and the reductions work as usual, showing the same picture;
  clicks, cursors, cuts and max/min/peak read the exact stored numbers from the file; a map's
  contrast histogram is counted from the summary and says so. Operations, choosing a map's rows,
  several values in one plot and an unwrapped phase of such curves are refused, with a message.
  ⚙ Settings → *Memory for data*: how much disk the summaries may take (20 GB; the least
  recently used go first) and *Empty*. Library previews of such data say to open it in Explore.

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

- `lbd.plot.table(...)`: the numbers a curve plot or heat map shows (same arguments as
  `lbd.plot.plot`), as shown, stored or both; `Table.to_csv(path, layout="rows" | "matrix")`
  writes them as Explore's Save as CSV does, readable by `numpy.loadtxt`.
- Curves can use a value as the horizontal axis (one with the same axes as the plotted value):
  each trace is drawn at its own x, e.g. a frequency span that changes with power.
- Complex modes `phase_unwrap` and `phase_deg_unwrap`: the phase without its 2π jumps along the
  horizontal axis (missing points are skipped).
- New module `lbd.plot.reduce`: reduce maps and curves to a screen's pixels without losing peaks.
- Choosing the saved "one curve per" axis (or a map's vertical axis) as the horizontal axis swaps
  the two, instead of warning that the saved view can't be used.

**File format and languages**

- **The heartbeat of a measurement, `name.lbd.live`** (spec §7; every language's Writer): a small
  JSON file beside a file being written, saying which computer and program measure and how far
  (points of how many, the outer axes' positions and seconds per step), rewritten at least every
  30 s and removed at the finish, so other computers can tell a running measurement from a
  stopped one. Python: `lbd.writing_progress(path)` reads it; `lbd.recover(path, keep=True)` makes
  a copy and leaves the file being written. Recover (every language) also removes a left-over
  heartbeat.
- **MATLAB and Julia name the program that keeps a file open** when a measurement can't be
  finished or recovered because of it ("… LBD Viewer (process 1234) kept it open …"), as Python
  does, and **warn when a Writer writes onto a network share** (Windows).

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

- **The README and the documentation's home page describe LBD 2.0**: find and label your data in
  the Library, look into it in Explore, make figures on the Figure page; with screenshots, cards for
  the Library, Explore and writing while measuring, and *How LBD works* opening with the three
  pages. *Concepts* lists a file's labels and id.

- **Build LBD yourself** (Developers): from the source at a release tag to installing the
  result, with the tools needed on each system; linked from the README and *Install*.

- **Variable sweeps**: *Concepts* explains axis groups (sweep axes, dimensions, data points) and
  **Grid or group?**, the pros and cons of each; the Python, MATLAB and Julia pages show building,
  writing (by coordinates and by the outer point), `to_dense`, `rows` and `coords`; *Writing
  while measuring* shows a variable sweep written live. `viewer/tests/mock_values.py` writes a
  variable sweep, a triangle and an adaptive map.

- A new page, **Writing while measuring** (Getting started): the Writer in every language, what
  `write` takes, growing axes, points not measured, what other programs see, and Recover.
  `viewer/tests/mock_live.py` writes a file slowly (and leaves a stopped one) to try the viewer.

**For developers**

- `scripts/make_mock_data.py --healthy`: mock data with nothing broken or in conflict (no damaged
  file, copies, conflicts, files without an id, missing file or stopped measurement), to show the
  tool or play around with it.
- `viewer/tests/mock_live.py --kind map|curve|scatter|variable` chooses what is written live (a
  power sweep as a map; a fridge cool-down log as a curve; single-shot readout as a scatter; a
  variable sweep), and `--name` the file's name. It writes only the live measurement now;
  `--stopped` also leaves one that stopped before finishing (`make_mock_data.py --live` asks for it,
  `--healthy` doesn't).
- The dev group installs `httpx2`: Starlette's `TestClient` uses it, so the viewer tests no longer
  warn "Using httpx with starlette.testclient is deprecated". `httpx` stays for the browser tests.
- The example files (`examples/data`, written by LBD 0.1.0) are no longer in the repository:
  `examples/make_examples.py` writes them in today's format where they are needed (run it before
  `lbd-view --dev examples/data`). The mock data, the screenshots, the smoke test, the release
  workflow, `test_all.py` (for the language modules' tests) and the `example_files` test fixture
  make them; `ensure_examples(folder)` writes a missing folder.
- The installer builds without warnings: `uv` runs quietly in the build scripts (PowerShell showed
  its progress as errors), esbuild's install step is approved in `package.json`, Vite's
  chunk-size hint is raised for this local page, Material's MkDocs 2 notice is off
  (`NO_MKDOCS_2_WARNING`; mkdocs stays below 2), and the viewer depends on `tzdata` on Windows
  (PyInstaller asked for it: time zone names for Python's `zoneinfo`).
- The viewer depends on `watchdog` (the Library's notifications, `library_watch.py`; bundled in
  every installer). `LibraryIndex.scan(folders=...)` checks only some folders; `scan()` returns
  what it found (`ScanResult`).
- **Faster tests.**
  - The viewer's tests and its browser tests run in parallel processes (pytest-xdist, whole files
    each); `test_all.py --workers N` (`1`: one by one). Tests that need the computer to themselves
    are marked `serial`.
  - Browser tests split into shards balanced by `viewer/tests/e2e/durations.json`: `--shard I/N`,
    `--record-durations`.
  - On GitHub, the tests run as side-by-side jobs: the web UI is built once, the suites run per
    system, the browser tests in shards (3 on Linux and Windows, 2 on macOS), cross-language per
    system. Chromium and Arial are cached.
  - Each e2e viewer server gets a port already bound for it.

- Mock data with long lists: `--many-labels` (`make_mock_data.py`, `dev_viewer.py`,
  `mock_library.py`; 300 users, 800 tags, names over 80 characters) and the
  `many_labels_files` fixture. New endpoints: `GET /api/roots/summary`, `POST
  /api/settings/reset`; the Library setting `column_widths`.

- **Mock data and a test viewer in one command each.** `scripts/make_mock_data.py FOLDER` makes a
  Library with every kind of label (stars, projects nested 1–3 levels, users in groups, flat and
  nested tags, comments, labels kept without a file), the files for Explore's panels, the
  examples, and with `--live` a measurement being written. `scripts/dev_viewer.py [FOLDER]`
  opens a test viewer on it (`lbd-view --dev`, with scratch settings). Documented in
  *Developers → Mock data* and a new *Quick start for developers*; *Releases* starts with a
  summary and a "Before releasing" list.
- `dev_viewer.py --build` builds the docs too (`mkdocs build --strict` into `site/`, the test
  viewer's Help), and without `--build` a line says when Help is older than the docs. Its scratch
  folders are deleted when the viewer stops, and those of stopped runs at the next start; never
  one still running, a `--keep-settings` folder or a folder you named.
- **Large files in the mock data.** `make_mock_data.py` (and `dev_viewer.py`'s new mock data)
  also writes `Large/`: the four engine tests (`viewer/tests/mock_large.py`, about 214 MB, the
  same numbers as the Labber logs): a curve of 1 000 000 points with a spike, a dip and a gap,
  1000 traces × 10 000 points, a 4001 × 4001 map, and a small map with uneven x. `--small` leaves
  them out. `Panels/` gets uneven grids (a map uneven on both axes, a map on a log-spaced axis, a
  curve with uneven x), and `mock_live.py --variable` writes a variable sweep live.
  *Developers → Mock data* says what to look for in each.
- `scripts/test_all.py` runs the suites side by side (`--jobs`, default 4), the longest first:
  a whole run takes about as long as the browser tests instead of the sum of all. `--changed
  [REF]` runs only the suites the changed files can affect, `--only` names suites. Viewer and
  browser tests that fail side by side run again alone, and the summary says so.
- New endpoints `GET /api/updates`, `POST /api/updates/check` and `POST /api/updates/remind`
  (`updates.py`; the settings group `updates`); tests never ask GitHub (`LBD_NO_UPDATE_CHECK=1`
  for a real viewer process).
- New endpoint `POST /api/stop` (local, with the token). The release workflow's Windows and Linux
  jobs run `scripts/upgrade_test.py`: v1.2.0 from its release, the new build over it, then an
  older-numbered build of the same installer, which must be refused.

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
