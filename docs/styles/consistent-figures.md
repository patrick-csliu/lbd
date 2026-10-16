# Consistent figures in your own code

LBD Viewer draws curves, scatter plots and heat maps. A paper or thesis needs more: fits,
combined panels, figure types no viewer offers. This page shows how to make **all** of them
match, in size, fonts, line widths, colours, ticks and resolution, whether they come from the
viewer or from your own code.

## The idea: one style, used everywhere

A [style](index.md) holds every visual setting of a figure. Keep **one style per paper**, and
use it in every place a figure is made:

| Where the figure is made | How it gets the style |
|---|---|
| LBD Viewer | Choose the preset in the plot controls, or make it the default on the Styles page. |
| `lbd.plot.plot(...)` | `style="paper"`; without it, the file's own preset or the default preset. |
| Your own matplotlib code | `with lbd.plot.use("paper"): ...` |
| A colleague's matplotlib, without LBD | `plt.style.use("paper.mplstyle")`, exported from the style. |

## Step by step

### 1. Make the style

On the viewer's **Styles** page, create a preset, e.g. `paper`, and set the journal's figure
width, font and sizes ([Styles page](../viewer/styles-page.md)). Or from Python:

```python
import lbd.plot as lp

lp.PresetStore().save("paper", {
    "figure": {"width_mm": 85, "height_mm": 60, "font": {"family": "Times New Roman", "size_pt": 9}},
})
```

### 2. Keep it with the paper

A preset lives on your computer. Save the style as a file next to the paper's data, so it is
versioned with the paper and works on any computer:

```python
lp.load_style("paper").save("paper.lbd.json")
```

Every function accepts the file path wherever it accepts a preset name:
`style="paper.lbd.json"`. The viewer can import it on the Styles page.

### 3. Fix the colour scales per quantity

Figures of the same quantity should share a colour scale, so that colours can be compared
between figures. Set it once in the style:

```python
lp.PresetStore().save("paper", {
    "figure": {"width_mm": 85, "height_mm": 60},
    "quantities": {"S21.db": {"vmin": -30, "vmax": 0}},
})
```

See [Fixed scales and unit prefixes](scales-and-units.md); a fixed `prefix` per quantity (e.g. always MHz) keeps the units the same too.

### 4. Plot measured data with the tool's plot types

In the viewer, choose the `paper` preset and export, or in Python:

```python
fig = lp.plot("sweep.lbd", "heatmap", "S21", complex="db", style="paper")
lp.save(fig, "fig2.pdf", style="paper")
```

### 5. Draw everything else inside the style

```python
import numpy as np
import matplotlib.pyplot as plt

x = np.linspace(0, 1, 20)
with lp.use("paper"):
    fig, ax = plt.subplots()
    ax.plot(x, x ** 2, "o", label="data")
    ax.plot(x, x ** 2, label="fit")
    ax.set_xlabel(lp.axis_label("Flux", "Φ0"))
    ax.legend()
    fig.savefig("fig3.pdf")
```

Figures with several panels combine both: draw each panel with `lp.plot(..., ax=panel)` inside
`lp.use(...)`; see [Plotting with lbd.plot](../python/plotting.md#from-a-dataset-or-file).

## What makes two figures identical

- **Size.** The style sets the size of the whole figure in mm, labels included, and exports
  are never cropped. Placed at 100 % in the document, 10 pt text is 10 pt on paper.
- **Fonts.** Use a font every computer that makes your figures has (the default, Arial, is on
  Windows and macOS; DejaVu Sans and DejaVu Serif ship with matplotlib), so the same font is used on
  every computer. Fonts are embedded in PDF exports.
- **Same code.** The viewer and `lbd.plot` share their drawing code; the same data, settings
  and style give pixel-identical results.
- **Saved views.** A view saved into an `.lbd` file opens the same way for everyone, so a
  figure can be redrawn years later.
