# Style settings

Every setting of a style, grouped like matplotlib's objects: Figure → Axes → frame, axis,
legend, …. The tables are generated from the code (`lbd.plot.style`), so they always match what
LBD Viewer, `.lbd.json` files and `lbd.plot` accept.

In a style file or dict, a setting's path is its group path plus its name. For example, the tick
direction is `figure.axes.axis.ticks.direction`:

```json
{"figure": {"axes": {"axis": {"ticks": {"direction": "out"}}}}}
```

!!! tip "Empty means automatic"
    Settings shown as *automatic* are empty by default. They follow another setting, as the
    Meaning column says (for example, the tick label size follows the font size).

## Figure

`figure` — matplotlib's Figure: the whole image, including labels and colour bar.

{{ style_table("FigureStyle") }}

The default, 85 mm × 64 mm, is one column of an APS or AIP journal; 170 mm is the full page
width (see [the default style](index.md#the-default-style-and-journal-rules)). `dpi` is matplotlib's
`savefig.dpi`: it sets the resolution of PNG exports, and of raster parts (heat-map pixels,
dense scatter) inside PDF/SVG.

### Font

`figure.font` — text of the whole figure.

{{ style_table("FontStyle") }}

The default font is Arial (on Windows and macOS). DejaVu Sans and DejaVu Serif ship with
matplotlib, so they look identical on every computer. Any other installed font works too.

The font must be installed on the computer that draws the figure. If it isn't, drawing stops
with an error that names the fonts you can use instead (DejaVu Sans, DejaVu Serif, similar
installed fonts, or the generic `serif` / `sans-serif` / `monospace`). The figure is never drawn
quietly with a different font. Loading or editing a style with a missing font is fine; only
drawing needs it. Fonts are embedded in PDF exports.

## Axes

`figure.axes` — matplotlib's Axes, the plotting area.

{{ style_table("AxesStyle") }}

### Frame

`figure.axes.frame` — the four spines around the plotting area.

{{ style_table("FrameStyle") }}

For an open frame, set `top` and `right` to `false`, and `axis.ticks.mirror` to `false`.

### Title

`figure.axes.title` — shown when a plot spec has a `title`.

{{ style_table("TitleStyle") }}

### Axis: label and ticks

`figure.axes.axis` — both the x and the y axis. It has three parts.

{{ style_table("AxisStyle") }}

`axis.label` — the axis title, e.g. "Frequency (GHz)". The unit formats write it as
`Frequency (GHz)`, `Frequency [GHz]` or `Frequency / GHz`; see also
[unit prefixes](scales-and-units.md#unit-prefixes).

{{ style_table("LabelStyle") }}

`axis.ticks` — major ticks and their numbers.

{{ style_table("TicksStyle") }}

`axis.minor` — minor ticks.

{{ style_table("MinorTicksStyle") }}

**One axis different.** `figure.axes.xaxis` and `figure.axes.yaxis` take the same keys as
`axis`, but only the ones that differ for that axis. For example, outward ticks on the y axis
only:

```json
{"figure": {"axes": {"yaxis": {"ticks": {"direction": "out"}}}}}
```

On the Styles page these are the **x axis only** and **y axis only** sections. Empty fields
there show the shared value they inherit.

### Grid

`figure.axes.grid`

{{ style_table("GridStyle") }}

### Legend

`figure.axes.legend`

{{ style_table("LegendStyle") }}

`location` takes any matplotlib legend location: `best`, `upper right`, `lower left`,
`center right`, ….

### Colours

`figure.axes.colors` — a list of colours used for successive curves and scatter series. The
default is the colour-blind-safe Okabe–Ito palette, ordered so that the first colours also
differ in greyscale print: `#000000` (black), `#0072B2` (blue), `#E69F00` (orange), `#D55E00`,
`#56B4E9`, `#009E73`, `#CC79A7`. From the fourth curve on, also vary the line style or marker.

### Lines

`figure.axes.lines` — curves. Markers are any matplotlib marker (`o`, `s`, `^`, `x`, `.`, …);
empty means none.

{{ style_table("LinesStyle") }}

### Scatter

`figure.axes.scatter` — markers of [scatter plots](plot-settings.md).

{{ style_table("ScatterStyle") }}

Scatter plots with more than 5000 points are stored as an image inside PDF/SVG files (at
`figure.dpi`), so the files stay small. Axes, labels and text stay vector.

### Image and colour bar

`figure.axes.image` — heat maps, and colour scales in general (scatter colouring, long curve
families). `cmap` is any matplotlib colour map, e.g. `viridis`, `magma`, `cividis`, `RdBu_r`,
`twilight`.

{{ style_table("ImageStyle") }}

`figure.axes.image.colorbar`

{{ style_table("ColorbarStyle") }}

## Quantities

`quantities.<name>` — fixed scales and units for one physical quantity, used by every plot
whose axis or value has that name: fixed limits, colour map, scale and unit prefix. See
[Fixed scales and unit prefixes](scales-and-units.md).

{{ style_table("QuantityStyle") }}
