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

## App

| Method and path | Body / query | Response |
|---|---|---|
| `GET /api/ping` | | `{app: "lbd-viewer", version, pid}`. Used by `cli.py` to detect a running viewer. |
| `POST /api/heartbeat` | | `{ok: true}`. Tabs call it every 10 s; the server stops after `--idle-exit` seconds without one. |
| `GET /api/state` | | `{version, lbd_version, roots, default_style, open_files_in, theme, styles, platform, config_dir, warnings}`. `warnings` also lists folders that no longer exist and a default style that was deleted. |
| `POST /api/open` | `{path}` | `{path}` (resolved). Allows reading a file outside the roots. |
| `PUT /api/settings` | `{default_style?, open_files_in?, theme?}` | Same as `GET /api/state`. `open_files_in`: `"viewer"` (files from Explorer / Finder go to the open page) or `"browser-tab"`. `theme`: `"system"` (follow the operating system), `"light"` or `"dark"`. Every page gets `settings_changed` for these two. 400 if none is given or a value is invalid. |

## Folders

| Method and path | Body / query | Response |
|---|---|---|
| `POST /api/roots` | `{path}` | `{roots}`. 400 if not a folder. |
| `DELETE /api/roots` | `?path=` | `{roots}`. 404 if the folder isn't in the list. |
| `POST /api/pick-folder` | | `{path}` from the native folder dialog, `null` if cancelled. 501 without a dialog, 409 if one is already open. |
| `GET /api/list` | `?path=` | `{path, dirs: [name], files: [{name, type, size, mtime}], errors: [{name, error}], signature}`: direct children only; `signature` changes whenever the listing does (see `/api/changes`); `type` is `lbd`, `style` (`.lbd.json`) or `image`; other files and skipped folders are left out; entries that can't be read (permissions, broken links) are in `errors`. |
| `POST /api/changes` | `{files: [path], dirs: [path]}` | `{files: {path: version}, dirs: {path: signature}, errors: {path: reason}}`: what changed on disk, asked every 2 s by each visible page for the files it shows and the folders it lists (`web/src/watch.ts`). A file's `version` is the one `/api/file` returns (modification time and size), a folder's `signature` the one `/api/list` returns; `null` when it is gone. Only sizes and times are read; no file is opened. A path that isn't allowed is in `errors`, never left out. |
| `GET /api/search` | `?root=&q=` | `{root, query, results: [{path, rel, type, size, mtime}], truncated, errors: [{path, error}]}`: recursive, case-insensitive substring of the relative path, up to 500 results; folders or files that couldn't be read are in `errors`. 404 if `root` isn't a folder. |
| `POST /api/reveal` | `{path}` | `{ok}`. Opens the system file manager with the file selected (a folder: opens it). |
| `POST /api/file/rename` | `{path, name}` | `{path}`: the new path, in the same folder. Only data, style and image files. 400 for a folder, another kind of file, a name with `/` or `\`, or a changed extension; 409 if the name exists or the file is being moved between pages; 404 if the file is missing. Every page gets a `renamed` event. |
| `POST /api/file/trash` | `{path}` | `{ok}`. Moves the file to the Recycle Bin / Trash (`send2trash`); never deletes permanently. 400, 404 and 409 as rename; 500 if the system has no trash for it (the file stays). Every page gets a `trashed` event. |

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
| `event` | `{event: "renamed", old, new}`, `{event: "trashed", path}`, `{event: "roots_changed"}`, `{event: "styles_changed"}`, `{event: "settings_changed"}` | a file was renamed or moved to the trash, or the folder list, the presets or the ⚙ settings (`open_files_in`, `theme`) changed |

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
