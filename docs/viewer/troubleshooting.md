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
| Port already in use with `--port` | Choose another port, or leave `--port` out to pick a free one. |
