# Build LBD yourself

If you'd rather not run a ready-made installer, build your own from the source. The build makes
the same packages as a release, with the same scripts the release uses (`scripts/build_windows.ps1`,
`build_linux.sh`, `build_macos.sh`, see [Releases](releases.md#building-locally)). A package you
built on your own computer isn't "downloaded", so the system shows none of the warnings it shows
for a downloaded installer.

## 1. The tools

All free. uv brings its own Python, so you don't need to install Python.

| Tool | Needed for | Get it |
|---|---|---|
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | the Python build environment (it downloads Python itself) | every system |
| [Node.js](https://nodejs.org/) (LTS, with npm) | the viewer's web page | every system |
| [Inno Setup 6](https://jrsoftware.org/isinfo.php) | the Windows installer (`ISCC.exe`) | Windows only |
| Git (optional) | getting the source with `git clone` instead of the source zip | every system |
| MATLAB (optional) | `LBD.mltbx`, the MATLAB toolbox; without it the package holds the `+lbd` source folder instead | every system |

On Linux, build on the kind of system you'll install on (or WSL2 on Windows). On a Mac, the build
uses `codesign` and `hdiutil`, which come with macOS. Whether a Mac without Apple's command line
tools (Xcode) builds everything has not been checked yet; `git` asks to install them, so take the
source zip there if you don't have them.

## 2. The source, at a release

Build a released version, not the newest development state: its tag is `vX.Y.Z` (the versions
are on the [release page](https://github.com/patrick-csliu/lbd/releases)).

With Git:

```bash
git clone --branch v2.0.0 https://github.com/patrick-csliu/lbd.git
cd lbd
```

Without Git: on the release page, download **Source code (zip)** (or `.tar.gz`) of that release
and unpack it.

## 3. Build

One command, in the source folder. Each one checks that every version number in the source agrees,
sets up its own environment in the output folder, builds the web page, the app, the language
modules and the Help, and packs them.

=== "Windows"

    In PowerShell:

    ```powershell
    powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
    ```

    Result: `%LOCALAPPDATA%\lbd-build\LBD-Viewer-<version>-windows-x64-setup.exe`.

=== "Linux"

    ```bash
    sh scripts/build_linux.sh
    ```

    Result: `~/.cache/lbd-build/lbd-viewer-<version>-linux-<arch>.tar.gz`.

=== "macOS"

    ```bash
    sh scripts/build_macos.sh
    ```

    Result: `~/Library/Caches/lbd-build/LBD-Viewer-<version>-macos-<arch>.dmg`, for this Mac's
    processor (Apple Silicon or Intel).

A build takes several minutes and needs a few GB in the output folder (outside the source
folder, so nothing large lands in a synced folder). Each system's package is built on that
system: the build can't make another system's package.

## 4. Install the result

As a downloaded one, see [Install](../getting-started/install.md):
- **Windows:** run the setup program.
- **Linux:** unpack the tarball and run `./install.sh`.
- **macOS:** open the disk image and drag **LBD Viewer** to Applications. Built on this Mac, it
  opens without the approval step.

Upgrading, refusing an older version and uninstalling work as with a release's installer.

## The same, but not identical

Your build works the same as the release of the same version: the same program, Help and
language modules. It isn't byte-for-byte the same file, so its checksum differs from the one in
the release's `SHA256SUMS`: build tools put dates and paths into the files, and the versions of
the build tools on your computer can differ from those on GitHub. Without MATLAB, the MATLAB
module is the `+lbd` source folder instead of `LBD.mltbx`
([Install](../getting-started/install.md#matlab)).
