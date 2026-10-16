# Building releases

1. **Set one version everywhere.** `uv run python scripts/check_versions.py` prints the version,
   or fails and lists the files that differ. Versions live in:
   - the viewer: `viewer/pyproject.toml`, `viewer/src/lbd_viewer/__init__.py` and
     `viewer/web/package.json`;
   - each language: the files listed under `[[version]]` in its `language.toml`.
2. **Run** `uv run python scripts/test_all.py`.
3. **Windows**, on Windows with Inno Setup 6:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
   ```
   This produces `%LOCALAPPDATA%\lbd-build\LBDViewer-Setup-<version>.exe`. Options:
   - `-OutDir <dir>`;
   - `-Skip <id>,<id>`: don't run those languages' SDK build step; ship their `fallback_copy`
     files instead, e.g. `-Skip matlab` ships the `+lbd` sources instead of `LBD.mltbx`;
   - `-SkipInstaller`: the app folder only.
4. **Linux**, on Linux or WSL2 with uv and Node.js:
   ```bash
   sh scripts/build_linux.sh [OUTDIR]
   ```
   This produces `~/.cache/lbd-build/lbd-viewer-<version>-linux-<arch>.tar.gz`.
   PyInstaller can't cross-compile, so each platform is built on itself.

Both scripts run the same steps:
1. check versions;
2. `uv sync --all-packages --group docs` into a build environment inside the output folder;
3. build the web UI;
4. make the icons;
5. run PyInstaller (`packaging/lbd-view.spec`, entry `packaging/entry.py`);
6. stage the SDK (`packaging/stage_sdk.py`);
7. build the documentation (`mkdocs build --strict`) into `<app>/docs`, the viewer's Help;
8. package.

`stage_sdk.py` fills `<app>/sdk/<id>/` for every discovered language, following the `[sdk]`
section of its manifest:
- it runs `build`, e.g. the Python wheel or `LBD.mltbx`;
- or, when the build tool is missing or the language is skipped, copies `fallback_copy`;
- it copies `copy`, e.g. the Julia package sources;
- it always copies `language.toml`, the example file and `README.md`.

The spec and a README go into `<app>/sdk/` itself.

The Windows installer (`packaging/windows/LBDViewer.iss`):
- installs per user with no admin rights;
- registers `.lbd` under `HKCU\Software\Classes`;
- keeps a fixed `AppId` so upgrades replace older versions. **Never change it.**
- doesn't ask "folder exists, install anyway?" (`DirExistsWarning=no`): the folder is its own;
- removes the whole install folder on uninstall, so no empty folder is left behind;
- asks when an uninstall starts (step `usUninstall`, before anything is removed) whether to
  remove the presets and settings (`%APPDATA%\lbd`) and the logs (`%LOCALAPPDATA%\lbd`);
  **No** is the default, **Yes** moves them to the Recycle Bin (never a permanent delete), and a
  silent uninstall keeps them;
- shows a note after installing if Arial, the default style's font, is missing.

The Linux `install.sh` checks for Arial too and offers to install it with the system's core
fonts package (`--no-fonts` skips this); `uninstall.sh` asks about the settings like Windows.

The Linux scripts are in `packaging/linux/`: `install.sh`, `uninstall.sh`, the `.desktop` entry
and the MIME type definition. The MIME type is defined by the `*.lbd` file pattern, so `.lbd`
files are recognized even though they are HDF5 inside.

Packaging gotcha: matplotlib picks its output backends by name at save time, so
`packaging/lbd-view.spec` lists `backend_svg`/`backend_pdf`/`backend_agg` as hidden imports.
Without them, the frozen app can't render.
