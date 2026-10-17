# How styles work

LBD draws every figure with matplotlib, in LBD Viewer and in Python (`lbd.plot`). Two kinds of
settings control a figure:

- A **style** controls how it looks: size, fonts, frame, ticks, colours, markers, colour maps and
  fixed scales. Styles are named **presets** (Styles page, shared with Python) or **style files**
  (`*.lbd.json`). A data file can also carry its own style changes.
- A **plot spec** controls what is drawn: which values, curve / scatter / heat map, which axis
  is horizontal, how complex data is shown, labels, and so on.

Both are JSON objects. You can edit them in the viewer, write them from code (the dataset's plot
and style fields, e.g. `d.plot` / `d.style` in Python), or pass them to
[`lbd.plot`](../python/plotting.md).

## Structure

A style follows matplotlib's own object tree: a **Figure** contains **Axes**, and an Axes has a
frame (the "spines"), a title, an x axis and a y axis (each with a label and ticks), a grid, a
legend, and the plotted elements (lines, scatter markers, images).

```
style
├── figure                     size, export resolution, background
│   ├── font                   text of the whole figure
│   └── axes                   the plotting area
│       ├── frame              the four spines
│       ├── title
│       ├── axis               x and y axis: label, ticks, minor ticks
│       ├── xaxis, yaxis       optional: what differs for one axis
│       ├── grid
│       ├── legend
│       ├── colors             colour cycle of curves
│       ├── lines              curves
│       ├── scatter            scatter markers
│       └── image              heat maps, colour maps
│           └── colorbar
└── quantities                 fixed scales per quantity
```

The same nesting appears on the viewer's Styles page and in style files. Every key is
optional: a preset or a file's style only needs the settings it changes.

Lengths are in millimetres (`_mm`), typographic points (`_pt`; 1 pt = 1/72 inch ≈ 0.353 mm)
or percent (`_pct`). An empty value (`null`) means "automatic", as described per key.

## How a style is put together

Exactly one preset applies to a figure. It is chosen in this order:

1. the preset picked in the viewer's **Preset** box (or passed as `style=` in Python);
2. otherwise the file's `style_name`, if a preset with that name exists on this computer;
3. otherwise the **default** preset (set on the Styles page).

The final style is built by layering, where later layers win, key by key:

```
built-in defaults  ←  the preset  ←  the file's own style  ←  unsaved changes in the viewer
```

So `{"figure": {"width_mm": 120}}` changes only the width. Presets store only what differs
from the built-in defaults; style files store the complete style.

**The built-in preset `default`** is the journal style for APS and AIP: one column
85 × 64 mm, Arial 10 pt for all text, 600 dpi ([why](#the-default-style-and-journal-rules)). It
can be changed (**Reset** restores it) but not deleted. Make your own presets for anything else,
e.g. a two-column figure or slides:

| You want | Preset settings |
|---|---|
| A two-column journal figure | `{"figure": {"width_mm": 170, "height_mm": 80}}` |
| Slides or a poster | `{"figure": {"width_mm": 160, "height_mm": 100, "dpi": 300, "font": {"size_pt": 14}, "axes": {"lines": {"width_pt": 2}}}}` |

## The default style and journal rules

The built-in default is made for **APS (Physical Review) and AIP journals**. It follows every
figure rule both publishers state; where they differ, it uses the stricter one (AIP's).

| Rule | Source | Default |
|---|---|---|
| Width ≤ 8.5 cm for one column, ≤ 17 cm for two | AIP (APS: 8.6 cm column) | 85 × 64 mm; for two columns set `figure.width_mm` to 170 |
| Height ≤ 21.1 cm | AIP | 64 mm |
| Text ≥ 8 pt (APS: ≥ 2 mm, about 5.7 pt) | AIP | all text 10 pt: axis titles, tick numbers, legend, title |
| No large differences in lettering size | AIP | one size for all text |
| Lines ≥ 0.5 pt | APS and AIP | frame and major ticks 0.6, minor ticks 0.5, grid 0.5, curves 1.0 |
| Units in parentheses: `Frequency (GHz)` | APS | `unit_format: paren` |
| Line art at 600 dpi | AIP (APS: preferably ≥ 600) | 600 dpi |
| Fonts embedded; no unusual fonts | AIP / APS | Arial, embedded in PDF (TrueType) |
| Readable in greyscale print | APS | colours ordered by grey level; viridis colour map |

What a style can't do for you, so check it in each figure:

- **Panel labels** (a), (b), … (APS and AIP).
- **No ×10ⁿ above an axis.** APS wants the factor in the unit: `Counts (10⁶)`, not `×10⁶`. Use
  base units with [unit prefixes](scales-and-units.md#unit-prefixes), or divide the data and
  write the factor in the label.
- **Captions** belong in the paper, not in the figure; captions of colour figures may need
  "(Color online)" (APS).

Sources: [APS — Information for Contributors](https://journals.aps.org/prmaterials/authors/information-for-contributors),
[APS — color online figures](https://journals.aps.org/prl/authors/guide-acceptable-color-online-figures-h24),
[AIP Publishing — Author Instructions](https://publishing.aip.org/resources/researchers/author-instructions/).
For another journal (e.g. Nature Physics: 89 mm, 5–7 pt sans-serif), make a preset with its
values.

