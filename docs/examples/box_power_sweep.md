# A box around a region, saved with the file

A power sweep of a resonator: above about −20 dBm the resonance moves. A box and a label mark
that region. The view, its style and the box are stored in the .lbd file, so the file opens the
same way in LBD Viewer and with lp.plot(path).

- **Figure:** a heat map with a rectangle and a label.
- **Code:** store the plot with the file (lbd.set_plot); redraw it from the file; export PDF, SVG and PNG.

<!-- no-check -->
```python title="box_power_sweep.py"
--8<-- "examples/python/box_power_sweep.py:13:54"
```

## Result

![A box around a region, saved with the file](img/box_power_sweep.png)

<!-- no-check -->
```text title="Printed output"
--8<-- "docs/examples/output/box_power_sweep.txt"
```

## How it works

--8<-- "examples/python/box_power_sweep.md"

**Functions used:** [`lbd.Dataset`][lbd.Dataset], [`lbd.set_plot`][lbd.set_plot], [`lbd.load`][lbd.load], [`lp.plot`][lbd.plot.plot], [`lp.save`][lbd.plot.save]

<small>To run it, copy the code into a file and run it with Python in an empty folder: it writes
its figure and files there. This page is made from `examples/python/box_power_sweep.py` by `scripts/make_gallery.py`.</small>
