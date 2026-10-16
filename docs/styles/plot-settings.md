# Plot settings

The plot spec says what to draw. Every key is optional; missing keys get defaults, and keys you
set win over the ones saved in the file.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `kind` | text | `"auto"` | `curve`, `scatter`, `heatmap`, `scalar` (a single number), or `auto`: `curve` for 1-D values, `heatmap` for 2-D and higher, `scalar` for single numbers. |
| `values` | list of names | the first non-scalar value | Values to plot. Curves and scatter can show several; heat maps use the first. |
| `complex` | text | `"abs"` | How complex values are shown: `abs` (magnitude), `db` (20·log₁₀\|z\|), `phase` (radians), `phase_deg` (degrees), `real`, `imag`, and for scatter only `iq` (the I/Q plane). Real values are shown as they are (with a warning if you asked for another mode). |
| `x` | name | the value's last axis | Horizontal axis. Curves and heat maps: an axis. Scatter: an axis, or a **value** with the same axes as the plotted one (value against value). |
| `y` | axis name | the last remaining axis | Heat maps: vertical axis. |
| `series` | axis name or `"none"` | the first other axis | Curves of a single 2-D (or higher) value: one curve per point of this axis. `"none"` draws one curve and uses a slice instead. |
| `color` | name or `"none"` | none | Scatter: colour the points by an axis (its coordinates) or by a value with the same axes. A short axis (e.g. the prepared state) gets one colour per point and a legend; a longer axis or a value gets a colour bar. |
| `index` | object `{axis: index}` | `0` for each | Curves and heat maps: for every dimension not shown, which point to show (0-based, whole numbers; `-1` is the last point; sliders in the viewer). Scatter: by default **all** points are drawn; an axis listed here is fixed at that index. |
| `x_scale` | text | `"linear"` | `linear` or `log`. |
| `y_scale` | text | `"linear"` | `linear` or `log`. A quantity with `"scale": "log"` also makes it log. |
| `title` | text | none | Title above the plot. Usually left empty for publication figures. |
| `x_label` | text | the axis/value label | Replaces the horizontal axis label; the unit is still added. |
| `y_label` | text | the value's label | Replaces the vertical axis label. With several values, the default is `Value`, since the legend names them. |
| `z_label` | text | the label | Replaces the colour bar label (heat maps, coloured scatter). |
| `annotations` | list | none | Extra drawing on the plot: lines, text, arrows, shapes. See [Annotations](#annotations). |

**Scatter modes**

| You want | Spec |
|---|---|
| Measured points against an axis | `{"kind": "scatter", "values": ["T1"], "x": "freq"}` |
| One value against another, point by point | `{"kind": "scatter", "values": ["Q"], "x": "I"}` |
| A complex value in the I/Q plane | `{"kind": "scatter", "values": ["S21"], "complex": "iq"}` |
| …coloured by a third quantity | add `"color": "power"` (an axis) or `"color": "T"` (a value) |

**Curve families and coloured scatter plots.** Curves of a `series` axis, and scatter points
coloured by an axis, get one colour of `colors` each and a legend entry (*Power = −60 dBm*). When
the axis has more points than there are colours in `colors`, they are coloured along
`image.cmap` instead, with a colour bar for that axis. A scatter plot also uses a colour bar when
the style fixes a colour scale for the axis (`vmin`, `vmax` or `cmap` in its quantity), or when
it is coloured by a value.

**Labels with symbols.** Labels may contain matplotlib math between dollar signs, e.g.
`"$|S_{21}|$"` or `"$T_1$"`.

## Annotations

`annotations` adds anything matplotlib can draw on the plot: reference lines, shaded bands,
text, arrows, markers, rectangles. Each entry names a matplotlib function and its arguments,
exactly as you would call it in Python. LBD only checks that matplotlib has that function and
calls it after the data is drawn; everything else is matplotlib's. Two complete examples:
[state centres on a single-shot heat map](../examples/heatmap_single_shot.md) and
[a box saved with the file](../examples/box_power_sweep.md).

| Entry | Calls | Use for |
|---|---|---|
| `{"method": "<name>", "args": [...], "kwargs": {...}}` | `ax.<name>(*args, **kwargs)`, any [Axes method](https://matplotlib.org/stable/api/axes_api.html) | `axvline`, `axhline`, `axvspan`, `axhspan`, `text`, `annotate`, `plot`, `fill_between`, `errorbar`, `set_xlim`, … |
| `{"patch": "<name>", "args": [...], "kwargs": {...}}` | `ax.add_patch(matplotlib.patches.<name>(*args, **kwargs))` | `Rectangle`, `Circle`, `Ellipse`, `Polygon`, `FancyArrowPatch`, … |

`args` and `kwargs` are optional. An example that marks a resonance:

```json
"annotations": [
  {"method": "axvline", "args": [6999.5], "kwargs": {"ls": ":", "color": "0.4"}},
  {"method": "axvspan", "args": [6999.3, 6999.7], "kwargs": {"alpha": 0.15}},
  {"method": "annotate", "args": ["$\\omega_\\mathrm{r}$"],
   "kwargs": {"xy": [6999.5, -15], "xytext": [0.6, 0.3], "textcoords": "axes fraction",
              "arrowprops": {"arrowstyle": "->"}}},
  {"method": "plot", "args": [[6999.5], [-15]], "kwargs": {"marker": "o", "ls": "", "label": "fit"}},
  {"patch": "Rectangle", "args": [[6999.2, -18], 0.6, 8], "kwargs": {"fill": false}},
  {"method": "annotate", "args": ["T = 20 mK"], "kwargs": {"xy": [0.03, 0.92], "xycoords": "axes fraction"}}
]
```

Rules:

- **Coordinates are in the units shown on the axes.** On a frequency axis shown in MHz, 7 GHz
  is `7000`. If the unit prefix of an axis is chosen automatically, it may change with the data
  or the style, and the annotations would land in the wrong place, so LBD warns. Fix the
  prefix for that quantity in the style, e.g. `{"quantities": {"freq": {"prefix": "M"}}}`
  (see [unit prefixes](scales-and-units.md)).
- **Text in a corner**, independent of the data: use `annotate` with
  `"xycoords": "axes fraction"` (0–1 across the plot), as in the last entry above.
- **Only JSON values** can be passed: numbers, text, lists, objects, `true`/`false`/`null`.
  Python objects such as `transform=ax.transAxes` can't; use the `…coords` options of
  `annotate` instead.
- **The style applies**: font size, line width and the colour cycle come from the style unless
  you set them; `"color": "C1"` is the second colour of the cycle.
- **Legend**: an entry with a `"label"` joins the legend.
- **Not allowed**: `clear`, `cla`, `remove`, `draw`, `draw_artist`, `redraw_in_frame` and the
  `get_…` methods, which would remove the plot or do nothing.
- **Errors**: an unknown name stops the plot with a suggestion (*no method 'axvlin'; did you
  mean axvline?*); an error from matplotlib names the entry
  (*annotations[2] (annotate): …*).
- **matplotlib version**: annotations are matplotlib calls, so a much newer matplotlib could
  one day rename an option. Every saved view records the matplotlib version that wrote it
  (`/plot/matplotlib` in the file); an error message shows it when it differs from yours.

## How settings are checked

- **Errors.** A setting that can't work stops the plot with a message that lists the valid
  choices: an unknown key (`xscale` instead of `x_scale`), a value or axis that doesn't exist,
  an unknown `kind` or `complex` mode, `iq` for a plot that isn't a scatter plot, an `index`
  that is out of range or not a whole number, an annotation matplotlib doesn't have or can't
  draw.
- **Warnings.** A setting that is valid but has no effect is ignored with a warning that names
  it: `color` on a curve, `series` when several values are plotted, an `index` for an axis that
  is drawn, a heat map of several values (only the first is shown).
- **Saved views are lenient.** A file's saved view may be older than its data. If it refers to
  something that no longer exists, that part is ignored with a warning and the default is used,
  so the file still opens.

LBD Viewer shows warnings as notes under the figure. It doesn't report settings that don't apply
to the chosen plot type, because it keeps them while you switch between types.

