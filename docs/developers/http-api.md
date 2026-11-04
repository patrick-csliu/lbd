# HTTP API

All endpoints are under `/api/`, take and return JSON unless noted otherwise, and require the
header `X-LBD-Token: <session code>`.

**Security model**

- The server binds to `127.0.0.1` only.
- Every `/api` request must carry the session token. It is random per start; `cli.py` passes it
  to the browser in the URL, and the UI moves it into `sessionStorage`.
- The `Host` header must be `127.0.0.1` or `localhost`. This blocks DNS rebinding.
- File paths must be inside a configured root folder, or have been opened explicitly
  (`/api/open`, double-click, command line). Anything else gets 403.
- Outside `/api/` the server only serves the web UI (`/`) and the documentation (`/docs/`).
  Neither holds user data, so they need no token; the host check still applies.

**Documentation.** `GET /docs/...` serves the built documentation site from the first of:
`$LBD_DOCS_DIR`, `<app folder>/docs` (installed app), `<repo>/site` (from source). Without
one, it answers 404 with a page that explains how to build it.

**Errors** are returned as `{"detail": "<message>"}` with status:
- 400: invalid input, a file that isn't LBD, a render problem, an invalid style (including an
  unknown setting), a broken settings file;
- 403: missing token, wrong host, or a path outside the allowed folders;
- 404: not found (also: a folder that isn't in the list, a path that isn't a file or folder);
- 409: a dialog is already open; a file that is being moved between pages; a view saved over a
  file that changed since the page loaded it; a page rule refused (see [Pages](#pages));
- 501: no system dialog here;
- 422: a request body with a missing field, a wrong type or an **unknown field** (bodies are
  strict, so a typo in a field name is an error instead of being ignored).

**Warnings.** Responses of `state`, `file`, `file/plot`, `render`, `styles/{name}` and
`stylefile` have a `warnings` list: things that worked but were adjusted or ignored (a style
setting from a newer LBD, a file's style preset that doesn't exist here, metadata that can't be
read, a settings problem). `export` sends them in the `X-LBD-Warnings` header (a JSON list). The
UI shows them as notes. They are the messages of Python's `lbd.LBDWarning`s.

An unexpected error (a bug) answers 500 with `{detail}`: what was being done, the error, and
where the details are (`viewer.log`, next to LBD's database); the session stays usable.

## App

| Method and path | Body / query | Response |
|---|---|---|
| `GET /api/ping` | | `{app: "lbd-viewer", version, pid}`. Used by `cli.py` to detect a running viewer. |
| `POST /api/heartbeat` | | `{ok: true}`. Tabs call it every 10 s; the server stops after `--idle-exit` seconds without one. |
| `GET /api/state` | | `{version, lbd_version, roots, default_style, open_files_in, open_data_in, theme, library, styles, platform, config_dir, warnings}`. `library`: `{read_headers, notice_seen, columns}` (the Library's settings, see `PUT /api/settings`). `warnings` also lists folders that no longer exist, a default style that was deleted, and (once) a broken database that was put aside. |
| `POST /api/open` | `{path}` | `{path}` (resolved). Allows reading a file outside the roots. |
| `PUT /api/settings` | `{default_style?, open_files_in?, open_data_in?, theme?, library?}` | Same as `GET /api/state`. `library`: any of `read_headers` (bool: read each data file's header for the Library's index; off: names, sizes and file dates only), `notice_seen` (bool: the cloud-storage notice was acknowledged), `columns` (the list's columns in their order, from `name`, `date`, `sweep`, `values`, `folder`, `size`, `file`, `modified`, `star`, `project`, `users`, `tags`, `comment`, `copies`), `column_widths` (`{column: px}` for columns whose width was dragged, 24–2000); changing `read_headers` makes the index check the folders at once. `open_files_in`: `"viewer"` (files from Explorer / Finder go to the open page) or `"browser-tab"`. `open_data_in`: the workspace data files from Explorer / Finder open in, `"explore"` or `"figure"`. `theme`: `"system"` (follow the operating system), `"light"` or `"dark"`. Every page gets `settings_changed` for these three. 400 if none is given or a value is invalid. |
| `POST /api/settings/reset` | `{section}` | One section of the Settings dialog back to its defaults (`general`, `library`, `sidebar`, `memory`, `measurements`; the settings in each are `SETTINGS_SECTIONS` in `config.py`). Same as `GET /api/state`, whose `defaults` gives each section's settings and their defaults (`{section: {"memory.maximum_gb": null, …}}`). 400 for an unknown section. |

## Folders

| Method and path | Body / query | Response |
|---|---|---|
| `POST /api/roots` | `{path}` | `{roots}`. 400 if not a folder. |
| `GET /api/roots/summary` | `?path=` | What removing that open folder changes, asked first: `{files, labelled, labels_only_here: {project, users, tags}, pages, inside}`: its files in the Library, those with labels, the labels no file elsewhere has, the browser tabs showing a file in it, and open folders inside it (which stay). 404 if the folder isn't in the list. |
| `DELETE /api/roots` | `?path=` | `{roots}`. 404 if the folder isn't in the list. |
| `POST /api/pick-folder` | | `{path}` from the native folder dialog, `null` if cancelled. 501 without a dialog, 409 if one is already open. |
| `GET /api/list` | `?path=` | `{path, dirs: [name], files: [{name, type, size, mtime}], errors: [{name, error}], signature}`: direct children only; `signature` changes whenever the listing does (see `/api/changes`); `type` is `lbd`, `style` (`.lbd.json`) or `image`; other files and skipped folders are left out; entries that can't be read (permissions, broken links) are in `errors`. |
| `POST /api/changes` | `{files: [path], dirs: [path]}` | `{files: {path: version}, dirs: {path: signature}, errors: {path: reason}}`: what changed on disk, asked every 2 s by each visible page for the files it shows and the folders it lists (`web/src/watch.ts`). A file's `version` is the one `/api/file` returns (modification time and size), a folder's `signature` the one `/api/list` returns; `null` when it is gone. Only sizes and times are read; no file is opened. A path that isn't allowed is in `errors`, never left out. |
| `GET /api/search` | `?root=&q=` | `{root, query, results: [{path, rel, type, size, mtime}], truncated, errors: [{path, error}]}`: recursive, case-insensitive substring of the relative path, up to 500 results; folders or files that couldn't be read are in `errors`. 404 if `root` isn't a folder. |
| `POST /api/reveal` | `{path}` | `{ok}`. Opens the system file manager with the file selected (a folder: opens it). |
| `POST /api/file/rename` | `{path, name}` | `{path}`: the new path, in the same folder. Only data, style and image files. 400 for a folder, another kind of file, a name with `/` or `\`, or a changed extension; 409 if the name exists or the file is being moved between pages; 404 if the file is missing. Every page gets a `renamed` event. |
| `POST /api/file/recover` | `{path}` | `{path}`: the `.lbd` file made (`lbd.recover`) from a file whose measurement stopped before finishing (`name.lbd.writing`). 400 for another file; 409 while it is still being written. Every page gets a `renamed` event. |
| `POST /api/file/trash` | `{path}` | `{ok}`. Moves the file to the Recycle Bin / Trash (`send2trash`); never deletes permanently. 400, 404 and 409 as rename; 500 if the system has no trash for it (the file stays). Every page gets a `trashed` event. |

## Library

The index of the data files under the open folders (`library.py`, `library.sqlite` next to
`catalog.sqlite`): read in the background, from the first library request on (every few seconds
while the Library asks, else every minute, and at once after `POST/DELETE /api/roots` or a change
of `library.read_headers`). A path outside the open folders is a 403.

| Method and path | Body / query | Response |
|---|---|---|
| `GET /api/library/list` | `?folder=&q=&date=&sort=&order=&offset=&limit=&project=&tags=&users=&starred=&conflicts=` | `{rows, total, generation}`: one page of the data files under `folder` (absent: every open folder) whose text has every word of `q` (case-insensitive; title, file name, description, axis and value names, labels and units, metadata keys and values; with `read_headers` off: file names only) and whose day starts with `date` (`2026`, `2026-03`, `2026-03-14`); labels: `project` (and the projects inside it), `tags` / `users` (repeatable: any of them, each with its sub-labels), `starred`, `conflicts`. `sort`: `name` (title, else file name), `date`, `sweep`, `values`, `folder`, `size`, `file`, `modified`; `order`: `asc` / `desc` (default `date`, `desc`); `limit` up to 1000. A row: `{path, root, folder, name, size, mtime, read, title, description, created, day, date_from_file, sweep, points, value_names, error}`: `created` as written in the file, `day` its date in the file's own time zone (`date_from_file`: from the file's modification time, when `created` is missing, unreadable or not read), `sweep` e.g. `"401×31"` (axes with more than one point; `points` their product), `error` why the file can't be read (it stays listed). 400 for an unknown `sort`. |
| `GET /api/library/facets` | `?folder=&q=&date=` | `{dates: {YYYY: {MM: {DD: count}}}, folders: [{path, name, count, children}], total, projects, users, tags, starred, conflicts, missing, generation}` (`projects` / `users` / `tags`: `[{label, name, count, children}]`): the date tree of the files `list` would give without a date, the tree of each open folder with the number of data files below each folder, and `total`, the files under all open folders (a folder opened inside another counted once). |
| `GET /api/library/file` | `?path=` | The file's summary, as `GET /api/file`, plus `warnings`; from the index, or read now when it isn't indexed, changed, or wasn't read (`read_headers` off). 404 if missing; the reading error (e.g. a damaged file) as with `/api/file`. |
| `POST /api/library/labels` | `{paths, star?, project?, comment?, add_tags, remove_tags, add_users, remove_users}` | `{notes}`. Changes the labels of these files and of their identical copies (`project: ""` removes it), in the folders' label files (`labels.py`); a mistyped label (an empty part, `a//b`), a read-only folder or a busy label file: 409 with the reason. |
| `GET /api/library/same` | `?path=` | `{id, conflict, size, mtime, others: [{path, size, mtime, title, differs, newer}]}`: the other files with this file's id; `differs` in words (`title`, `description`, `date (created)`, `metadata`, `values or their sizes`, `axes`, `the data itself`) when they are a conflict. |
| `POST /api/library/resolve` | `{path, action}` | `{notes}`. `new_id`: writes a new id into this file (its old one as `parent_id`), only if it is unchanged since indexed and not open elsewhere (else 409, nothing written); `same`: remembered in the label files, the conflict cleared until one of them changes; `trash`: as `/api/file/trash`. |
| `POST /api/library/duplicate` | `{path, labels}` | `{path, notes}`: a copy next to the file (`name (copy).lbd`, `(copy 2)` …; never replaces a file) with a new id and the original's as `parent_id`; with `labels`, the labels too. |
| `POST /api/library/give-ids` | `{paths}` | `{notes}`: writes an id into each of these files that has none. |
| `GET /api/library/missing` / `POST` | — / `{entry, path?}` | `{missing: [{folder, id, name, created, star, project, users, tags, comment}]}`: labels whose file can't be found. `POST` points an entry to a file (`path`) or discards it (no `path`). |
| `GET /api/library/preview` | `?path=&now=` | The file's preview (`previews.py`): a WebP picture with header `X-LBD-Preview` = `{source: "chosen", chosen_at, changed_since}` or `{source: "automatic", drawn_at}`; without a picture, JSON `{state: "drawing" \| "off" \| "error", reason}`. Not drawn yet (and previews not off): asked for, first with `now=true` (the selected file), else after it. |
| `POST /api/library/preview/want` | `{paths, now}` | Draw these previews soon: `now` (Show preview) even with previews off; else as rows near the selection (not when off). |
| `POST /api/library/preview/choose` | `{path, panels: [{spec, settings, stat, view}], grid: [rows, columns], preset?}` | `{chosen_at, warnings}`: Explore's **Library preview**: draws its panels once and keeps only the picture as the file's chosen preview (`catalog.sqlite`, under the file's id so identical copies share it, else its path); 422 with the reason if it can't be drawn. `DELETE ?path=` forgets it (`{forgotten}`). |
| `GET /api/library/preview/cache` / `POST /api/library/preview/clear` | | `{count, bytes}` of the automatic pictures / `{freed}`: deletes them (chosen ones are kept). |
| `GET /api/library/status` | | `{indexing, done, total, errors, scans, generation, notes, previews: {drawn, total, drawing, mode}}` (`notes`: about labels, e.g. a merged sync conflict copy; given once): progress of the current check (`done` of `total` files to read), folders that couldn't be read, and `generation`, which changes whenever the index does (the page then asks for its rows again). |

## Pages

Each browser tab showing the viewer is a *page*. The rules (one page per open file, delivery,
moving tabs) are in `viewer/src/lbd_viewer/pages.py`; these endpoints adapt them to HTTP. An
unknown or expired page is a 404 (a page then registers again); a refused rule (a file being
moved, a transfer already over or claimed, a move to a page that was closed) is a 409.

| Method and path | Body / query | Response |
|---|---|---|
| `POST /api/pages` | | `{page, number}`: a new page, with the lowest number no live page has (closed and expired pages free theirs). |
| `GET /api/pages` | | `{pages: [{page, number, files}]}`: the live pages and the files each has open (the same list `pages_changed` sends). |
| `GET /api/pages/{id}/next` | `?wait=` (0–30 s, default 25), `?after=` (default 0) | The long poll, which also keeps the page alive: the first command not handled yet, `{id, kind, data}`, or `{}` after `wait` seconds. `after` is the `id` of the last command the page handled: it and the ones before are confirmed and dropped. A command stays queued until confirmed, so if its answer got lost (the connection dropped), it comes again. A page is dropped 40 s after its last poll, or after 3 s *offline* unless it polls meanwhile. A page is offline from `POST /api/pages` until its first poll, and when its long poll's connection drops (the tab closed, even without `bye`). An offline page is not listed or sent files, so a page that registers but never listens never shows up as a target. |
| `POST /api/pages/{id}/ack/{command}` | | `{granted, elsewhere, busy}`: the page takes the files of an `open` command. It opens `granted`; `elsewhere` (`{path: page number}`) are open in another page; `busy` ones are being moved. |
| `POST /api/pages/{id}/focus` | | `{ok}`: the page was used; files from Explorer go to the page used last. |
| `POST /api/pages/{id}/bye` | | `{ok}`: the page is closing; its files are free at once. |
| `POST /api/pages/{id}/acquire` | `{path}` | `{path}` (its canonical spelling) if the page may open it, or `{path, owner}` if page `owner` has it open (then nothing changes). |
| `POST /api/pages/{id}/release` | `{path}` | `{ok}`: the page closed the file. |
| `POST /api/pages/show` | `{path}` | `{page}`: asks the page that has the file open to show it. 404 if no page has. |
| `POST /api/transfers` | `{page, paths, states, to}` | `{id, timeout}`: starts moving tabs from `page` to page `to`, or to a new browser tab (`to: null`; the source opens `/?claim=<id>`). `states` are the tabs' unsaved settings. The files are locked until the move ends. 409 "that page was closed" if `to` is gone. |
| `POST /api/transfers/{id}/claim` | `{page}` | `{paths, states, from}`: the target takes the files and opens the tabs. |
| `POST /api/transfers/{id}/complete` | `{page}` | `{paths}`: the target has the tabs; the files are now its own, and the source gets `transfer_done`. Asking again (the answer got lost) gives the same answer. |
| `POST /api/transfers/{id}/cancel` | `{reason}` (optional) | `{ok}`; the source is told the `reason` (the page cancels when the new browser tab it opened was closed). A move without `complete` in time (5 s; 15 s for a new browser tab), or whose target closes, is cancelled the same way: the source gets `transfer_cancelled` and keeps its tabs. |
| `POST /api/deliver` | `{files, dirs}` | `{delivered, shown, busy, unplaced}`: what `lbd-view file.lbd` sends to a running viewer. Files already open are shown in their page (`shown`); the others go to the page used last, which must take them within 3 s. `unplaced`: files no page took (the caller opens a browser tab for them); `busy`: files being moved. `dirs` are added to the folder list. |

Commands a page receives (`kind`, `data`):

| Kind | Data | Sent when |
|---|---|---|
| `open` | `{paths}` | files were delivered; the page answers with `ack` |
| `show` | `{path}` | the file is wanted, and this page has it (`path: null`: just come forward) |
| `transfer` | `{id, from}` | another page moves tabs here; the page claims them |
| `transfer_done` | `{id, paths, to}` | this page's tabs arrived in page `to`; close them |
| `transfer_cancelled` | `{id, paths, reason}` | this page's move was cancelled; unlock the tabs |
| `pages_changed` | `{pages: [{page, number, files}]}` | the live pages changed: one opened, closed or lost its connection, or opened, closed or took files. The whole list; an older one still queued is replaced |
| `event` | `{event: "renamed", old, new}`, `{event: "trashed", path}`, `{event: "roots_changed"}`, `{event: "styles_changed"}`, `{event: "settings_changed"}` | a file was renamed or moved to the trash, or the folder list, the presets or the ⚙ settings (`open_files_in`, `open_data_in`, `theme`) changed |

## Images (view only)

| Method and path | Body / query | Response |
|---|---|---|
| `GET /api/image/info` | `?path=` | `{path, name, file_size, modified, format, width, height, mode, bit_depth, frames, dpi, size_mm, text, note}`. `text` holds PNG text chunks, EXIF basics, or SVG size/metadata. |
| `GET /api/image` | `?path=` | Bytes a browser can show. PNG/JPEG/GIF/WebP/SVG as they are; TIFF and BMP converted to PNG (16-bit images contrast-stretched). SVG is sent with `Content-Security-Policy: script-src 'none'`. |

## Files and figures

| Method and path | Body / query | Response |
|---|---|---|
| `GET /api/file` | `?path=` | File summary: `{path, name, title, description, created, writer, lbd_version, size, axes: [{name, unit, label, length, dtype, min, max}], values: [{name, unit, label, axes, shape, dtype, complex, text?}], meta, plot, style, style_name, matplotlib, version}` (`text`: a single number (no axes) as shown, with a unit prefix, e.g. `"21 µs"`; `matplotlib`: the version that last wrote the saved view, or `null`; `version`: the file's modification time and size, for `if_version`). In `meta`, arrays over 50 elements become `{array, shape, dtype, preview}` and complex numbers become strings. |
| `GET /api/axis` | `?path=&name=` | `{name, label, unit, values}`: every value of a numeric axis (missing points are `null`), e.g. to go to the point nearest a typed value. 404 for an unknown axis, 400 for a non-numeric one. |
| `PUT /api/file/plot` | `{path, spec?, style?, style_name?, if_version?}` | The updated file summary. Keys present in the body are set; `null` removes the entry; absent keys are kept; 400 if none is given or the spec has unknown keys. Calls `lbd.set_plot`. With `if_version`, 409 if the file changed since (another program wrote it); without it, the file is overwritten. 409 also while the file is being moved between pages. |
| `POST /api/render` | `{path, spec?, preset?, style?, style_file?}` | `{svg, spec, preset, size_mm: [w, h], warnings}`. An unknown `preset` is a 400; a file's own `style_name` that doesn't exist falls back to the default with a warning. Plot settings that don't apply to the chosen plot type are ignored without a warning here, because the UI keeps them while switching types. `spec` in the response is the resolved [plot spec](../styles/plot-settings.md), plus `slices: [{axis, index, length, label, unit, value}]`. `preset` names the preset used; `style` holds unsaved UI changes; `style_file` (a `.lbd.json` inside a root) replaces the preset, for previews. |
| `POST /api/export/save` | as export | Renders, then shows the system "Save as" dialog on this computer (data file's folder, default name filled in) and writes the file there: `{path, warnings}`, `path` is `null` if cancelled. Render errors come before the dialog. 400 if the chosen name has another extension (nothing saved); 501 without a dialog (the UI then uses `/api/export`); 409 if another dialog is open. |
| `POST /api/export` | as render, plus `format`: `svg`, `pdf`, `png` or `jpg` | The file bytes as a download, with `Content-Disposition: attachment; filename="<file>_<values>.<fmt>"`, and `X-LBD-Warnings` when there are warnings. |

## Explore

The Explore workspace's views (`explore.py`): a session per Explore tab keeps the file's data,
its reductions to the screen (`lbd.plot.reduce`) and a matplotlib figure the size of the panel.
Sessions close with their tab, after 10 minutes unused, and beyond 12 at once (the least
recently used); an unknown session is a 404 and the UI opens a new one.

| Method and path | Body / query | Response |
|---|---|---|
| `POST /api/explore` | `{path, spec?, preset?, width, height, dpr?}` | `{session, spec, kind, preset, full: [[x0, x1], [y0, y1]], warnings}`. `width`/`height`: the panel in CSS pixels (at least 50); `dpr`: the screen's pixel ratio (1–2). `spec` as for render; the Explore view shows curves and heat maps (400 for scatter). `spec` in the response is resolved, with `slices`; a value used as x adds `along`, the axis its points run along. |
| `POST /api/explore/{session}/spec` | `{spec}` | As opening: other plot settings, drawn by the same session (the data already read is kept). |
| `POST /api/explore/{session}/render` | `{xlim?, ylim?, stat?, format?, settings?, width?, height?, dpr?}` | The picture: raw RGBA pixels (`format: "raw"`, default) or PNG. The `X-LBD-Frame` header (JSON) has `{format, width, height, dpr, plot: [left, top, width, height], xlim, ylim, xscale, yscale, full, note, reduced, stat, ms: {wait, reduce, draw, encode}, notes}`: the plot area in the picture's pixels and its limits map pixels to data. `xlim`/`ylim` absent: all the data. `stat` (`max`, `min`, `mean`): what a pixel shows when it covers several map cells; `note` says how the data was reduced. `settings`: how the data is shown: `select` `{axis: [positions]}` (the traces drawn, or the map's rows; left-out rows stay empty), `cmap`, `invert`, `xscale`/`yscale`/`cscale` (`linear`, `log`), `clim` `[from, to]` (`null`: from the data), `ops` (a list of operations, `operations.py`: `{op, along?, on?, n?, bins?, method?, sigma?}` (`smooth`: `method` `mean`, `gaussian` with `sigma` in points, or `median` with an odd `n`) with `op` one of `subtract_mean`, `normalize`, `derivative`, `smooth`, `subtract_first`, `subtract_previous`, `average`, `std`, `fft`, `histogram`, with `along`: `x` or `traces`; first, on complex values: `delay` `{tau}` (s), `rotation` `{phi}` (degrees), `auto_rotate`, `iq_histogram` `{bins}`), `ops_on` (`false`: all off, equations too), `equations` (`{x?, y?, z?}`: formulas applied after the operations, `equations.py`); `notes` mention chosen positions that no longer exist. `ops` in the header is `{notes, applied, equations, names, shows?, unit?, one_to_one?}`: per operation `null` (applied), `"off"`, or why it can't apply; per equation field `{error}` (left out) or `{note}` (e.g. points without a value); `names`: `[{name, means}]`, what each name in an equation stands for (stored units). Cursor read-outs then carry `stored` (the stored value behind a shown point, while `one_to_one`). Every picture's header also has `hidden` (notes on what the scales hide, e.g. points ≤ 0 on a log axis, or a log scale kept linear) and `empty` (why nothing can be shown, or `null`), and `sync` `{x, y}`: what panels must share to follow each other's zoom (the horizontal axis' label as drawn; the vertical unit, or a map's vertical axis label). Curves of values with two units are drawn with a right-hand axis (`explore.py` `_units_apart`); a third unit is a 400. Cursor table rows then carry their own `unit`. A new `width`/`height` redraws the same view at that size. |
| `POST /api/explore/{session}/pick` | `{x, y}` (pixels of the last picture) | `{pick}`: the stored point (curves) or cell (maps) there, from the full data, or `null`. A point: `{kind: "point", trace, label, value_name, index, x: {axis, value, unit, label}, y, y_unit, series?, shown, at, line}` (`y` as plotted: complex modes applied; `line`: the trace as drawn, in pixels, for highlighting). A cell: `{kind: "cell", index, x, y, value, value_unit, shown, rect}`. |
| `POST /api/explore/{session}/cursors` | `{cursors: [{x, y, trace?, free?, step?}], type?, xlim, ylim, width, height, cuts?, lines?}` | Everything the page draws for one cursor state (`reading.py`): `{type, factors: {x, y, z}, cursors: [...], cuts?}`. One or two cursors, positions in plot units; `type`: `cross` (default), `vertical`, `horizontal`. Each is snapped to the stored data (curves: the nearest point on screen, given the view `xlim`/`ylim` and plot area `width` × `height`; with `trace`, on that trace; maps: the cell), unless `free`. `step` `[along x, along y or traces]` moves by stored points. Each cursor: `{x, y, free, trace?, label?, index: {axis: i}, items: [{role, name, label, unit, value, index?}], table?, line?, cell?}`; `items` are the numbers as stored (values as plotted); `table` (vertical, curves): every visible trace's value at that x; `line`: the trace as drawn (plot units). `cuts` (maps): `{row?, column?}`, each `{pos, z, range, fixed, index}` through cursor 1, reduced to the plot area's pixels. `factors`: plot units per stored unit. |
| `POST /api/explore/{session}/find` | `{what, xlim, ylim, trace?}` | `{x, y, trace?}`: the stored point (curves; of `trace`, else of every visible trace, within `xlim`) or cell (maps, within the rectangle) with the highest (`max`) or lowest (`min`) value, or farthest from the median (`peak`). 400 when nothing is stored there. |
| `POST /api/explore/{session}/histogram` | `{settings?}` | Maps: the shown cells counted, `{edges, counts, lowest, highest, auto, log, cells}` in plot units (`auto`: the range without 0.5 % at each end; `log`: log-spaced bins of the positive cells on a log colour scale). `settings` as for render, applied first. |
| `POST /api/explore/{session}/calculate` | `{what, index, xlim, trace?}` | `{value, unit}`: for operation `index` (a `delay` or `rotation`), the τ (s) or φ (°) that straightens the data in `xlim` (plot units) of `trace` (else all shown traces), with the complex operations above it applied. 400 with too few points. |
| `POST /api/explore/{session}/save-cut` | `{which, index, trace?, path?}` | `which`: `row` or `column` (maps; through the cell at `index`) or `trace` (curves). Without `path`: `{path}`, a suggested new file next to the data file. With `path`: writes the cut (stored data along the kept axis; metadata `cut_from`, `cut_index`, `cut_at`, `source_meta`) and returns `{path}`; refuses an existing file. |
| `DELETE /api/explore/{session}` | | `{ok}`. A request still using a closed session gets 404, like an unknown one. |
| `GET /api/explore/remembered` | `?path=` | `{state, note}`: the Explore view remembered for the file in LBD's database (`catalog.py`; never in the file). `state` is `{version: 2, panels: [{id, spec, settings, stat, view, cursors, …}], active, layout, sync: {x, y, sliders}}`; a record from before panels (no `version`) is upgraded to one panel (`catalog.upgrade`). Panels that no longer fit the file (an axis or value they use is gone or changed) are left out and named in `note`; none left: `state: null` with a `note`. |
| `PUT /api/explore/remembered` | `{path, state}` | `{ok}`. The last save wins. Renaming a file (`/api/file/rename`) keeps its remembered view. |
| `DELETE /api/explore/remembered` | `?path=` | `{ok}`: forgets it. |

## Styles

| Method and path | Body / query | Response |
|---|---|---|
| `GET /api/styles` | | `[{name, builtin, customized, default}]`; `default` first, then alphabetical |
| `GET /api/fonts` | | `{installed, generic}`: the font families installed on this computer (sorted) and the generic ones; the Styles page offers these |
| `GET /api/style-defaults` | | `{defaults, schema}`: the built-in defaults and the JSON schema of `Style` |
| `GET /api/styles/{name}` | | `{name, preset, resolved, builtin, customized, warnings}`: `preset` holds only the stored differences, `resolved` is complete |
| `PUT /api/styles/{name}` | `{preset}` | Same as GET. 400 for invalid names, unknown settings or invalid values. |
| `GET /api/styles/{name}/export` | `?format=lbd` or `mpl` | The complete style as a `<name>.lbd.json` file, or matplotlib's `<name>.mplstyle`, as a download |
| `POST /api/styles/import` | `{name, content, overwrite?}` | Same as GET of the new preset. `content` is the style file's JSON (object or text). 400 for bad JSON, invalid values, or an existing name without `overwrite`. |
| `GET /api/stylefile` | `?path=` | `{path, name, description, resolved, size, warnings}`: a `.lbd.json` file inside a root, fully resolved; settings it has that this version doesn't know are ignored with a warning |
| `DELETE /api/styles/{name}` | | The list. Deletes a user preset, or resets a customized built-in one; 400 for an unchanged built-in one. |

## Language modules

| Method and path | Body / query | Response |
|---|---|---|
| `GET /api/sdk` | | `{version, lbd_version, bundled, sdk_dir, languages: {python, matlab, julia}}`. Each language: `{name, folder, available, requirements, install: [{label, code}], check, upgrade, uninstall, example, notes}` |
| `POST /api/sdk/reveal` | `?lang=` | `{folder}`. Opens that language's folder. |

When the viewer runs from the source tree (`bundled: false`), the commands point at the source
folders. In an installed viewer they point at `<install dir>/sdk`. `LBD_SDK_DIR` overrides the
location.
