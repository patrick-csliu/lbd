# Command line and settings

## Command line

```
lbd-view [paths...] [--port N] [--no-browser] [--idle-exit SECONDS] [--new] [--dev] [--version]
```

| Argument | Meaning |
|---|---|
| `paths` | `.lbd` files to open, and/or folders to add to the folder panel. If a viewer is already running, files open as tabs in the viewer page you used last (or in new browser tabs, as set under **⚙**); without files, a new browser tab opens. |
| `--port N` | Use this port instead of a free one. |
| `--no-browser` | Print the address instead of opening a browser. |
| `--idle-exit SECONDS` | Stop this long after the last viewer tab closes (default 90). `0` keeps it running. |
| `--new` | Start a separate viewer even if one is running. |
| `--dev` | For development: port 8765, session code `dev`, never stops by itself. |
| `--version` | Print the version. |

On Windows, the installed program is `lbd-view.exe` in the install folder. On Linux,
`install.sh` puts `lbd-view` in `~/.local/bin`. On macOS, it is
`"/Applications/LBD Viewer.app/Contents/MacOS/lbd-view"`, or `lbd-view` after a uv install.

## Where things are stored

| What | Windows | Linux | macOS |
|---|---|---|---|
| Settings: folder list, default preset, the **⚙** settings (`settings.json`) | `%APPDATA%\lbd\` | `~/.config/lbd/` | `~/Library/Application Support/lbd/` |
| Style presets (`styles/<name>.lbd.json`) | `%APPDATA%\lbd\styles\` | `~/.config/lbd/styles/` | `~/Library/Application Support/lbd/styles/` |
| Log of the installed app (`viewer.log`) | `%LOCALAPPDATA%\lbd\Logs\` | none; messages go to the terminal or the desktop session log | `~/Library/Logs/lbd/` (the app); with uv none, messages go to the terminal |
| Running-viewer lock (`server.json`) | `%LOCALAPPDATA%\Temp\lbd\` | `$XDG_RUNTIME_DIR/lbd/` | `~/Library/Caches/TemporaryItems/lbd/` |
| Which folders are expanded in the folder panel | the browser's site storage | the browser's site storage | the browser's site storage |

Uninstalling the viewer asks whether to keep settings and presets (the default is to keep
them). Set the environment variable `LBD_CONFIG_DIR` to use a different settings folder, and
`LBD_RUNTIME_DIR` for a different running-viewer lock (e.g. to run a second, separate copy).
