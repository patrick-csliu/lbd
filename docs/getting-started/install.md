# Install

There are two separate parts:

1. **LBD Viewer**, the app that lists and plots files. On Windows and Linux it brings its own
   Python and needs no other software; on macOS it's installed as a Python package.
2. **Language modules** for Python, MATLAB and Julia, which let your own programs write and
   read `.lbd` files. You install these yourself, into the environments you use.

## LBD Viewer on Windows

1. Run `LBDViewer-Setup-<version>.exe`. No administrator rights are needed; it installs for
   your user only.
2. Optionally tick **Open LBD Viewer now** at the end.

The installer:
- puts the viewer in `%LOCALAPPDATA%\Programs\LBDViewer`;
- adds **LBD Viewer** to the Start menu;
- makes double-clicking `.lbd` files open the viewer;
- puts the language modules in `%LOCALAPPDATA%\Programs\LBDViewer\sdk`.

**Upgrade:** run the installer of the new version. It replaces the old one, closing a running
viewer first if needed.

**Uninstall:** Windows Settings → Apps → **LBD Viewer** → Uninstall. This removes the program
and the `.lbd` file association. When it starts, it asks whether to also remove your presets and
settings (including the list of folders) in `%APPDATA%\lbd`. The default is **No**, so they are
kept for a later installation; **Yes** moves them to the Recycle Bin, where you can restore them.

Requirements: 64-bit Windows 10 or 11.

## LBD Viewer on Linux

1. Unpack the archive:
   ```bash
   tar xzf lbd-viewer-<version>-linux-x86_64.tar.gz
   ```
2. Run the installer for your user. No root is needed:
   ```bash
   cd lbd-viewer-<version>-linux-x86_64 && ./install.sh
   ```

`install.sh`:
- puts the viewer in `~/.local/share/lbd-viewer`;
- links the `lbd-view` command into `~/.local/bin`;
- adds **LBD Viewer** to the applications menu;
- registers the file type `application/x-lbd` for `*.lbd` files and makes the viewer its
  default app.

The language modules are in `~/.local/share/lbd-viewer/sdk`.

If `~/.local/bin` is not on your `PATH`, the installer says so. You can still start the viewer
from the menu.

**Fonts.** LBD's default style uses Arial, and figures can only be drawn with fonts that are
installed. Most Linux systems don't have Arial, so `install.sh` checks and, if it's missing,
offers to install it with the system's core fonts package (this needs `sudo`, and you accept
Microsoft's licence for the fonts). To do it yourself:

```bash
sudo apt-get install ttf-mscorefonts-installer      # Debian, Ubuntu
```

openSUSE: `sudo zypper install fetchmsttfonts`; Arch: `ttf-ms-fonts` from the AUR; Fedora: the
`msttcore-fonts-installer` package from mscorefonts2.sourceforge.net. Or choose another font for
the default style on the Styles page, e.g. DejaVu Sans, which is always available.
`./install.sh --no-fonts` skips the check.

**Upgrade:** run `install.sh` of the new version. **Uninstall:** run `./uninstall.sh` from the
unpacked folder. It asks whether to also remove your presets and settings in `~/.config/lbd`;
the default is to keep them, and removed ones go to the desktop's trash when there is one.

Requirements: a 64-bit Linux desktop with a web browser. The file association and menu entry
use the standard freedesktop tools (`xdg-mime`, `update-mime-database`), which desktop
distributions include.

## LBD Viewer on macOS

