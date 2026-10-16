# Quick look: plot numpy arrays in one call

For a fast look at arrays, for example right after a fit, lp.quick draws them in the same style
as the viewer, without a Dataset or a file. Here: a Rabi oscillation with its fit.

- **Figure:** measured points and a fitted curve, with a legend.
- **Code:** lp.quick with named curves (a dict), labels and units; base units get readable prefixes.

<!-- no-check -->
```python title="quick_look.py"
--8<-- "examples/python/quick_look.py:12:25"
```

## Result

![Quick look: plot numpy arrays in one call](img/quick_look.png)

## How it works

--8<-- "examples/python/quick_look.md"

**Functions used:** [`lp.quick`][lbd.plot.quick], [`lp.save`][lbd.plot.save]

<small>To run it, copy the code into a file and run it with Python in an empty folder: it writes
its figure and files there. This page is made from `examples/python/quick_look.py` by `scripts/make_gallery.py`.</small>
