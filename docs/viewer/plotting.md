# Plotting

A plotted file shows the controls on the left and the figure on the right. Every change redraws
the figure straight away. The same settings are available in Python as the
[plot spec](../styles/plot-settings.md) of [`lbd.plot.plot`][lbd.plot.plot].

**Data**

| Control | Meaning |
|---|---|
| **Plot type** | **Curves** draws lines. **Scatter** draws markers (see below). **Heat map** draws a colour map of a 2-D value. **Single number** shows one of the file's single numbers (offered when the file has one). |
| **Values** (curves, scatter) | Tick several values to draw them together; they share the horizontal axis. Below them: **On other axes** lists values measured over another axis, e.g. a noise spectrum over frequency next to a decay over delay; click one to plot it instead, on its own axis. **Numbers** lists the file's single numbers with their value, e.g. `T1 = 21 µs`; click one to show it. |
| **Value** (heat map, I/Q scatter) | The value to show. Heat maps list values with 2 or more axes; the I/Q plane lists complex values. |
| **Complex data as** | For complex values: magnitude, magnitude in dB (20·log₁₀), phase in radians or degrees, real part, imaginary part. For scatter also **I/Q plane**: real part against imaginary part, with equal scales. |
| **Horizontal axis** | Which axis runs left to right. For scatter this can also be another **value** with the same axes: the two values are then plotted against each other, point by point. |
| **Vertical axis** | Heat maps: which axis runs bottom to top. |
| **One curve per** | Curves of a 2-D value: draws one curve per point of this axis, for example one curve per power. Choose **— (single curve)** to draw one curve and pick the other axis's point with a slider instead. |
| **Colour by** | Scatter: colour the points by an axis (e.g. power) or by another value with the same axes. A short axis (e.g. the prepared state) gets one colour per point and a legend; a longer axis or a value gets a colour bar, with the style's fixed scales. |
| **Sliders** | Curves and heat maps: for each dimension that isn't drawn, choose which point to show, with the slider or by typing the axis value in the box next to it (e.g. `-42` for Power in dBm): it goes to the nearest measured point and shows that point's exact value. A value beyond the axis goes to its nearest end. Scatter plots draw all points. |
| **Fixed parameters** | An axis with a single point was not swept (one power, one temperature). It is never chosen as the horizontal axis, vertical axis or "one curve per" by itself, a value with one swept axis is drawn as curves, and it shows as e.g. `Power = -40 dBm (fixed)`, without a slider. |
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
| **DPI (PNG/JPG)** | The resolution of PNG and JPG exports for this file (50–2400). Leave empty to use the preset's (Styles page, "PNG / raster resolution"). PDF and SVG are vector files and the preview doesn't change. |
| **Annotations (JSON list)** | Lines, text, arrows and shapes drawn on the plot, as matplotlib calls, e.g. `[{"method": "axvline", "args": [7.0], "kwargs": {"ls": ":"}}]`. Press **Apply**; **Save view** stores them in the file. See [Annotations](../styles/plot-settings.md#annotations). |
| **Style changes for this file (JSON)** | Any other [style setting](../styles/settings.md) for this file only, applied on top of the preset. Example: `{"figure": {"font": {"size_pt": 9}}, "quantities": {"S21.db": {"vmin": -20, "vmax": 0}}}`. Press **Apply**. |

These changes are not saved until you use **Save this view to the file**.

**Changing the plot type.** A file's saved view was made for one plot type. When you choose
another type, the values, complex mode, log scales and title carry over; the axes, series,
colours, slider positions, axis labels and annotations belong to the saved plot and start from
the new type's defaults. Likewise, when you choose other values, a saved setting that doesn't
fit them is left out. Neither gives a note: the saved view isn't wrong.

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
