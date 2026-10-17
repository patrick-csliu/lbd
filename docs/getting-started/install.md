# Install

There are two separate parts:

1. **LBD Viewer**, the app that lists and plots files. It brings its own Python and needs no
   other software.
2. **Language modules**, one per programming language, which let your own programs write and
   read `.lbd` files. You install these yourself, into the environments you use. LBD has
   modules for **Python, MATLAB and Julia** ([below](#language-modules)); more can be added
   ([Adding a language](../developers/adding-a-language.md)).

## LBD Viewer on Windows

1. Run `LBD-Viewer-<version>-windows-x64-setup.exe`. No administrator rights are needed; it installs for
   your user only.
2. Choose the shortcuts: **Add LBD Viewer to the Start menu** (ticked by default) and **Create a
   desktop shortcut** (not ticked). An upgrade remembers your choice.
3. Optionally tick **Open LBD Viewer now** at the end.

The installer:
- puts the viewer in `%LOCALAPPDATA%\Programs\LBDViewer`;
- adds the shortcuts you chose (the uninstaller removes them);
- makes double-clicking `.lbd` files open the viewer;
- puts the language modules in `%LOCALAPPDATA%\Programs\LBDViewer\sdk`.

**Upgrade:** run the installer of the new version. It replaces the old one, closing a running
viewer first if needed.

**Uninstall:** Windows Settings → Apps → **LBD Viewer** → Uninstall. This removes the program
and the `.lbd` file association. When it starts, it asks whether to keep your presets and
settings (including the list of folders) in `%APPDATA%\lbd` for a later installation. The default
is **Yes**, keep them; **No** moves them to the Recycle Bin, where you can restore them.

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

`install.sh` asks two questions: **Show LBD Viewer in the applications menu? [Y/n]** and **Add a
shortcut to the desktop? [y/N]** (Enter takes the capital letter, the default). Run without a
terminal (in a script), it takes the defaults. Then it:
- puts the viewer in `~/.local/share/lbd-viewer`;
- links the `lbd-view` command into `~/.local/bin`;
- adds the shortcuts you chose. Without the menu entry, double-clicking `.lbd` files still
  works: the entry is installed but hidden from the menu;
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
unpacked folder. It asks whether to keep your presets and settings in `~/.config/lbd`; the
default is to keep them, and otherwise they go to the desktop's trash when there is one.

Requirements: a 64-bit Linux desktop with a web browser. The file association and menu entry
use the standard freedesktop tools (`xdg-mime`, `update-mime-database`), which desktop
distributions include.

## LBD Viewer on macOS

1. **Download** the disk image for your Mac from the release on GitHub. Apple menu → **About This
   Mac**: "Chip: Apple M…" needs `LBD-Viewer-<version>-macos-arm64.dmg`, "Processor: Intel" needs
   `LBD-Viewer-<version>-macos-x86_64.dmg`.
2. **Install:** open the disk image and drag **LBD Viewer** onto **Applications**.
3. **The first start needs your approval once.** LBD Viewer isn't signed by an Apple-registered
   developer (that costs a yearly fee), so macOS first blocks it: *"Apple could not verify 'LBD
   Viewer' is free of malware…"*. Click **Done**, then open **System Settings → Privacy &
   Security**, scroll down to *"LBD Viewer was blocked…"*, click **Open Anyway** and enter your
   password. In Terminal, this does the same:
   ```bash
   xattr -dr com.apple.quarantine "/Applications/LBD Viewer.app"
   ```
   After each update, approve the new version the same way.

After that, double-clicking a `.lbd` file opens it in LBD Viewer, in your browser. There are no
shortcut questions on the Mac: LBD Viewer is in Launchpad and Spotlight once it is in
Applications. For a Dock icon, drag it from Applications onto the Dock. The app shows
in the Dock while it runs; it quits with ⌘Q, or by itself 90 seconds after the last viewer tab
is closed.

| Task | How |
|---|---|
| Upgrade | Drag the new **LBD Viewer** onto **Applications** and replace the old one, then approve it once (step 3). |
| Uninstall | Drag **LBD Viewer** from Applications to the Trash. Your presets and settings in `~/Library/Application Support/lbd` are kept; delete that folder to remove them too. |

Requirements: macOS 14 (Sonoma) or newer, on an Apple Silicon or Intel Mac.

### Without the app: Python packages

The viewer also installs as a Python package with [uv](https://docs.astral.sh/uv/), which puts it
in its own environment, with its own Python, and adds the `lbd-view` command, without the app
icon and double-clicking. macOS doesn't ask for approval then, because it isn't a "downloaded
app". This works on Windows and Linux too, for anyone who prefers Python packages to the
installer.

Requirements: uv (`brew install uv`, or see its
[installation page](https://docs.astral.sh/uv/getting-started/installation/)). You don't need to
install Python: uv downloads the version the viewer is tested with.

1. From the release on GitHub, download both wheels into one folder:
   `lbd_viewer-<version>-py3-none-any.whl` and `lbd-<version>-py3-none-any.whl`.
2. In Terminal, in that folder:
   ```bash
   uv tool install --python 3.12 ./lbd_viewer-<version>-py3-none-any.whl --with ./lbd-<version>-py3-none-any.whl
   ```
   `--python 3.12` keeps the viewer on the Python it is tested with: the newest Python versions
   can lack ready-made packages of its dependencies (h5py) for a while. The `lbd` module comes from
   the second file, not from the internet (the viewer needs exactly this version).
3. Start it with `lbd-view`, or `lbd-view ~/Data/measurements` to add a folder. It opens in your
   browser, with Help and the Language modules page like the installed app. If the command isn't
   found, run `uv tool update-shell` once and open a new Terminal window.

| Task | Command |
|---|---|
| Upgrade | the same `uv tool install` command with the new files, plus `--force` |
| Uninstall | `uv tool uninstall lbd-viewer`. Your presets and settings in `~/Library/Application Support/lbd` are kept; delete that folder to remove them too. |


## Language modules

The easiest way is the viewer's **Language modules** page. It shows these commands with the
correct paths for your computer already filled in, plus a check command, an example and the
uninstall command.

`<sdk>` below means the `sdk` folder of the installed viewer:
- Windows: `%LOCALAPPDATA%\Programs\LBDViewer\sdk`
- Linux: `~/.local/share/lbd-viewer/sdk`
- macOS: `/Applications/LBD Viewer.app/Contents/Resources/sdk` (with uv: inside the
  installed package; the Language modules page shows the path)

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
