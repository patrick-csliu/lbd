1. **Mock data.** Measured points of a Rabi oscillation and the fitted curve, as plain numpy
   arrays.
2. **One call.** [`lp.quick`][lbd.plot.quick] plots arrays in the viewer's style, without a
   [`Dataset`][lbd.Dataset] or a file:
    - `y` can be one array or a dict of named arrays; the names go into the legend;
    - `x_label`/`x_unit` and `y_label`/`y_unit` make the axis titles. A base unit such as `"s"`
      gets a readable prefix automatically, here ns.
3. **Save.** [`lp.save`][lbd.plot.save] writes the figure; or call `plt.show()` to look at it in
   a window.

**Change it**

- A scatter plot: `lp.quick(i, q, kind="scatter")`, coloured by a third array with `color=...`.
- A heat map: `lp.quick(x, y, z=Z, z_label="Counts")`.
- Keep the data: build a `Dataset` and save it, as in the [curves example](curves_resonator.md).
