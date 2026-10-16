# Style files and export

## Style files

A style file is the complete style as JSON, named `<name>.lbd.json`:

```json
{
  "lbd_style": 2,
  "name": "thesis",
  "description": "Thesis figures, serif text, 120 mm wide",
  "figure": {"width_mm": 120, "height_mm": 80, "dpi": 300, "font": {"family": "DejaVu Serif"}, "axes": {"...": "..."}},
  "quantities": {}
}
```

- **Viewer, Styles page:** **Export .lbd.json** downloads the selected preset as a file;
  **Import…** adds a file as a new preset (you choose its name; an existing preset is never
  overwritten).
- **Folder panel:** `.lbd.json` files in your folders are listed with a ✎ icon. Clicking one
  previews it on an open data file; **Import as preset** adds it.
- **Python:** `lbd.plot.load_style("thesis.lbd.json")`, `Style.load(path)`, `style.save(path)`.
  See [lbd.plot](../python/plotting.md).

Keep the style file of a paper next to its data, so anyone can make the figures again exactly.
Files may also be partial (only some keys); missing keys use the defaults.

## matplotlib `.mplstyle` export

**Export .mplstyle** on the Styles page (or `style.to_mplstyle()` in Python) writes the style
in matplotlib's own format. Anyone with matplotlib, even without LBD, then gets the same figure
size, fonts, frame, ticks, colours and line widths:

```python
import matplotlib.pyplot as plt
plt.style.use("thesis.mplstyle")
```

The parts of a style that matplotlib has no setting for are not included:
- unit format and unit prefixes,
- fixed scales per quantity,
- colour bar size,
- scatter marker size and opacity,
- legend `max_entries`,
- different label sizes for x and y.

Use `lbd.plot` to get those too.

## Exported files

Exports use exactly the same drawing code as the screen.

| Format | Contents |
|---|---|
| **PDF** | Vector lines and text, fonts embedded (TrueType), as journals require. Heat-map pixels and dense scatter are embedded as images at `figure.dpi`. Size is exactly `width_mm × height_mm`. |
| **SVG** | Vector; text as outlines, so it looks the same everywhere without the fonts installed. Good for editing in Inkscape or Illustrator. |
| **PNG** | Raster at `figure.dpi`, exactly `width_mm × height_mm` (85 mm at 600 dpi is about 2007 px). The dpi is stored in the file, so other programs know its printed size. |

Each export records its creator (`LBD viewer <version> (matplotlib <version>)`) and the data
file's title. The viewer's image view shows this information for PNG and SVG files. Figures
are never cropped automatically, so the printed size is exactly what the style says.
