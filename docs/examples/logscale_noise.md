# Log scale: a noise spectrum in your own matplotlib code

Your own figure, written with plain matplotlib, in the same style as the viewer's plots: a noise
power spectral density on log-log axes with guide lines for the 1/f and the white noise.

- **Figure:** log-log axes, data and two guide lines, a legend and a fit result.
- **Code:** lp.use for the style, lp.axis_label for "Name (unit)", lp.prefix for a readable number, lp.save.

<!-- no-check -->
```python title="logscale_noise.py"
--8<-- "examples/python/logscale_noise.py:12:34"
```

## Result

![Log scale: a noise spectrum in your own matplotlib code](img/logscale_noise.png)

## How it works

--8<-- "examples/python/logscale_noise.md"

**Functions used:** [`lp.use`][lbd.plot.use], [`lp.axis_label`][lbd.plot.axis_label], [`lp.prefix`][lbd.plot.prefix], [`lp.save`][lbd.plot.save]

<small>To run it, copy the code into a file and run it with Python in an empty folder: it writes
its figure and files there. This page is made from `examples/python/logscale_noise.py` by `scripts/make_gallery.py`.</small>
