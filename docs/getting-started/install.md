# Install

There are two separate parts:

1. **LBD Viewer**, the app that lists and plots files. It brings its own Python and needs no
   other software.
2. **Language modules**, one per programming language, which let your own programs write and
   read `.lbd` files. You install these yourself, into the environments you use. LBD has
   modules for **Python, MATLAB and Julia** ([below](#language-modules)); more can be added
   ([Adding a language](../developers/adding-a-language.md)).

## LBD Viewer: one command

The quickest way to install or upgrade the viewer is one command, which gets the latest release
from GitHub:

=== "Windows"

    In PowerShell (no administrator rights needed):

    ```powershell
    irm https://github.com/patrick-csliu/lbd/releases/latest/download/install.ps1 | iex
    ```

    It downloads the setup program, checks it, and runs it silently. The shortcuts are those of
    the installer: the Start menu yes, the desktop no, or your earlier choice when upgrading.
    To choose, run it with options:

    ```powershell
    & ([scriptblock]::Create((irm https://github.com/patrick-csliu/lbd/releases/latest/download/install.ps1))) -DesktopShortcut
    ```

    `-DesktopShortcut` adds a desktop shortcut, `-NoStartMenu` leaves out the Start menu one.

=== "Linux"

    ```bash
    curl -fsSL https://github.com/patrick-csliu/lbd/releases/latest/download/install.sh | sh
    ```

    It downloads the package for this computer, checks it, unpacks it and runs its `install.sh`
    (below), which takes the default answers. To choose, add options after `sh -s --`:
    `--desktop` (a desktop shortcut), `--no-menu` (not in the applications menu), `--no-fonts`
    (skip the Arial check). For example `curl -fsSL … | sh -s -- --desktop`.

=== "macOS"

    In Terminal:

    ```bash
    curl -fsSL https://github.com/patrick-csliu/lbd/releases/latest/download/install-macos.sh | sh
    ```

    It downloads the disk image for this Mac (Apple Silicon or Intel), checks it, and copies
    LBD Viewer to Applications, replacing an older one (it refuses to replace a newer one). A
    file downloaded this way usually isn't blocked by macOS the way a browser download is (step
    3 below), but this isn't guaranteed.

**What the scripts check.** Each release has a file `SHA256SUMS` with the SHA-256 checksum of
every file in it. The script downloads it and the installer, and installs only if the
installer's checksum matches; otherwise it stops, says so and deletes the download. This catches
a damaged or changed download; it doesn't prove more than the release page itself does. Each
script says what it is doing and, when it fails, why (no network, a checksum that doesn't match,
no permission). Nothing is left half-installed: the download is deleted at the end, and the
installer runs only when everything is in place. Some lab computers don't allow scripts; then
use the installer from the release page, as below.

Prefer to build the viewer yourself from the source? See
[Build LBD yourself](../developers/build-yourself.md).

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

**Upgrade:** run the installer of the new version. It replaces the old one. A running viewer is
first asked to stop (labels still waiting are written into their files), and stopped by force only
if it hasn't ended after 10 seconds. An installer older than the installed version refuses: see
[Going back to an older version](#going-back-to-an-older-version).

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

**Upgrade:** run `install.sh` of the new version. It stops a running viewer first (gently, as on
Windows) and refuses a version older than the installed one. **Uninstall:** run `./uninstall.sh`
from the unpacked folder, or `~/.local/share/lbd-viewer/uninstall.sh`. It asks whether to keep your presets and settings in `~/.config/lbd`; the
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


## The first start

The first time LBD Viewer starts, it asks a few questions, only those whose answer matters for your
data. It asks until they are answered (closing the page asks again next time); each can be changed
later in Settings.

1. **Your data folders**: the Library lists the data files in them. More can be added later.
2. **Where each folder is kept**: on this computer only; synced with other computers by a sync tool
   (Synology Drive, OneDrive, Dropbox, …); or in the cloud with files kept online only. For a
   folder kept online only, LBD doesn't read each file's details (that would download every
   file); the Library lists names, sizes and dates (Settings → Library → Read each file's details).
3. **For a synced folder: how LBD edits data files** (labels, saved views, ids): *in place* (fast,
   small, but a write cut half-way can damage the file) or *copy and swap* (a complete copy each
   time, safe against a power cut, but a sync tool sends the whole file). Settings → Library → Edit
   data files.
4. **Check online for new versions?** (below). Settings → About.

After an upgrade from an earlier version, with folders already set, only the last question is asked.

## Updates

LBD Viewer tells you when a new version is out, if you allow it (asked at the first start; Settings
→ About → **Check for new versions online**); it never downloads or installs anything by itself.

- **When it checks:** at most once a day, when the viewer starts, while **Check for new versions
  online** is on (a viewer left open overnight doesn't check again). **Check now** in Settings →
  About asks at once, also when it is off. It asks GitHub, in the background, for the latest published release
  (`api.github.com/repos/patrick-csliu/lbd/releases/latest`), waiting at most 5 seconds.
- **What it sends:** only that request, with the program's name and version
  (`User-Agent: LBD-Viewer/<version>`); nothing about your computer, you or your files. It uses
  the system's proxy settings.
- **Without internet** the automatic check is quiet and tries again at the next start.
- **Settings → About** shows what the last check found: *"LBD X is available"* with a link to its
  release page, the [one-line install command](#lbd-viewer-one-command) for your system, and
  **Check now**, which says why when it fails (no connection, a proxy, an unexpected answer).
- **The reminder:** on the first start of a day when a newer version is known, one viewer page
  (only one, when several are open) asks: **Remind later** (again at a start on a later day),
  **Install…** (opens Settings → About) or **Never remind** (not for this version; the next new
  version reminds again, and Settings → About always shows it).

The last check and your choice are kept in the settings (`settings.json`, `updates`).

## Going back to an older version

A new version replaces the old one; no two versions are installed side by side. The Windows and
Linux installers refuse to put an older version over a newer one, with a message such as *"LBD
Viewer 2.1.0 is installed, newer than this installer (2.0.0)"*. To go back: uninstall the newer
version first (Windows Settings → Apps; on Linux `~/.local/share/lbd-viewer/uninstall.sh`), then
run the older installer. A disk image on macOS can't refuse; the older app says so once, at its
first start, and carries on.

Your settings and Library stay when you uninstall, and the older version uses them as far as it
can:

- **Settings:** it reads the settings it knows. Since 2.0.0, settings only a newer version knows
  are kept when an older one saves, so going forward again finds them. Versions before 2.0.0
  write only their own settings: after changing a setting there, the newer version's other
  settings (Library, memory, Explore, …) are back to their defaults.
- **The Library's index** is built again by a version that uses another kind of index.
- **LBD's database** (remembered Explore views, chosen previews): one made by a newer version is
  put aside (`catalog.broken-<time>.sqlite`) and a new one started, and the viewer says so.
- **Labels** are in the data files and the Library's label files, not in the program.

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
