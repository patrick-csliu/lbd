# Releases

## How to release

GitHub builds every release; you choose the version and click **Publish**. Nothing becomes
public before that click.

| Step | Who | What |
|---|---|---|
| 1. Write the notes | you | Every change has a line in `CHANGELOG.md` under the top heading, `## Unreleased` (or `## <version> (in development)`). If the viewer's look changed, redo the documentation's screenshots: `uv run python scripts/make_screenshots.py` (on Windows, with Chromium for Playwright), look at them, and commit them. `tests/scripts/test_screenshots.py` checks that every shot is used and every image exists. |
| 2. Set the version | you | `uv run python scripts/bump_version.py 0.2.0`: writes the version into every place `check_versions.py` reads (the viewer, each language's `[[version]]` files, `uv.lock`, `package-lock.json`) and heads the CHANGELOG section `## 0.2.0 (<date>)`. Refuses a lower or malformed version and a missing or empty section. `--dry-run` shows the changes only. |
| 3. Test | you | `uv run python scripts/test_all.py` |
| 4. Tag and push | you | `git commit -am "Release 0.2.0"`, `git tag -a v0.2.0 -m "LBD 0.2.0"`, `git push --follow-tags`. The tag must be annotated (`-a`): `--follow-tags` doesn't push plain tags. |
| 5. Build and check | GitHub | The **Release** workflow (`.github/workflows/release.yml`) starts from the tag: it checks that the tag matches the files and that the CHANGELOG has the section, runs all tests, builds `LBD.mltbx` with MATLAB, then the Windows installer, the macOS app for Apple Silicon and Intel (`scripts/build_macos.sh`), the Linux package and the Python wheels (`scripts/build_wheels.py`). Each is checked with `scripts/smoke_test_app.py --release`: the Windows installer is installed silently, checked, and uninstalled (settings must stay); the macOS app is checked, its disk image opened, and a `.lbd` file opened the way Finder does (`open -a`) before the app is quit; the Linux package is unpacked and checked; the wheels are installed on macOS with `uv tool install`, exactly as the install guide says, and checked. |
| 6. Draft | GitHub | A **draft** release "LBD 0.2.0" with `LBD-Viewer-0.2.0-windows-x64-setup.exe`, `LBD-Viewer-0.2.0-macos-arm64.dmg` and `…-macos-x86_64.dmg`, `lbd-viewer-0.2.0-linux-x86_64.tar.gz`, `LBD.mltbx`, and the two wheels `lbd-0.2.0-py3-none-any.whl` and `lbd_viewer-0.2.0-py3-none-any.whl` (the viewer with its Help and language modules, for macOS and anyone with Python); its text is the CHANGELOG section. Only people with write access see drafts. |
| 7. Check | you | GitHub → **Releases** → the draft: download the installer, try it, edit the text if needed. |
| 8. Publish | you | **Publish release**. Now it's public and marked *Latest*. |

**When something fails:** nothing is published. The run is red under **Actions**; the failing
test suite and its output show as annotations on the run's page. Fix it, commit, and either move
the tag (`git tag -f v0.2.0`, `git push -f origin v0.2.0`) or release the next version. A new
run replaces the earlier *draft* of the same version; a *published* release is never replaced.

**Try it without releasing:** Actions → **Release** → **Run workflow**. It builds the version in
the files (no tag needed; the CHANGELOG section may still be "in development") and makes a draft
titled "LBD <version> (trial build)". Look at it, then delete the draft.

Versions are `X.Y.Z` only: Python, npm and Julia write pre-release versions differently, so
there are no release candidates.

`scripts/smoke_test_app.py --exe <app>/lbd-view[.exe] [--release]` also checks a build on your own
computer: it starts the viewer with empty settings and the example data, then checks the version,
the folder listing, a plot, PDF and PNG export, and with `--release` the Help pages and that every
language module is complete.

## Building locally

The same build steps as on GitHub, for trying a change to the packaging:

1. **Check the versions.** `uv run python scripts/check_versions.py` prints the version, or
   fails and lists the places that differ: the viewer (`viewer/pyproject.toml`,
   `viewer/src/lbd_viewer/__init__.py`, `viewer/web/package.json`), the lock files (`uv.lock`,
   `viewer/web/package-lock.json`), and the files under `[[version]]` in each language's
   `language.toml`.
2. **Run** `uv run python scripts/test_all.py`.
3. **Windows**, on Windows with Inno Setup 6:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
   ```
   This produces `%LOCALAPPDATA%\lbd-build\LBD-Viewer-<version>-windows-x64-setup.exe`. Options:
   - `-OutDir <dir>`;
   - `-Skip <id>,<id>`: don't run those languages' SDK build step; ship their `fallback_copy`
     files instead, e.g. `-Skip matlab` ships the `+lbd` sources instead of `LBD.mltbx`;
   - `-Prebuilt matlab=<dir>`: use the files in `<dir>` (e.g. an `LBD.mltbx` built elsewhere)
     instead of running that language's build step;
   - `-SkipInstaller`: the app folder only.
4. **Linux**, on Linux or WSL2 with uv and Node.js:
   ```bash
   sh scripts/build_linux.sh [OUTDIR]
   ```
   `LBD_PREBUILT="matlab=<dir>"` does what `-Prebuilt` does on Windows.
   This produces `~/.cache/lbd-build/lbd-viewer-<version>-linux-<arch>.tar.gz`.
5. **macOS**, on a Mac with uv and Node.js:
   ```bash
   sh scripts/build_macos.sh [OUTDIR]
   ```
   This produces `~/Library/Caches/lbd-build/LBD-Viewer-<version>-macos-<arch>.dmg` for the
   Mac's own processor (arm64 or x86_64). The app bundle (`packaging/lbd-view.spec`) declares the
   `.lbd` file type; `lbd_viewer/macapp.py` receives the files Finder opens. After adding Help
   and the language modules to `Contents/Resources`, the script signs the app again "ad-hoc"
   (Apple Silicon refuses unsigned apps) and checks with `scripts/macos_min_version.py` that no
   bundled library needs a newer macOS than the app declares (`MACOS_MIN` in the spec).

PyInstaller can't cross-compile, so each platform is built on itself.

The scripts run the same steps:
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
- or, with `--prebuilt <id>=<dir>`, copies the files in `<dir>` instead;
- or, when the build tool is missing or the language is skipped, copies `fallback_copy`;
- it copies `copy`, e.g. the Julia package sources;
- it always copies `language.toml`, `LICENSE`, the example file and `README.md`.

The spec and a README go into `<app>/sdk/` itself.

The Windows installer (`packaging/windows/LBDViewer.iss`):
- installs per user with no admin rights;
- registers `.lbd` under `HKCU\Software\Classes`;
- keeps a fixed `AppId` so upgrades replace older versions. **Never change it.**
- doesn't ask "folder exists, install anyway?" (`DirExistsWarning=no`): the folder is its own;
- removes the whole install folder on uninstall, so no empty folder is left behind;
- asks when an uninstall starts (step `usUninstall`, before anything is removed) whether to
  keep the presets and settings (`%APPDATA%\lbd`) and the logs (`%LOCALAPPDATA%\lbd`);
  **Yes** (keep) is the default, **No** moves them to the Recycle Bin (never a permanent
  delete), and a silent uninstall keeps them;
- shows a note after installing if Arial, the default style's font, is missing.

The Linux `install.sh` checks for Arial too and offers to install it with the system's core
fonts package (`--no-fonts` skips this); `uninstall.sh` asks about the settings like Windows.

The Linux scripts are in `packaging/linux/`: `install.sh`, `uninstall.sh`, the `.desktop` entry
and the MIME type definition. The MIME type is defined by the `*.lbd` file pattern, so `.lbd`
files are recognized even though they are HDF5 inside.

Packaging gotcha: matplotlib picks its output backends by name at save time, so
`packaging/lbd-view.spec` lists `backend_svg`/`backend_pdf`/`backend_agg` as hidden imports.
Without them, the frozen app can't render.
