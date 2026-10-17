---
hide:
  - navigation
  - toc
---

# LBD

**One data format and one viewer for consistent scientific figures.**

Save measurements from Python, MATLAB or Julia as `.lbd` files. Look at any of them by
double-clicking, and get figures that look the same for every dataset, every program and every
year: the same size, fonts, line widths, colours and colour scales.

![A data file plus a style makes a figure; the same style with any data file makes figures that match](assets/concept.svg)

The core idea: a **data file** holds what you measured, a **style** holds how figures look,
and LBD puts them together when it draws. Keep one style, and every figure matches.
[How LBD works :octicons-arrow-right-24:](getting-started/how-it-works.md)

<div class="grid cards" markdown>

-   :material-rocket-launch:{ .lg .middle } **Get started**

    ---

    Install the viewer and a language module, then take the ten-minute tour.

    [:octicons-arrow-right-24: Install](getting-started/install.md) ·
    [Quick start](getting-started/quickstart.md)

-   :material-chart-bell-curve:{ .lg .middle } **LBD Viewer**

    ---

    Browse your data folders, plot curves, scatter plots and heat maps, save a view into the
    file, export PDF, SVG or PNG.

    [:octicons-arrow-right-24: Viewer guide](viewer/index.md)

-   :material-palette-swatch:{ .lg .middle } **Styles**

    ---

    Every visual setting in one style, shaped like matplotlib's Figure → Axes tree. Presets,
    style files, fixed colour scales per quantity.

    [:octicons-arrow-right-24: How styles work](styles/index.md) ·
    [All settings](styles/settings.md)

-   :material-language-python:{ .lg .middle } **Python**

    ---

    Write and read files with `lbd`; draw your own matplotlib figures in the same style with
    `lbd.plot`.

    [:octicons-arrow-right-24: Files](python/files.md) ·
    [Plotting](python/plotting.md) ·
    [API reference](reference/python/lbd.md)

-   :material-math-integral-box:{ .lg .middle } **MATLAB and Julia**

    ---

    The same files, with the same dimension order, from MATLAB and Julia.

    [:octicons-arrow-right-24: MATLAB](matlab.md) ·
    [Julia](julia.md)

-   :material-file-tree:{ .lg .middle } **File format**

    ---

    Plain HDF5 inside, with a short specification every implementation follows.

    [:octicons-arrow-right-24: Concepts](getting-started/concepts.md) ·
    [Specification](format.md)

-   :material-image-multiple:{ .lg .middle } **Examples**

    ---

    Short scripts with their figures: save data and settings, annotations, your own figures,
    styles. Each explained step by step.

    [:octicons-arrow-right-24: Gallery](examples/index.md#gallery) ·
    [Find an example by task](examples/index.md#find-an-example-by-task)

</div>

## Examples

<div class="grid cards" markdown>

-   [![Curves](examples/img/curves_resonator.png)](examples/curves_resonator.md)

    **[Curves](examples/curves_resonator.md)**: save data and settings, plot curves

-   [![Heat map](examples/img/heatmap_single_shot.png)](examples/heatmap_single_shot.md)

    **[Heat map](examples/heatmap_single_shot.md)**: mark points, lines and regions

-   [![Scatter](examples/img/scatter_iq_readout.png)](examples/scatter_iq_readout.md)

    **[Scatter](examples/scatter_iq_readout.md)**: the I/Q plane, a colour per state

-   [![Two panels](examples/img/subplots_wigner.png)](examples/subplots_wigner.md)

    **[Two panels](examples/subplots_wigner.md)**: your own plot next to the tool's

</div>

[All examples :octicons-arrow-right-24:](examples/index.md)

## Start here

| I want to… | Read |
|---|---|
| understand the idea | [How LBD works](getting-started/how-it-works.md). |
| look at data files | [Install the viewer](getting-started/install.md#lbd-viewer-on-windows), then the [viewer guide](viewer/index.md). |
| make my programs write `.lbd` files | [Install the module](getting-started/install.md#language-modules), the [quick start](getting-started/quickstart.md) and [Concepts](getting-started/concepts.md). |
| make every figure of a paper or thesis match | [Consistent figures in your own code](styles/consistent-figures.md) and [fixed scales per quantity](styles/scales-and-units.md#fixed-scales-per-quantity). |
| work on LBD itself | The [developer guide](developers/index.md). |
| add support for another language | [Adding a language](developers/adding-a-language.md). |

!!! tip "This documentation works offline"
    LBD Viewer ships a copy of this site: use **Help** in the viewer's top bar. Search works
    without a network connection too.
