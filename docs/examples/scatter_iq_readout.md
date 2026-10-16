# Scatter: single-shot readout in the I/Q plane

Every single-shot measurement of a qubit is one point in the I/Q plane. Prepared in |0⟩ or in
|1⟩, the points form two clouds; colouring them by the prepared state shows how well they separate.

- **Figure:** a scatter plot of I against Q, one colour per prepared state, named in the legend.
- **Code:** plot a Dataset in memory; colour points by an axis (a legend for a short axis); override the style for one figure.

<!-- no-check -->
```python title="scatter_iq_readout.py"
--8<-- "examples/python/scatter_iq_readout.py:12:36"
```

## Result

![Scatter: single-shot readout in the I/Q plane](img/scatter_iq_readout.png)

## How it works

--8<-- "examples/python/scatter_iq_readout.md"

**Functions used:** [`lbd.Dataset`][lbd.Dataset], [`lp.plot`][lbd.plot.plot], [`lp.save`][lbd.plot.save]

<small>To run it, copy the code into a file and run it with Python in an empty folder: it writes
its figure and files there. This page is made from `examples/python/scatter_iq_readout.py` by `scripts/make_gallery.py`.</small>
