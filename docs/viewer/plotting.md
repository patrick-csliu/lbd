# Plotting

A plotted file shows the controls on the left and the figure on the right. Every change redraws
the figure straight away. The same settings are available in Python as the
[plot spec](../styles/plot-settings.md) of [`lbd.plot.plot`][lbd.plot.plot].

**Data**

| Control | Meaning |
|---|---|
| **Plot type** | **Curves** draws lines. **Scatter** draws markers (see below). **Heat map** draws a colour map of a 2-D value. A file with only a single number shows that number. |
| **Values** (curves, scatter) | Tick several values to draw them together. They must share the horizontal axis. |
| **Value** (heat map, I/Q scatter) | The value to show. Heat maps list values with 2 or more axes; the I/Q plane lists complex values. |
| **Complex data as** | For complex values: magnitude, magnitude in dB (20·log₁₀), phase in radians or degrees, real part, imaginary part. For scatter also **I/Q plane**: real part against imaginary part, with equal scales. |
| **Horizontal axis** | Which axis runs left to right. For scatter this can also be another **value** with the same axes: the two values are then plotted against each other, point by point. |
| **Vertical axis** | Heat maps: which axis runs bottom to top. |
| **One curve per** | Curves of a 2-D value: draws one curve per point of this axis, for example one curve per power. Choose **— (single curve)** to draw one curve and pick the other axis's point with a slider instead. |
| **Colour by** | Scatter: colour the points by an axis (e.g. power) or by another value with the same axes. A short axis (e.g. the prepared state) gets one colour per point and a legend; a longer axis or a value gets a colour bar, with the style's fixed scales. |
| **Sliders** | Curves and heat maps: for each dimension that isn't drawn, choose which point to show. The label shows the axis value, e.g. `Power = -20 dBm (5/13)`. Scatter plots draw all points. |
| **Log x / Log y** | Logarithmic axes. |

**Scatter examples:**
- measured points against frequency: Values = `T1`, Horizontal = `freq`;
- quadrature against in-phase: Values = `Q`, Horizontal = `I`;
- readout I/Q blobs coloured by the prepared state: Value = `IQ`, Complex = I/Q plane, Colour by = `prep`.

**Labels.** Open **Labels** to set a title, or to replace the axis and colour bar labels. Units
are added automatically. Changes apply when you leave the field or press Enter. Math is allowed
between dollar signs, e.g. `$|S_{21}|$`.

**Style**

| Control | Meaning |
|---|---|
| **Preset** | The style preset for this figure. It starts at the file's own preset if it names one, otherwise the default preset. |
| **Width mm / Height mm** | Change the figure size for this file only. Leave empty to use the preset's size. |
| **Annotations (JSON list)** | Lines, text, arrows and shapes drawn on the plot, as matplotlib calls, e.g. `[{"method": "axvline", "args": [7.0], "kwargs": {"ls": ":"}}]`. Press **Apply**; **Save view** stores them in the file. See [Annotations](../styles/plot-settings.md#annotations). |
| **Style changes for this file (JSON)** | Any other [style setting](../styles/settings.md) for this file only, applied on top of the preset. Example: `{"figure": {"font": {"size_pt": 9}}, "quantities": {"S21.db": {"vmin": -20, "vmax": 0}}}`. Press **Apply**. |

These changes are not saved until you use **Save this view to the file**.

**Notes under the figure.** A yellow note means the figure was drawn but something was adjusted
or ignored, for example: the file names a style preset that doesn't exist on this computer, its
saved view refers to a value that was removed, or a log scale hides values ≤ 0. Settings that
can't work at all (an index out of range, an unknown axis) show a red error instead.

**Zoom**

| Option | Meaning |
|---|---|
| **Fit** | Fits the figure into the window. |
| **100 % (print size)** | Shows the figure at its real printed size on a standard 96 dpi screen. |
| **150 % / 200 %** | Enlarges it. |

The figure's real size in mm is shown next to the zoom box.
