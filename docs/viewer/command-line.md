# Command line and settings

## Command line

```
lbd-view [paths...] [--port N] [--no-browser] [--idle-exit SECONDS] [--new] [--dev] [--version]
```

| Argument | Meaning |
|---|---|
| `paths` | `.lbd` files to open (one browser tab each), and/or folders to add to the folder panel. |
| `--port N` | Use this port instead of a free one. |
| `--no-browser` | Print the address instead of opening a browser. |
| `--idle-exit SECONDS` | Stop this long after the last viewer tab closes (default 90). `0` keeps it running. |
| `--new` | Start a separate viewer even if one is running. |
| `--dev` | For development: port 8765, session code `dev`, never stops by itself. |
| `--version` | Print the version. |

On Windows, the installed program is `lbd-view.exe` in the install folder. On Linux,
`install.sh` puts `lbd-view` in `~/.local/bin`.

## Where things are stored

| What | Windows | Linux |
|---|---|---|
| Settings: folder list, default preset (`settings.json`) | `%APPDATA%\lbd\` | `~/.config/lbd/` |
| Style presets (`styles/<name>.json`) | `%APPDATA%\lbd\styles\` | `~/.config/lbd/styles/` |
| Log of the installed app (`viewer.log`) | `%LOCALAPPDATA%\lbd\Logs\` | none; messages go to the terminal or the desktop session log |
| Running-viewer lock (`server.json`) | `%LOCALAPPDATA%\Temp\lbd\` | `$XDG_RUNTIME_DIR/lbd/` |
| Which folders are expanded in the folder panel | the browser's site storage | the browser's site storage |

Uninstalling the viewer keeps settings and presets. Delete the settings folder yourself to
remove them. Set the environment variable `LBD_CONFIG_DIR` to use a different settings folder.
