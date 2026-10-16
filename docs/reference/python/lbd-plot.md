# `lbd.plot` — figures in the viewer's styles

```python
import lbd.plot as lp        # needs: pip install "lbd[plot]"
```

This reference is generated from the code. For a guided introduction, see
[Plotting with lbd.plot](../../python/plotting.md); to find the right function for a task, see
[Which function do I need?](../../python/which-function.md). The style settings are listed in
[Style settings](../../styles/settings.md).

## Choose a style

Every function below takes `style=`: a preset name, a `.lbd.json` file, a dict of settings, or
a `Style`. These three are for looking at styles.

| You want to… | Use |
|---|---|
| see which preset names exist | [`list_styles`][lbd.plot.list_styles] |
| get the full settings of a preset, file or dict (to read or change them) | [`load_style`][lbd.plot.load_style] |
| know what you get when you pass no style | [`default_style`][lbd.plot.default_style] |

::: lbd.plot.list_styles
    options:
      heading_level: 3

::: lbd.plot.load_style
    options:
      heading_level: 3

::: lbd.plot.default_style
    options:
      heading_level: 3

## Style your own figures

For figures you draw with matplotlib yourself.

| You want to… | Use |
|---|---|
| style the figures made in one block of code | [`use`][lbd.plot.use] (`with lp.use("thesis"): ...`) |
| style every figure of a notebook or script | [`activate`][lbd.plot.activate] |
| a figure of another size, or a grid of panels | [`subplots`][lbd.plot.subplots] |
| restyle a figure made elsewhere | [`apply`][lbd.plot.apply] |
| save outside the `with` block, exactly like the viewer exports | [`save`][lbd.plot.save] |

::: lbd.plot.use
    options:
      heading_level: 3

::: lbd.plot.activate
    options:
      heading_level: 3

::: lbd.plot.subplots
    options:
      heading_level: 3

::: lbd.plot.apply
    options:
      heading_level: 3

::: lbd.plot.save
    options:
      heading_level: 3

## Units and labels

| You want to… | Use |
|---|---|
| readable numbers: 7e9 Hz → 7 GHz, or a prefix you choose | [`prefix`][lbd.plot.prefix] |
| an axis title with its unit, in the style's format | [`axis_label`][lbd.plot.axis_label] |

::: lbd.plot.prefix
    options:
      heading_level: 3

::: lbd.plot.axis_label
    options:
      heading_level: 3

## Plot data like the viewer

| You have… | Use |
|---|---|
| an `lbd.Dataset` or an `.lbd` file | [`plot`][lbd.plot.plot] |
| plain arrays | [`quick`][lbd.plot.quick] |

::: lbd.plot.plot
    options:
      heading_level: 3

::: lbd.plot.quick
    options:
      heading_level: 3

## Manage presets

Only needed to create, change or delete presets from code, or to reproduce the viewer's exact
style for a file. For plotting, pass the preset's name as `style=`.

| You want to… | Use |
|---|---|
| create or change a preset | [`PresetStore.save`][lbd.plot.PresetStore.save] |
| add a `.lbd.json` file as a preset | [`PresetStore.import_file`][lbd.plot.PresetStore.import_file] |
| remove a preset, or reset a built-in one | [`PresetStore.delete`][lbd.plot.PresetStore.delete] |
| see what a preset changes (only the differences) | [`PresetStore.preset`][lbd.plot.PresetStore.preset] |
| the exact style the viewer uses for a file | [`PresetStore.resolve`][lbd.plot.PresetStore.resolve] |

::: lbd.plot.PresetStore
    options:
      heading_level: 3
      members: [names, is_builtin, is_customized, preset, style, save, delete, import_file, resolve]

::: lbd.plot.config_dir
    options:
      heading_level: 3

## Errors and warnings

**Errors** stop the call: something can't be done as asked. Both are `ValueError`s.

**Warnings** mean the call worked, but something was ignored or adjusted; read them, they
usually point at a typo or a setting that doesn't apply. All are `lbd.LBDWarning`s. To silence
one kind on purpose:

```python
import warnings
import lbd.plot as lp

warnings.filterwarnings("ignore", category=lp.UnitWarning)   # or lp.RenderWarning, lbd.LBDWarning, ...
```

::: lbd.plot.StyleError
    options:
      heading_level: 3

::: lbd.plot.RenderError
    options:
      heading_level: 3

::: lbd.plot.StyleWarning
    options:
      heading_level: 3

::: lbd.plot.RenderWarning
    options:
      heading_level: 3

::: lbd.plot.UnitWarning
    options:
      heading_level: 3
