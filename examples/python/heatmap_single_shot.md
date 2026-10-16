1. **Mock data.** 2000 shots per prepared state are drawn around two centres. `np.histogram2d`
   counts them in 80 × 80 bins of I and Q, which is the heat map.
2. **A Dataset in memory.** The bin centres become the axes `I` and `Q` (stored in volts) and
   the counts become a value with `axes=["Q", "I"]`: rows are Q, columns are I. Nothing has to
   be saved to plot it: [`lp.plot`][lbd.plot.plot] takes the [`Dataset`][lbd.Dataset] directly.
3. **Annotations.** Each entry is one matplotlib call that LBD makes after drawing the data
   ([annotations](../styles/plot-settings.md#annotations)):
    - `{"method": "plot", "args": [...], "kwargs": {...}}` calls `ax.plot(*args, **kwargs)`:
      the crosses at the centres. Any `Axes` method works the same way: `text` for the
      labels, `axline` for the endless threshold line.
    - `{"patch": "Circle", "args": [...]}` adds a shape from `matplotlib.patches`: the dashed
      2σ circles.
    - `annotate` with `"xycoords": "axes fraction"` places text at a fixed spot of the plot
      (0 to 1 across), whatever the data range.
4. **Fix the prefix.** Annotation coordinates are in the units shown on the axes, here mV. The
   style fixes both axes to mV (`"prefix": "m"`), so the marks can't move if the automatic choice
   changes. Without it, LBD warns you about exactly this.

**Change it**

- A log colour scale: add `"counts": {"scale": "log"}` to `quantities` (empty bins are then
  left blank, with a warning).
- Another colour map: `"counts": {"cmap": "magma"}`.
- Store the marks in a file, so the viewer shows them too: see the
  [box example](box_power_sweep.md).
