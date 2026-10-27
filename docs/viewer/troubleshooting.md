# Troubleshooting

| Problem | Cause and fix |
|---|---|
| "This page has no valid session" | The tab belongs to a viewer that has stopped, or it was opened from a bookmark. Start the viewer again from the menu or by opening a file. |
| "Can't reach the viewer" | The viewer stopped, for example after all tabs were closed or after sleep. Start it again. |
| "This path is not inside one of your folders" | Add the folder containing the file with **+ Add folder**, or open the file by double-clicking it. |
| A figure shows an error box | The message says what's wrong, e.g. a heat map of a 1-D value, an axis the value doesn't have, or invalid math in a label. Change the setting or press **Reset**. |
| "invalid style: figure.font.size_pt: …" | A style value is out of range. The message names the key; see [Style settings](../styles/settings.md). |
| "unknown style setting 'figure.widht_mm' (did you mean 'figure.width_mm'?)" | A typo in a style (JSON box, imported file, Python dict). Unknown settings are never ignored silently; fix the name. |
| A yellow note under a figure | The figure was drawn, but something was adjusted or ignored, e.g. the file asks for a style preset that only exists on another computer, or its saved view names a value that no longer exists. The note says what. |
| A folder item shows ⚠ | The viewer can't read that entry (no permission, or a link whose target is gone). Hover it for the reason. |
| "Couldn't search …" or "… couldn't be read, so the results may be incomplete" | Some folders couldn't be searched (permissions, a disconnected drive). The results show what could be read. |
| A notice that a folder no longer exists | A folder in the list was moved, deleted, or is on a drive that isn't connected. Reconnect it, or remove it with **×**. |
| "settings.json is not valid JSON; fix or delete the file" | The viewer's settings file is damaged. It is not reset automatically, so nothing is lost: fix it, or delete it to start with empty settings. |
| An image shows "can't be read" | The file is damaged or not really an image of that type. Very large images (above about 180 megapixels) are refused for safety. |
| Error: the font '…' is not installed | The style's font isn't on this computer. The message lists fonts you can use. The default font, Arial, is on Windows and macOS; on Linux install it (e.g. the `ttf-mscorefonts-installer` package), or set the style's font to DejaVu Sans, which ships with matplotlib and gives identical figures everywhere. |
| Nothing happens when double-clicking (Windows) | Check the log in `%LOCALAPPDATA%\lbd\Logs\viewer.log`. A startup failure also shows a message box. |
| macOS: "Apple could not verify 'LBD Viewer'…", or nothing happens | The app isn't signed by a registered developer, so macOS asks for your approval once per version: System Settings → Privacy & Security → **Open Anyway** (see [Install](../getting-started/install.md#lbd-viewer-on-macos)). Otherwise, check the log in `~/Library/Logs/lbd/viewer.log`; a startup failure also shows an alert. |
| macOS: "LBD Viewer is damaged and can't be opened" | The download was changed on its way, or the app was copied without its signature. Download the disk image again, then approve it as above. |
| A file can't be opened | It may not be an LBD file, or it may be from a newer major format version. The message says which; update the viewer for newer files. |
| "Already open in Page N" | A file is open in one viewer page at a time, so two pages can't hold different unsaved changes. Click **Show it in Page N**, or move the tab there (right-click → **Move to Page N**). See [Several browser tabs](folders-and-files.md#several-browser-tabs). |
| "The move was cancelled (…); the files stay here" | The other page was closed, or didn't take the files within a few seconds (a new browser tab blocked as a pop-up, or closed). Nothing is lost: the tabs stay where they were. Allow pop-ups for the viewer's address to move tabs to a new browser tab. |
| A tab shows 🔒 *now open in Page N* | This page was asleep (a closed laptop) and another page opened the file meanwhile. Close this copy; the file is in Page N. |
| "…was changed since this tab opened it" when saving | Another program, a script, or another computer wrote the file after you opened it. **Overwrite** saves your view anyway (the data stays); **Reload** shows the file as it is now. |
| Double-clicked files don't open in a new browser tab | By default they open as tabs in the viewer page you used last. To get a new browser tab every time, choose it under **⚙**. |
| A single number isn't plotted | Values without axes (e.g. a fitted T1) are listed with their value under **Numbers**, not drawn as a figure. |
| "…your unsaved plot settings were dropped" | The file was written again (by your program, a script, a sync client) while you had changed its plot settings; the tab now shows the new data with the file's own view. Save a view into the file to keep it across runs. See [Files that change](folders-and-files.md#files-that-change). |
| "The file was changed on disk, but the new version can't be read" | The file is still being written, or the program writing it stopped halfway. The tab keeps the previous version and updates when the file is written again. |
| Saving from your program fails: "another program kept it open" (Windows) | Windows can't replace a file another program has open. Saving waits up to 3 seconds; if the file stays open (an image viewer, Excel, a sync client holding it), close it there and save again. LBD Viewer only opens a file for a moment. |
| Port already in use with `--port` | Choose another port, or leave `--port` out to pick a free one. |
