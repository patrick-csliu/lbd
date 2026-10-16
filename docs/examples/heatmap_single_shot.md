# Heat map: single-shot qubit readout with the two states marked

A 2-D histogram of many single-shot I/Q measurements. Annotations mark the centre of each state,
a 2σ circle around it, and the threshold between them.

- **Figure:** a heat map of counts in the I/Q plane, with markers, labels, circles and a threshold line.
- **Code:** annotations: an Axes method with args and kwargs, a patch, text at a fixed place in the plot.

<!-- no-check -->
```python title="heatmap_single_shot.py"
--8<-- "examples/python/heatmap_single_shot.py:12:54"
```

## Result

![Heat map: single-shot qubit readout with the two states marked](img/heatmap_single_shot.png)

## How it works

--8<-- "examples/python/heatmap_single_shot.md"

**Functions used:** [`lbd.Dataset`][lbd.Dataset], [`lp.plot`][lbd.plot.plot], [`lp.save`][lbd.plot.save]

<small>To run it, copy the code into a file and run it with Python in an empty folder: it writes
its figure and files there. This page is made from `examples/python/heatmap_single_shot.py` by `scripts/make_gallery.py`.</small>
