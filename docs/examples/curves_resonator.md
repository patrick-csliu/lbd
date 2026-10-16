# Curves: a resonator measured at several powers

Save a measurement together with its settings, read it back, and plot one curve per drive power.

- **Figure:** |S21| in dB against frequency, one curve per power.
- **Code:** save data and metadata (instrument settings) in an .lbd file, read the header back, plot curves.

<!-- no-check -->
```python title="curves_resonator.py"
--8<-- "examples/python/curves_resonator.py:11:51"
```

## Result

![Curves: a resonator measured at several powers](img/curves_resonator.png)

<!-- no-check -->
```text title="Printed output"
--8<-- "docs/examples/output/curves_resonator.txt"
```

## How it works

--8<-- "examples/python/curves_resonator.md"

**Functions used:** [`lbd.Dataset`][lbd.Dataset], [`lbd.info`][lbd.info], [`lbd.load`][lbd.load], [`lp.plot`][lbd.plot.plot], [`lp.save`][lbd.plot.save]

<small>To run it, copy the code into a file and run it with Python in an empty folder: it writes
its figure and files there. This page is made from `examples/python/curves_resonator.py` by `scripts/make_gallery.py`.</small>