There is no Mac app yet. On a Mac, install the viewer as a Python package with
[pipx](https://pipx.pypa.io/), which puts it in its own environment and adds the `lbd-view`
command. This works on Windows and Linux too, for anyone who prefers Python packages to the
installer.

Requirements: Python 3.10 or newer (from [python.org](https://www.python.org/downloads/) or
Homebrew) and pipx (`brew install pipx`, or `python3 -m pip install --user pipx`, then
`pipx ensurepath`).

1. From the release on GitHub, download both wheels into one folder:
   `lbd_viewer-<version>-py3-none-any.whl` and `lbd-<version>-py3-none-any.whl`.
2. In Terminal, in that folder:
   ```bash
   pipx install ./lbd_viewer-<version>-py3-none-any.whl --preinstall ./lbd-<version>-py3-none-any.whl
   ```
   The `lbd` module comes from the second file, not from the internet (the viewer needs exactly
   this version).
3. Start it with `lbd-view`, or `lbd-view ~/Data/measurements` to add a folder. It opens in your
   browser, with Help and the Language modules page like the installed app.

| Task | Command |
|---|---|
| Upgrade | the same `pipx install` command with the new files, plus `--force` |
| Uninstall | `pipx uninstall lbd-viewer`. Your presets and settings in `~/Library/Application Support/lbd` are kept; delete that folder to remove them too. |

Not yet on macOS: an app icon in Applications and opening `.lbd` files by double-clicking.
macOS doesn't ask for permission to run it, because it isn't an app downloaded from the internet.

## Language modules

The easiest way is the viewer's **Language modules** page. It shows these commands with the
correct paths for your computer already filled in, plus a check command, an example and the
uninstall command.

`<sdk>` below means the `sdk` folder of the installed viewer:
- Windows: `%LOCALAPPDATA%\Programs\LBDViewer\sdk`
- Linux: `~/.local/share/lbd-viewer/sdk`
- macOS (pipx): inside the installed package; the Language modules page shows the path

### Python

Requirements: Python 3.9 or newer. `numpy` and `h5py` are installed if missing.

Run the install in **every** environment (venv, conda env, Jupyter kernel) that should read or
write `.lbd` files. Add `[plot]` to also get [`lbd.plot`](../python/plotting.md): figures
with the viewer's styles from Python. It installs matplotlib, pydantic and platformdirs too.
On Linux, the default style's font Arial may be missing; see [Fonts](#lbd-viewer-on-linux) above.

```bash
pip install "<sdk>/python/lbd-<version>-py3-none-any.whl[plot]"
```

Only reading and writing files, without plotting:

```bash
pip install "<sdk>/python/lbd-<version>-py3-none-any.whl"
```

In a Jupyter notebook cell, use `%pip install "...whl[plot]"` instead.

| Task | Command |
|---|---|
| Check | `python -c "import lbd; print(lbd.version())"`, and for plotting `python -c "import lbd.plot as lp; print(lp.list_styles())"` |
| Upgrade | `pip install --upgrade "<sdk>/python/lbd-<new version>-py3-none-any.whl[plot]"` |
| Uninstall | `pip uninstall lbd` |

Installing the module adds only `numpy` and `h5py`. The viewer's own packages (web server,
matplotlib) are not installed into your environment.

### MATLAB

Requirements: MATLAB R2021b or newer. No toolboxes are needed.

Double-click `<sdk>/matlab/LBD.mltbx`, or run in MATLAB:

<!-- no-check -->
```matlab
matlab.addons.toolbox.installToolbox("<sdk>/matlab/LBD.mltbx")
```

| Task | Command |
|---|---|
| Check | `lbd.version()` |
| Upgrade | Install the `LBD.mltbx` of the new version; it replaces the old one. |
| Uninstall | Home → Add-Ons → Manage Add-Ons → LBD → Uninstall, or `t = matlab.addons.toolbox.installedToolboxes; matlab.addons.toolbox.uninstallToolbox(t(strcmp({t.Name}, "LBD")))` |

If the viewer was built without MATLAB, `<sdk>/matlab` contains the `+lbd` source folder instead
of `LBD.mltbx`. Add it to the path with `addpath("<sdk>/matlab"); savepath`.

### Julia

Requirements: Julia 1.9 or newer. HDF5.jl, JSON3.jl and OrderedCollections.jl are installed if
missing.

Run this in the Julia environment (project) where you want to use LBD:

<!-- no-check -->
```julia
using Pkg; Pkg.develop(path="<sdk>/julia")
```

| Task | Command |
|---|---|
| Check | `using LBD; LBD.version()` |
| Upgrade | `Pkg.develop` links to the folder, so installing a new viewer version updates the module. Restart Julia to load it. |
| Uninstall | `using Pkg; Pkg.rm("LBD")` |

### Without the viewer: from the source repository

On a computer that only records data, you can install the modules straight from a copy of the
repository:

| Language | Command |
|---|---|
| Python | `pip install "<repo>/languages/python[plot]"` or `pip install "lbd[plot] @ git+<repo URL>#subdirectory=languages/python"` |
| Julia | `Pkg.develop(path="<repo>/languages/julia")` or `Pkg.add(url="<repo URL>", subdir="languages/julia")` |
| MATLAB | `addpath("<repo>/languages/matlab"); savepath` |

## Versions

The viewer and the three modules of one release share one version number. Files record their
format version (`1.0`), and the modules handle files from other versions like this:

- Files from older module versions are always readable.
- Files with a newer **minor** format version are read, with a warning.
- Files with a newer **major** format version are refused with a message to update.

Install the modules from the same release as your viewer. The version is shown on the viewer's
Language modules page.
