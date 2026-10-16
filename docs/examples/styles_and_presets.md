# Styles: make a preset once, use it everywhere

A style sets size, fonts, line widths, ticks and colours. Here a "talk" preset is made from the
default, stored (the viewer's Styles page sees it too), saved as a file to keep with a paper, and
exported for colleagues who use matplotlib without LBD.

- **Figure:** a plot drawn with the new preset.
- **Code:** list and load styles, change settings, store a preset, a .lbd.json style file, an .mplstyle file.

<!-- no-check -->
```python title="styles_and_presets.py"
--8<-- "examples/python/styles_and_presets.py:13:47"
```

## Result

![Styles: make a preset once, use it everywhere](img/styles_and_presets.png)

<!-- no-check -->
```text title="Printed output"
--8<-- "docs/examples/output/styles_and_presets.txt"
```

## How it works

--8<-- "examples/python/styles_and_presets.md"

**Functions used:** [`lp.list_styles`][lbd.plot.list_styles], [`lp.load_style`][lbd.plot.load_style], [`lp.PresetStore`][lbd.plot.PresetStore], [`lp.Style`][lbd.plot.Style], [`lp.use`][lbd.plot.use], [`lp.save`][lbd.plot.save]

<small>To run it, copy the code into a file and run it with Python in an empty folder: it writes
its figure and files there. This page is made from `examples/python/styles_and_presets.py` by `scripts/make_gallery.py`.</small>
