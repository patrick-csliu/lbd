# Which function do I need?

Find your task, then follow the link for the details. Every function is in the
[`lbd` reference](../reference/python/lbd.md) or the [`lbd.plot` reference](../reference/python/lbd-plot.md).
Whole scripts, from data to figure, are in the [Examples](../examples/index.md).

```python
import lbd                # files
import lbd.plot as lp     # figures (pip install "lbd[plot]")
```

## Save and read data

| I want to… | Use | Example |
|---|---|---|
| save a measurement | [`Dataset`][lbd.Dataset], [`add_axis`][lbd.Dataset.add_axis], [`add_value`][lbd.Dataset.add_value], [`save`][lbd.Dataset.save] | [Building a dataset](files.md#building-a-dataset) |
| read a file | [`lbd.load`][lbd.load] | `d = lbd.load("sweep.lbd")` |
| read only some values of a big file | [`lbd.load`][lbd.load] with `values=` | `lbd.load("big.lbd", values="S21")` |
| list or check many files quickly | [`lbd.info`][lbd.info] | [Reading](files.md#reading) |
| give files a default plot without rewriting them | [`lbd.set_plot`][lbd.set_plot] | `lbd.set_plot(p, spec={"kind": "heatmap"})` |
| know which version is installed | [`lbd.version`][lbd.version] | `lbd.version()` |

## Plot data like the viewer

| I have… | Use | Example |
|---|---|---|
| an `.lbd` file | [`lp.plot`][lbd.plot.plot] | `lp.plot("sweep.lbd")` |
| a `Dataset` in memory (saved or not) | [`lp.plot`][lbd.plot.plot] | `lp.plot(d, "heatmap", "S21", complex="db")` |
| plain arrays | [`lp.quick`][lbd.plot.quick] | `lp.quick(t, v, x_unit="s", y_unit="V")` |
| a figure with several panels | [`lp.plot`][lbd.plot.plot] with `ax=` | [Panels](plotting.md#from-a-dataset-or-file) |

## Make my own figures match

| I want to… | Use | Example |
|---|---|---|
| style a figure I draw with matplotlib | [`lp.use`][lbd.plot.use] | `with lp.use("thesis"): fig, ax = plt.subplots()` |
| style every figure in a notebook | [`lp.activate`][lbd.plot.activate] | `lp.activate("thesis")` |
| another size, or a grid of axes | [`lp.subplots`][lbd.plot.subplots] | `lp.subplots(1, 2, width_mm=170)` |
| restyle a figure made by other code | [`lp.apply`][lbd.plot.apply] | `lp.apply(fig, "thesis")` |
| readable units (7e9 Hz → 7 GHz) or a fixed prefix | [`lp.prefix`][lbd.plot.prefix] | `f, unit = lp.prefix(f, "Hz", to="M")` |
| an axis title with its unit | [`lp.axis_label`][lbd.plot.axis_label] | `lp.axis_label("Frequency", unit)` |
| save exactly like the viewer exports | [`lp.save`][lbd.plot.save] | `lp.save(fig, "fig.pdf", style="thesis")` |

## Work with styles

| I want to… | Use | Example |
|---|---|---|
| see the preset names | [`lp.list_styles`][lbd.plot.list_styles] | `lp.list_styles()` |
| read or change settings in Python | [`lp.load_style`][lbd.plot.load_style] | `s = lp.load_style("thesis"); s.figure.width_mm` |
| keep a style next to a paper's data | [`Style.save`][lbd.plot.style.Style.save] | `lp.load_style("thesis").save("thesis.lbd.json")` |
| give a style to someone without LBD | [`Style.to_mplstyle`][lbd.plot.style.Style.to_mplstyle] | [mplstyle recipe](plotting.md#a-style-for-matplotlib-users-without-lbd) |
| create, change or delete a preset | [`PresetStore`][lbd.plot.PresetStore] | `lp.PresetStore().save("paper", {...})` |
| the exact style the viewer uses for a file | [`PresetStore.resolve`][lbd.plot.PresetStore.resolve] | see its example |

## When something goes wrong

Functions raise an **error** when they can't do what was asked (the message names the problem
and the valid choices) and give a **warning** when they did it but ignored or adjusted
something. Nothing is dropped silently. See
[Errors and warnings](../reference/python/lbd-plot.md#errors-and-warnings).
