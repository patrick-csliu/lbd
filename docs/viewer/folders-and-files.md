# Folders and files

## Folders

The folder panel lists folders you choose, and inside them every subfolder and these files:

| Icon | Files | Clicking opens |
|---|---|---|
| ◧ | `.lbd` data files | the file's details and plot |
| ✎ | `.lbd.json` style files | a preview of the style; see [Style files](images-and-style-files.md#style-files) |
| ▣ | images: `.png .jpg .jpeg .gif .bmp .tif .tiff .webp .svg` | the image and its metadata, view only; see [Images](images-and-style-files.md#images) |

Other files are not shown.

| To | Do this |
|---|---|
| Add a folder | **+ Add folder**, then **Browse…** to pick one, or paste a path (for example copied from the Explorer address bar) and press **Add**. Quotes around a pasted path are removed. |
| Remove a folder | The **×** next to its name. It is only removed from the list; no files are deleted. |
| Open or close a folder | Click it, or select it and press Enter. Open folders are remembered in this browser. |
| Close all folders | The **⊟** (collapse all) button. |
| Make the panel wider | Drag its right edge. Double-click the edge to fit the longest name shown. The width is remembered in this browser. With the keyboard: focus the edge (Tab), then ← / →; Home resets it. |
| Find a file | Type in **Filter files in all folders…**. It searches every subfolder of every listed folder for file paths containing the text, ignoring case. At most 500 matches are shown per folder. |
| See new files | The **⟳** (refresh) button rereads the folders. |

Hidden and system folders are skipped:
- names starting with `.`,
- `__pycache__`, `node_modules`, `venv`,
- Synology's `@eaDir`, `#recycle` and `#snapshot`,
- Windows' `$RECYCLE.BIN` and `System Volume Information`.

### Right-click menu

Right-click an item in the panel (or select it and press the Menu key or Shift+F10):

| Item | Menu |
|---|---|
| A listed folder | **Show in Explorer**, **Copy path**, **Remove from list** |
| A subfolder | **Show in Explorer**, **Copy path** |
| A data, style or image file | **Show in Explorer**, **Copy path**, **Rename…**, **Move to Recycle Bin…** |

On macOS the menu says Finder and Trash, on Linux file manager and Trash.

- **Show in Explorer** opens the folder with the file selected.
- **Rename…** asks for the new name. The extension must stay the same (`.lbd`, `.lbd.json`, or
  the image's), so the file stays in the panel; a name that already exists is refused. An open
  tab of the file follows the new name.
- **Move to Recycle Bin…** asks first, then moves the file to the Recycle Bin (Trash), where
  you can restore it. If the drive has no Recycle Bin (some network drives), the file is not
  deleted and you get a message.

Folders can't be renamed or deleted from the viewer.

**Browse…** opens your system's folder dialog. If your system has none (some minimal Linux
installs), paste the path instead.

The viewer can only read files inside the listed folders, and files you open directly by
double-clicking or from the command line.

## Tabs

| Action on a file | Result |
|---|---|
| **Single-click** (or Space) | Opens the file in a *preview tab*, whose name is in italics. For data files it shows the details. The next single-click replaces the preview tab, so browsing doesn't pile up tabs. |
| **Double-click** (or Enter), or the **Plot** button | Keeps the tab; data files are plotted. |

Click a tab to switch to it, double-click a preview tab to keep it, and close a tab with its
**×**. Right-click a tab for **Close**, **Close others** and **Close all**. Each tab keeps its
own plot settings while it is open. Keeping several files in tabs is
a quick way to compare them.

## File details

Under **File contents** you see:
- the description, creation time, writing program, file size and format version;
- a **Values** table: name, label, unit, axes, shape and type;
- an **Axes** table: name, label, unit, number of points, first and last value;
- **Metadata** as a tree; large arrays are summarized.

**Show in folder** opens the file's folder in File Explorer or your file manager, with the file
selected.
