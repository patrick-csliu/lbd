# Two panels with a shared axis: a Wigner function and its projection

A cat state's Wigner function W(x, p) as a heat map, and above it the probability P(x) of the
position, the projection of W onto the x axis. Both panels share the x axis.

- **Figure:** two stacked panels, (a) a curve, (b) a heat map with a diverging colour map.
- **Code:** lp.subplots with a shared axis; lp.plot into one panel (ax=), your own matplotlib code in the other.

<!-- no-check -->
```python title="subplots_wigner.py"
--8<-- "examples/python/subplots_wigner.py:12:43"
```

## Result

![Two panels with a shared axis: a Wigner function and its projection](img/subplots_wigner.png)

## How it works

--8<-- "examples/python/subplots_wigner.md"

**Functions used:** [`lbd.Dataset`][lbd.Dataset], [`lp.subplots`][lbd.plot.subplots], [`lp.plot`][lbd.plot.plot], [`lp.use`][lbd.plot.use], [`lp.save`][lbd.plot.save]

<small>To run it, copy the code into a file and run it with Python in an empty folder: it writes
its figure and files there. This page is made from `examples/python/subplots_wigner.py` by `scripts/make_gallery.py`.</small>
