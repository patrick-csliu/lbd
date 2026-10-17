# LBD Viewer

LBD Viewer lists the `.lbd` files in your folders and plots them. It also shows your figures
and style files. It runs on your own computer and shows its window in your web browser.
Nothing is uploaded anywhere.

## Starting the viewer

- **Double-click an `.lbd` file** in File Explorer (Windows) or your file manager (Linux). The
  viewer opens it in a new browser tab.
- **Start menu / applications menu / desktop shortcut → LBD Viewer** opens the viewer without
  a file, in a new browser tab, also when the viewer already runs. (The viewer can't bring an
  open browser tab to the front: browsers don't allow it.)
- **Command line:** `lbd-view`, `lbd-view file.lbd` or `lbd-view some/folder`; see
  [Command line](command-line.md#command-line).

Only one copy of the viewer runs at a time. Opening more files adds browser tabs to the same
viewer.

## How it runs

- The viewer is a small web server on your computer. It only accepts connections from this
  computer (`127.0.0.1`).
- Each start creates a random **session code**. It is part of the address the viewer opens and
  is required for every request. This stops other web pages in your browser from reading your
  files through the viewer. As a result, a bookmarked address only works while that viewer is
  running.
- **Single instance:** a second start (for example double-clicking another file) hands the
  file to the running viewer and opens a new tab, instead of starting a second server.
- **Automatic shutdown:** open tabs tell the viewer every 10 seconds that they are still there.
  About 90 seconds after the last tab closes, the viewer stops by itself. If no tab connects at
  all after a start, it waits at least 60 seconds first.

## The window

**⚙** at the top right holds two settings, saved for every viewer tab and the next start:
- **Files opened from Explorer / Finder:** in the open viewer, or in a new browser tab (see
  [Several browser tabs](folders-and-files.md#several-browser-tabs)).
- **Theme:** **System** follows the light or dark mode of Windows, macOS or Linux, also when it
  changes while the viewer is open; **Light** and **Dark** stay as chosen. Figures always stay on
  white, because they are print figures. The Help pages have their own light/dark switch.

The top bar switches between the viewer's pages:

| Page | What it does |
|---|---|
| **Data** | The folder panel and the open files: [Folders and files](folders-and-files.md), [Plotting](plotting.md), [Saving views and exporting](saving-and-exporting.md). |
| **Styles** | Create and edit style presets, and choose the default one: [Styles page](styles-page.md). |
| **Language modules** | How to install the Python, MATLAB and Julia modules on this computer: [Language modules page](language-modules.md). |
| **Help** | Opens this documentation in a new tab. It is part of the viewer, so it works without internet. |

Small **?** buttons next to the plot controls, on the Styles page and on the Language modules
page open the matching page of this documentation.
