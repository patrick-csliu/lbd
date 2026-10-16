# Saving views and exporting

## Saving a view into the file

**Save this view to the file** stores the current settings inside the `.lbd` file:
- the plot settings (type, values, axes, colour, complex mode, scales, labels, slider positions),
- your style changes (merged with style changes already in the file),
- the chosen preset name.

From then on the file opens like this, on any computer with LBD Viewer, for anyone you send it
to, and with `lbd.plot.plot(path)` in Python. The data itself is never changed.

| Button | Effect |
|---|---|
| **Reset** | Drops your unsaved changes and goes back to the file's saved view, or to the defaults. |
| **Remove saved view** | Deletes the saved plot settings and style changes from the file. It appears only when the file has some. |

The same can be done from code with [`lbd.set_plot`][lbd.set_plot] (Python), or by
setting `plot`/`style`/`style_name` before saving in any language.

## Exporting

**Export: PDF / SVG / PNG / JPG** saves the figure exactly as shown, at its real size. A
**Save as** dialog opens in the data file's folder with the name `<file>_<values>.<format>`
filled in; change the folder or name, or cancel. The dialog asks before replacing a file, and
the name must keep the format's extension. On a system without a save dialog (some minimal
Linux installs) the figure goes to your browser's download folder instead. See
[Exported files](../styles/files-and-export.md#exported-files) for what each format contains.

| Format | Use it for |
|---|---|
| PDF | Papers, theses, LaTeX: sharp at any zoom, fonts embedded |
| SVG | Editing in Inkscape or Illustrator, web pages |
| PNG | Word, PowerPoint, chat and email, at the style's resolution |
| JPG | Only when something insists on JPG. It compresses with loss: thin lines and small text get blurred edges, so the viewer shows a short warning after saving. Prefer PNG. |
