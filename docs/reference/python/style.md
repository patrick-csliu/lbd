# Style (`lbd.plot.style`)

A style is a tree of settings shaped like matplotlib's objects. Every setting, with its type,
default and allowed values, is listed in [Style settings](../../styles/settings.md); how presets,
files and overrides combine is in [How styles work](../../styles/index.md).

```
Style
├── figure: FigureStyle            size, export resolution, background
│   ├── font: FontStyle
│   └── axes: AxesStyle
│       ├── frame: FrameStyle
│       ├── title: TitleStyle
│       ├── axis: AxisStyle       label: LabelStyle, ticks: TicksStyle, minor: MinorTicksStyle
│       ├── xaxis, yaxis           partial AxisStyle overrides
│       ├── grid: GridStyle
│       ├── legend: LegendStyle
│       ├── colors                 colour cycle
│       ├── lines: LinesStyle
│       ├── scatter: ScatterStyle
│       └── image: ImageStyle     colorbar: ColorbarStyle
└── quantities: {name: QuantityStyle}
```

Every group is a pydantic model: attribute access (`style.figure.axes.frame.linewidth_pt`),
validation on assignment, and `model_dump()` for a plain dict.

::: lbd.plot.style.Style
    options:
      heading_level: 2
      members: [axis_style, to_rcparams, save, load, to_mplstyle, diff]
      show_bases: false

