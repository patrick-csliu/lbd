1. **Mock data, saved.** A power sweep of a resonator whose resonance moves above −20 dBm,
   saved to `power_sweep.lbd` (see the [curves example](curves_resonator.md) for saving data).
2. **Store how the file should be plotted.** [`lbd.set_plot`][lbd.set_plot] writes into an
   existing file, without rewriting its data:
    - `spec`: what to draw, the same [plot settings](../styles/plot-settings.md) that
      `lp.plot` takes, including the `annotations`;
    - `style`: style changes for this file only (here: frequency in MHz).
3. **The box.** `{"patch": "Rectangle", "args": [[x, y], width, height]}` draws
   `matplotlib.patches.Rectangle((x, y), width, height)`, in the units shown on the axes: MHz and
   dBm. `text` adds the label under it ([annotations](../styles/plot-settings.md#annotations)).
4. **Redraw from the file alone.** [`lp.plot(path)`][lbd.plot.plot] with no settings uses
   the saved view and style. LBD Viewer opens the file the same way, box included, and so does
   anyone you send the file to.
5. **Export.** [`lp.save`][lbd.plot.save] writes PDF, SVG or PNG from the extension, at the
   figure's exact size with embedded fonts.
6. **Check what was stored.** [`lbd.load`][lbd.load] returns `d.plot` and `d.style`. The file
   also records the matplotlib version that wrote the view (`d.matplotlib`), since annotations are
   matplotlib calls.

**Change it**

- Remove the saved view again: `lbd.set_plot("power_sweep.lbd", spec=None, style=None)`.
- Use a named preset for this file: `lbd.set_plot(path, style_name="thesis")`.
- A different shape: `"patch": "Ellipse"` with `[[x, y], width, height]`.
