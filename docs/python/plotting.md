# Plotting with `lbd.plot`

```python
import lbd.plot as lp
```

`lbd.plot` makes figures in Python that look exactly like LBD Viewer's. It uses the same styles
(presets from the viewer's Styles page, or `.lbd.json` style files) and the same drawing code.
There are two ways to use it:

1. **Your own matplotlib figures, in the tool's style.** The viewer can't offer every figure
   type, so you draw anything you like with matplotlib, and `lbd.plot` gives it the same size,
   fonts, frame, ticks, colours, line widths and resolution as every other figure.
2. **The tool's plot types from Python**: curves, scatter and heat maps of a `Dataset` in
   memory (nothing needs to be saved first) or of an `.lbd` file.

Install it with the plotting extra, `pip install "lbd[plot]"`, which adds matplotlib, pydantic
and platformdirs ([Install → Python](../getting-started/install.md#python)). Every function is
listed in the [API reference](../reference/python/lbd-plot.md); to find the right one for a task,
see [Which function do I need?](which-function.md). Complete scripts with their figures are in
the [Examples](../examples/index.md).

## Quick start

```python
import numpy as np
import matplotlib.pyplot as plt
import lbd
import lbd.plot as lp

f = np.linspace(6.99e9, 7.01e9, 401)
p = np.arange(-60, 1, 5.0)
s21 = 1 - 0.8 / (1 + 2j * (f[None, :] - 7e9) / 0.6e6) * np.ones((len(p), 1))

# 1) Your own figure, in the style "default" (or any preset / .lbd.json file)
with lp.use("default"):
    fig, ax = plt.subplots()                      # the style's size, constrained layout
    f_ghz, f_unit = lp.prefix(f, "Hz")            # Hz -> GHz, like the tool
    for k in (0, 6, 12):
        ax.plot(f_ghz, 20 * np.log10(np.abs(s21[k])), label=f"{p[k]:g} dBm")
    ax.set_xlabel(lp.axis_label("Frequency", f_unit))
    ax.set_ylabel(lp.axis_label("|S21|", "dB"))
    ax.legend()
    fig.savefig("my_figure.pdf")                  # the style's dpi, fonts embedded

# 2) The tool's plots, straight from data in memory
d = lbd.Dataset(title="Resonator power sweep")
d.add_axis("power", p, unit="dBm", label="Power")
d.add_axis("freq", f, unit="Hz", label="Frequency")
d.add_value("S21", s21, axes=["power", "freq"])
fig = lp.plot(d, "heatmap", "S21", complex="db")
lp.save(fig, "sweep.pdf")
```

## Choosing a style

Every function takes a `style` argument, in any of these forms:

| Form | Example | Meaning |
|---|---|---|
| preset name | `"thesis"` | A preset from the viewer's Styles page, or the built-in `default`. |
| file path | `"figs/thesis.lbd.json"` | A [style file](../styles/files-and-export.md#style-files). Any path ending in `.json`, or any existing file, is read as a file. |
| dict | `{"figure": {"width_mm": 120}}` | Settings merged over the built-in defaults (partial is fine). |
| `Style` | `lp.load_style("thesis")` | A [style object](../reference/python/style.md). |
| `None` | | The **default preset**, as chosen on the viewer's Styles page. |

Presets are stored where the viewer keeps them (`%APPDATA%\lbd\styles` on Windows,
`~/.config/lbd/styles` on Linux), so a preset made in the viewer is available in Python at
once. The environment variable `LBD_CONFIG_DIR` moves both. Every setting is listed in
[Style settings](../styles/settings.md).

```python
lp.list_styles()                          # ['default', 'paper', 'thesis']
s = lp.load_style("thesis")               # a complete Style
s.figure.width_mm = 170                   # a wider variant ...
s.save("thesis-wide.lbd.json")            # ... kept as a style file
lp.PresetStore().save("thesis-wide", s.diff())   # ... or as a preset the viewer shows too
```

## Your own figures

### Inside a `with` block

[`lp.use(style)`][lbd.plot.use] makes matplotlib draw with the style inside the block:

- `plt.subplots()` and `plt.figure()` get the style's size and constrained layout;
- lines, markers, colours, fonts, frame, ticks and grid follow the style;
- `fig.savefig()` uses the style's dpi and embeds fonts.

When the block ends, matplotlib's previous settings come back.

```python
with lp.use("thesis"):
    fig, (a1, a2) = plt.subplots(1, 2)
    a1.plot(x, y)
    a2.errorbar(x, y, yerr=dy, fmt="o")
    fig.savefig("fig3.pdf")
```

!!! warning "Create, draw and save inside the block"
    matplotlib reads some settings when a figure is drawn, not when it is created. Saving
    outside the block can change details such as tick marks. Use [`lp.save`][lbd.plot.save] if
    you save later: it saves inside the style.

For another size or a grid of panels, use [`lp.subplots`][lbd.plot.subplots]:

```python
with lp.use("thesis"):
    fig, axs = lp.subplots(2, 1, height_mm=120, sharex=True)
```

### For a whole notebook

[`lp.activate(style)`][lbd.plot.activate] applies a style globally, like `plt.style.use()`:
every later figure uses it. Undo it with `plt.rcdefaults()`, or activate another style.

<!-- no-check -->
```python
%matplotlib inline
lp.activate("paper")          # all notebook figures in the paper style
lp.plot(d)                    # displayed inline
```

### Figures made elsewhere

[`lp.apply(fig, style)`][lbd.plot.apply] restyles a Figure or Axes that was made without the
style, for example by another library: background, frame, ticks, grid, and text sizes and font.
Plotted data keeps its colours and line widths.

### Units and labels like the viewer's

[`lp.prefix`][lbd.plot.prefix] puts a unit prefix on your data the way the viewer does, or
uses the prefix you choose, and [`lp.axis_label`][lbd.plot.axis_label] writes the label in the
style's unit format:

```python
f = np.linspace(4e9, 8e9, 401)
f_ghz, unit = lp.prefix(f, "Hz")              # automatic: values in GHz, unit "GHz"
f_mhz, unit_m = lp.prefix(f, "Hz", to="M")    # your choice, for any unit: MHz
lp.axis_label("Frequency", unit)              # "Frequency (GHz)"
```

Automatic prefixes work for base units (Hz, s, V, A, m, g, …); for any other unit, pass the
prefix you want (`to="m"`) or `to=""`, otherwise you get a warning that nothing was changed.
LBD only adds prefixes, it never converts between units. See
[Unit prefixes](../styles/scales-and-units.md#unit-prefixes).

## The tool's plot types

### From a dataset or file

[`lp.plot`][lbd.plot.plot] draws a curve, scatter or heat map exactly like LBD Viewer. `data` is
a `Dataset` in memory or an `.lbd` path; the other arguments are the
[plot settings](../styles/plot-settings.md). Settings saved in the file's view are used unless
you override them, as in the viewer. The result is a normal matplotlib figure: add
annotations, change limits, then `plt.show()` or `lp.save(...)`.

```python
fig = lp.plot("sweep.lbd")                                   # the file's saved view and style
fig = lp.plot(d, "curve", "S21", complex="phase_deg", series="power")
fig = lp.plot(d, "scatter", "S21", complex="iq", color="power", style="thesis")
```

Annotations (lines, text, arrows, shapes) can be passed the same way, or stored in the file's
saved view with `lbd.set_plot`, so the viewer draws them too. They use the units shown on the
axes, so fix the prefix of those axes ([details](../styles/plot-settings.md#annotations)):

```python
fig = lp.plot("sweep.lbd", "curve", "S21", complex="db", series="none",
              style={"quantities": {"freq": {"prefix": "G"}}},
              annotations=[
                  {"method": "axvline", "args": [6.0], "kwargs": {"ls": ":"}},
                  {"method": "annotate", "args": ["probe tone"],
                   "kwargs": {"xy": [6.0, 0], "xytext": [0.05, 0.85], "textcoords": "axes fraction",
                              "arrowprops": {"arrowstyle": "->"}}},
                  {"patch": "Rectangle", "args": [[5.5, -0.5], 1.0, 1.0], "kwargs": {"fill": False}},
              ])
```

Pass `ax=` to draw into one panel of a larger figure:

```python
with lp.use("thesis"):
    fig, (a, b) = lp.subplots(1, 2, width_mm=170)
    lp.plot(d, "heatmap", "S21", complex="db", ax=a, style="thesis")
    lp.plot(d, "curve", "S21", complex="db", series="none", index={"power": 0}, ax=b, style="thesis")
    a.set_title("(a)", loc="left")
    b.set_title("(b)", loc="left")
lp.save(fig, "fig2.pdf", style="thesis")
```

### From plain arrays

[`lp.quick`][lbd.plot.quick] plots arrays with the tool's look, without building a Dataset:

| Use | Call |
|---|---|
| One curve | `lp.quick(t, v, x_label="Time", x_unit="s", y_label="Signal", y_unit="V")` |
| Several curves | `lp.quick(t, {"data": v, "fit": v_fit})`; the keys become the legend |
| Scatter against x | `lp.quick(f, t1, kind="scatter", x_label="Frequency", x_unit="Hz", y_label="T1", y_unit="s")` |
| Value against value | `lp.quick(i, q, kind="scatter")`; when `x` isn't sorted, the points are plotted pairwise |
| Coloured scatter | add `color=power, color_label="Power", color_unit="dBm"` |
| Heat map | `lp.quick(f, p, z=Z, z_label="|S21|", z_unit="dB")`, with `Z.shape == (len(p), len(f))` |

```python
t = np.linspace(0, 1e-6, 201)
fig = lp.quick(t, {"data": np.sin(2e7 * t), "fit": 0.9 * np.sin(2e7 * t)},
               x_label="Time", x_unit="s", y_label="Signal", y_unit="V")
```

## Recipes

### Make every figure of a paper consistent

See [Consistent figures in your own code](../styles/consistent-figures.md).

### Plot data before saving it

```python
d = lbd.Dataset(title="live")
d.add_axis("freq", f, unit="Hz", label="Frequency")
d.add_value("S21", np.exp(1j * f * 1e-9), axes="freq")    # your measurement here
fig = lp.plot(d, complex="db")                # look at it
d.save("run_042.lbd")                         # keep it if it's good
```

### A style for matplotlib users without LBD

```python
open("paper.mplstyle", "w").write(lp.load_style("paper").to_mplstyle())
# colleagues: plt.style.use("paper.mplstyle")
```

## Errors and warnings

Nothing is ignored silently. A call that can't do what you asked raises an error; a call that
worked but ignored or adjusted something gives a warning.

| | When |
|---|---|
| [`StyleError`][lbd.plot.StyleError] (a `ValueError`) | Unknown preset, unreadable style file, an unknown setting (the message suggests the closest name: `figure.widht_mm` → *did you mean figure.width_mm?*), an invalid value (the message names it), or drawing with a font that isn't installed (the message lists the fonts you can use). |
| [`RenderError`][lbd.plot.RenderError] (a `ValueError`) | The plot can't be made: an unknown value or axis, a heat map of a 1-D value, an index out of range… The message lists the valid choices. |
| `TypeError` / `ValueError` | An argument of the wrong type or shape, e.g. `color=` for a curve, arrays of different lengths in `quick`. |
| `ImportError` | `lbd.plot` imported without `pip install "lbd[plot]"`. |
| [`RenderWarning`][lbd.plot.RenderWarning] | A setting doesn't apply to the plot type (`color` on a curve), or the file's saved view refers to a value that no longer exists. |
| [`StyleWarning`][lbd.plot.StyleWarning] | A style *file* (or the style saved in an `.lbd` file) has settings this version doesn't know; they are ignored. The file's style preset doesn't exist on this computer. |
| [`UnitWarning`][lbd.plot.UnitWarning] | An automatic unit prefix was asked for a unit that doesn't get one (e.g. `dBm`). |

## Notes

- `lp.plot` and the viewer use the same functions, so the same data, plot settings and style
  give pixel-identical results. A test checks this.
- `lp.plot` creates figures with pyplot, so they appear in Jupyter and with `plt.show()`. The
  viewer itself never uses pyplot.
- Figures from `lp.plot` keep their tick and text settings even when saved with a plain
  `fig.savefig()` outside the style. Only the automatic layout may then differ by a fraction of
  a pixel. `lp.save` gives byte-identical files.
