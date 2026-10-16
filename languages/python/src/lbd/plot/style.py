"""LBD figure styles, organised like matplotlib's own object tree.

    Style
    ├── figure                 matplotlib Figure: size, export dpi, background, font
    │   ├── font
    │   └── axes               matplotlib Axes
    │       ├── frame            the four spines
    │       ├── title
    │       ├── axis             both XAxis and YAxis: label, ticks, minor ticks
    │       ├── xaxis / yaxis    optional overrides of `axis` for one of them
    │       ├── grid, legend
    │       ├── colors           colour cycle
    │       └── lines, scatter, image (+ colorbar)   defaults of the plotted elements
    └── quantities             fixed scales per quantity (LBD-specific)

`Style.to_rcparams()` turns a style into matplotlib rcParams, so the same style drives the LBD
viewer, `lbd.plot` and any hand-written matplotlib code.
"""

from __future__ import annotations

import copy
import difflib
import functools
import json
import math
import typing
from pathlib import Path
from typing import Any, Dict, List, Literal, Mapping, Optional, Tuple, Union

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from typing_extensions import Annotated

import lbd
from lbd.io import _warn

from .units import normalize_prefix

STYLE_VERSION = 2
STYLE_SUFFIX = ".lbd.json"
OKABE_ITO = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9", "#F0E442", "#000000"]
# The default colour cycle: Okabe-Ito (colour-blind safe), ordered so the first colours also differ
# in grey (black 0.00, blue 0.34, orange 0.64 lightness): figures stay readable in greyscale print.
# Yellow is left out (too light on white).
DEFAULT_COLORS = ["#000000", "#0072B2", "#E69F00", "#D55E00", "#56B4E9", "#009E73", "#CC79A7"]
MM = 1 / 25.4


class StyleError(ValueError):
    """A style has invalid settings, or a style file or preset can't be read.

    The message names the setting, e.g. `figure.font.size_pt`, and for an unknown setting it
    suggests the closest known one. Drawing with a font that isn't installed is also a
    `StyleError`; its message lists the fonts that can be used instead.
    """


class StyleWarning(lbd.LBDWarning):
    """A style was used, but part of it was ignored or converted.

    For example: a style stored in an `.lbd` file (perhaps by a newer LBD) has settings this
    version doesn't know.
    """


LEGEND_LOCATIONS = ("best", "upper right", "upper left", "lower left", "lower right", "right",
                    "center left", "center right", "lower center", "upper center", "center")


def _color(v: str) -> str:
    import matplotlib.colors as mcolors

    if not mcolors.is_color_like(v):
        raise ValueError(f"{v!r} is not a colour; use a name ('black'), hex ('#0072B2') or 'none'")
    return v


def _cmap(v: str) -> str:
    import matplotlib

    if v not in matplotlib.colormaps:
        close = difflib.get_close_matches(v, list(matplotlib.colormaps), n=3)
        hint = f"; did you mean {', '.join(close)}?" if close else "; e.g. viridis, magma, cividis, RdBu_r"
        raise ValueError(f"unknown colour map {v!r}{hint}")
    return v


def _marker(v: str) -> str:
    if v == "":
        return v
    from matplotlib.markers import MarkerStyle

    try:
        MarkerStyle(v)
    except ValueError:
        raise ValueError(f"{v!r} is not a matplotlib marker; e.g. o, s, ^, v, x, +, ., D") from None
    return v


Color = Annotated[str, AfterValidator(_color)]
Cmap = Annotated[str, AfterValidator(_cmap)]
Marker = Annotated[str, AfterValidator(_marker)]


class _Model(BaseModel):
    # Unknown keys are errors (a typo must not vanish), and assignments are checked too.
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    def __setattr__(self, name: str, value: Any) -> None:
        try:
            super().__setattr__(name, value)
        except ValidationError as e:
            raise StyleError(f"invalid style: {_problems(e)}") from None


# ---- the tree ------------------------------------------------------------------------


class FontStyle(_Model):
    """Text of the whole figure (`figure.font`).
    """
    family: str = Field("Arial", description="Font name, or serif / sans-serif / monospace. "
                                             "Must be installed: drawing with a missing font is an error")
    size_pt: float = Field(10.0, gt=3, le=40, description="Size of all text (axis titles, tick numbers, legend, title)")
    math: Literal["dejavusans", "dejavuserif", "cm", "stix", "stixsans"] = Field(
        "dejavusans", description="Font for math between $...$")


class FrameStyle(_Model):
    """The four spines around the plotting area (`figure.axes.frame`).
    """
    linewidth_pt: float = Field(0.6, gt=0, le=5, description="Line width of the frame")
    color: Color = Field("black", description="Frame colour")
    top: bool = Field(True, description="Show the top side")
    right: bool = Field(True, description="Show the right side")
    bottom: bool = Field(True, description="Show the bottom side")
    left: bool = Field(True, description="Show the left side")


class TitleStyle(_Model):
    """The title above the plot (`figure.axes.title`), shown when a plot spec has a `title`.
    """
    size_pt: Optional[float] = Field(None, gt=3, le=60, description="Empty: the font size")
    weight: Literal["normal", "bold"] = Field("normal", description="Font weight of the title")
    pad_pt: float = Field(4.0, ge=0, le=50, description="Gap between title and plot")


class LabelStyle(_Model):
    """An axis title such as *Frequency (GHz)* (`figure.axes.axis.label`).
    """
    size_pt: Optional[float] = Field(None, gt=3, le=60, description="Empty: the font size")
    pad_pt: float = Field(3.0, ge=0, le=50, description="Gap between label and tick labels")
    unit_format: Literal["paren", "bracket", "slash"] = Field(
        "paren", description="'Frequency (GHz)', 'Frequency [GHz]' or 'Frequency / GHz'")
    auto_prefix: bool = Field(True, description="Automatic unit prefixes for base units, e.g. Hz -> GHz")


class TicksStyle(_Model):
    """Major ticks and their numbers (`figure.axes.axis.ticks`).
    """
    direction: Literal["in", "out", "inout"] = Field("in", description="Which way tick marks point")
    length_pt: float = Field(3.5, ge=0, le=20, description="Major tick length")
    width_pt: Optional[float] = Field(None, gt=0, le=5, description="Empty: the frame line width")
    label_size_pt: Optional[float] = Field(None, gt=3, le=60, description="Empty: the font size")
    mirror: bool = Field(True, description="Ticks on the opposite side too (top / right)")


class MinorTicksStyle(_Model):
    """Minor ticks (`figure.axes.axis.minor`).
    """
    visible: bool = Field(True, description="Show minor ticks")
    length_pt: float = Field(2.0, ge=0, le=20, description="Minor tick length")
    width_pt: Optional[float] = Field(0.5, gt=0, le=5, description="Minor tick width. Empty: 75 % of the frame line width")


class AxisStyle(_Model):
    """An axis (matplotlib's XAxis / YAxis): its label, major ticks and minor ticks.

    `figure.axes.axis` applies to both axes; `figure.axes.xaxis` / `yaxis` hold only the
    settings that differ for one of them.
    """
    label: LabelStyle = Field(default_factory=LabelStyle, description="The axis title, e.g. Frequency (GHz)")
    ticks: TicksStyle = Field(default_factory=TicksStyle, description="Major ticks and their numbers")
    minor: MinorTicksStyle = Field(default_factory=MinorTicksStyle, description="Minor ticks")


class GridStyle(_Model):
    """Grid lines at the ticks (`figure.axes.grid`).
    """
    visible: bool = Field(False, description="Grid lines at the ticks")
    which: Literal["major", "minor", "both"] = Field("major", description="At which ticks")
    linewidth_pt: Optional[float] = Field(0.5, gt=0, le=5, description="Grid line width. Empty: half the frame line width")
    color: Color = Field("#b0b0b0", description="Grid line colour")
    alpha: float = Field(0.5, ge=0, le=1, description="Opacity")
    linestyle: Literal["-", "--", ":", "-."] = Field("-", description="Grid line style")


class LegendStyle(_Model):
    """The legend (`figure.axes.legend`).
    """
    visible: bool = Field(True, description="Show a legend when there is more than one curve")
    frame: bool = Field(False, description="Draw a box around the legend")
    location: Literal[LEGEND_LOCATIONS] = Field("best", description="Where the legend goes")
    size_pt: Optional[float] = Field(None, gt=3, le=60, description="Empty: the font size")
    max_entries: int = Field(6, ge=1, le=100, description="Hide the legend above this many entries")


class LinesStyle(_Model):
    """Curves (`figure.axes.lines`).
    """
    width_pt: float = Field(1.0, gt=0, le=10, description="Line width")
    style: Literal["-", "--", ":", "-."] = Field("-", description="Line style")
    marker: Marker = Field("", description="Marker on every point, e.g. 'o'; empty for none")
    marker_size_pt: float = Field(3.5, gt=0, le=30, description="Marker size")


class ScatterStyle(_Model):
    """Markers of scatter plots (`figure.axes.scatter`).
    """
    marker: Marker = Field("o", description="Matplotlib marker, e.g. o, s, ^, x, .")
    size_pt: float = Field(2.5, gt=0, le=30, description="Marker diameter")
    alpha: float = Field(0.6, ge=0, le=1, description="Opacity")
    edgecolor: Color = Field("none", description="Marker edge colour, or none")
    edgewidth_pt: float = Field(0.0, ge=0, le=5, description="Marker edge width")


class ColorbarStyle(_Model):
    """The colour bar next to heat maps and colour-coded scatter plots.
    """
    visible: bool = Field(True, description="Show a colour bar")
    size_pct: float = Field(5.0, gt=0, le=50, description="Colour bar width, % of the plot width")
    pad_pct: float = Field(3.0, ge=0, le=50, description="Gap to the plot, % of the plot width")


class ImageStyle(_Model):
    """Heat maps and colour scales in general (`figure.axes.image`).
    """
    cmap: Cmap = Field("viridis", description="Matplotlib colour map")
    colorbar: ColorbarStyle = Field(default_factory=ColorbarStyle, description="The colour bar next to heat maps")


class AxesStyle(_Model):
    """The plotting area, matplotlib's Axes (`figure.axes`): frame, axes, grid, legend, colours and plotted elements.
    """
    facecolor: Color = Field("white", description="Background of the plotting area")
    frame: FrameStyle = Field(default_factory=FrameStyle, description="The four spines")
    title: TitleStyle = Field(default_factory=TitleStyle, description="The title above the plot")
    axis: AxisStyle = Field(default_factory=AxisStyle, description="Both axes: label, ticks, minor ticks")
    # Partial AxisStyle dicts; merged over `axis` for that axis only.
    xaxis: Dict[str, Any] = Field(default_factory=dict, description="Settings of `axis` that differ for the x axis only")
    yaxis: Dict[str, Any] = Field(default_factory=dict, description="Settings of `axis` that differ for the y axis only")
    grid: GridStyle = Field(default_factory=GridStyle, description="Grid lines")
    legend: LegendStyle = Field(default_factory=LegendStyle, description="The legend")
    colors: List[Color] = Field(default_factory=lambda: list(DEFAULT_COLORS), min_length=1,
                                description="Colour cycle (default: Okabe-Ito, ordered to differ in greyscale)")
    lines: LinesStyle = Field(default_factory=LinesStyle, description="Curves")
    scatter: ScatterStyle = Field(default_factory=ScatterStyle, description="Scatter markers")
    image: ImageStyle = Field(default_factory=ImageStyle, description="Heat maps and colour scales")

    @field_validator("xaxis", "yaxis")
    @classmethod
    def _partial_axis(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        unknown = _unknown_keys(v, AxisStyle)
        if unknown:
            raise ValueError("unknown setting(s) " + ", ".join(unknown))
        try:
            AxisStyle.model_validate(deep_merge(AxisStyle().model_dump(), v))
        except ValidationError as e:
            raise ValueError(_problems(e)) from None
        return v


class FigureStyle(_Model):
    """The figure (`figure`): size, export resolution, background, font, and the axes in it.
    """
    width_mm: float = Field(85.0, gt=10, le=1000, description="Figure width (85 mm = one journal column)")
    height_mm: float = Field(64.0, gt=10, le=1000, description="Figure height")
    dpi: int = Field(600, ge=50, le=2400, description="Resolution of PNG exports and raster parts")
    facecolor: Color = Field("white", description="Background of the whole figure")
    font: FontStyle = Field(default_factory=FontStyle, description="Text of the whole figure")
    axes: AxesStyle = Field(default_factory=AxesStyle, description="The plotting area")


class QuantityStyle(_Model):
    """Fixed scales for one quantity, so plots from different files can be compared.

    Used under `Style.quantities`, keyed by a value name, `<value name>.<complex mode>`
    (e.g. `S21.db`) or a value label. Limits are in the value's own unit.
    """
    vmin: Optional[float] = Field(None, description="Lower limit, in the value's own unit. Empty: automatic")
    vmax: Optional[float] = Field(None, description="Upper limit, in the value's own unit. Empty: automatic")
    cmap: Optional[Cmap] = Field(None, description="Colour map for this quantity. Empty: image.cmap")
    scale: Literal["linear", "log"] = Field("linear", description="Linear or logarithmic colour scale / vertical axis")
    prefix: Optional[str] = Field(
        None, description="Fixed unit prefix, e.g. M for MHz, m for mV, '' for none. Empty: automatic")

    @field_validator("prefix")
    @classmethod
    def _known_prefix(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else normalize_prefix(v)

    @model_validator(mode="after")
    def _limits(self) -> "QuantityStyle":
        for name in ("vmin", "vmax"):
            v = getattr(self, name)
            if v is not None and not math.isfinite(v):
                raise ValueError(f"{name} must be a finite number")
        if self.vmin is not None and self.vmax is not None and not self.vmin < self.vmax:
            raise ValueError(f"vmin ({self.vmin:g}) must be smaller than vmax ({self.vmax:g})")
        if self.scale == "log" and self.vmin is not None and self.vmin <= 0:
            raise ValueError("a log scale needs vmin > 0")
        return self


class Style(_Model):
    """A complete LBD figure style.

    Settings follow matplotlib's object tree (`style.figure.axes.frame.linewidth_pt`); every
    setting is listed in [Style settings](../../styles/settings.md). Get one with
    [`lbd.plot.load_style`][lbd.plot.load_style]; a `Style()` without arguments holds the
    built-in defaults.

    **Use it when** you want to read or change settings in Python, make a variant of a preset,
    or save a style file. To *use* a style, pass it (or just its preset name) as `style=` to any
    `lbd.plot` function.

    Settings are checked when they are set: `s.figure.width_mm = -5` raises `StyleError`, and
    so does a setting that doesn't exist.

    Examples
    --------
    >>> s = lp.load_style("thesis")
    >>> s.figure.width_mm = 170
    >>> s.save("thesis-wide.lbd.json")
    """
    lbd_style: int = Field(STYLE_VERSION, ge=1, description="Style format version (2)")
    name: Optional[str] = Field(None, description="Name of the style (presets and style files)")
    description: str = Field("", description="Free text, e.g. what the style is for")
    figure: FigureStyle = Field(default_factory=FigureStyle, description="The figure and everything in it")
    # Key: value name, "<value name>.<complex mode>" (e.g. "S21.db"), or value label.
    quantities: Dict[str, QuantityStyle] = Field(
        default_factory=dict,
        description="Fixed scales per quantity. Key: value name, `<value>.<complex mode>` (e.g. `S21.db`), or label")

    @field_validator("lbd_style")
    @classmethod
    def _version(cls, v: int) -> int:
        if v < STYLE_VERSION:
            raise ValueError(f"style version {v} is not supported (expected {STYLE_VERSION})")
        if v > STYLE_VERSION:
            _warn(f"this style was made for a newer LBD (style version {v}, this LBD reads {STYLE_VERSION}); "
                  "settings it doesn't know are ignored", StyleWarning)
        return v

    # -- derived views

    def axis_style(self, which: Literal["x", "y"]) -> AxisStyle:
        """The effective settings of one axis: `axis` with `xaxis` / `yaxis` merged in.

        Use it to read what the x or the y axis really gets, when a style has per-axis
        overrides (`figure.axes.yaxis`).

        Parameters
        ----------
        which : {"x", "y"}

        Returns
        -------
        AxisStyle

        Raises
        ------
        ValueError
            `which` is not `"x"` or `"y"`.
        """
        if which not in ("x", "y"):
            raise ValueError(f"which must be 'x' or 'y', not {which!r}")
        ax = self.figure.axes
        override = ax.xaxis if which == "x" else ax.yaxis
        if not override:
            return ax.axis
        return AxisStyle.model_validate(deep_merge(ax.axis.model_dump(), override))

    def to_rcparams(self, check_font: bool = True) -> Dict[str, Any]:
        """The style as matplotlib rcParams.

        Used by LBD's renderer, [`lbd.plot.use`][lbd.plot.use] and the `.mplstyle` export. Use
        it directly only to combine LBD's settings with your own, e.g.
        `matplotlib.rc_context({**s.to_rcparams(), "lines.linewidth": 3})`.

        Parameters
        ----------
        check_font : bool
            Check that `figure.font.family` is installed (default). Without the check,
            matplotlib would quietly draw with another font.

        Returns
        -------
        dict
            rcParam name → value, e.g. `{"figure.figsize": (3.35, 2.52), "font.size": 10.0, ...}`.

        Raises
        ------
        StyleError
            The font isn't installed on this computer; the message lists fonts that are.
        """
        from cycler import cycler

        f = self.figure
        a = f.axes
        if check_font:
            check_font_installed(f.font.family)
        family = [f.font.family]
        frame_w = a.frame.linewidth_pt
        x, y = self.axis_style("x"), self.axis_style("y")
        rc: Dict[str, Any] = {
            "figure.figsize": (f.width_mm * MM, f.height_mm * MM),
            # The tool lays out every figure this way; plain plt.subplots() should do the same, or
            # labels get cut off at the figure's fixed size.
            "figure.constrained_layout.use": True,
            "figure.facecolor": f.facecolor,
            "savefig.dpi": f.dpi,
            "font.family": family,
            "font.size": f.font.size_pt,
            "mathtext.fontset": f.font.math,
            "axes.facecolor": a.facecolor,
            "axes.edgecolor": a.frame.color,
            "axes.linewidth": frame_w,
            "axes.spines.top": a.frame.top,
            "axes.spines.right": a.frame.right,
            "axes.spines.bottom": a.frame.bottom,
            "axes.spines.left": a.frame.left,
            "axes.titlesize": a.title.size_pt if a.title.size_pt else "medium",
            "axes.titleweight": a.title.weight,
            "axes.titlepad": a.title.pad_pt,
            "axes.labelsize": x.label.size_pt if x.label.size_pt else "medium",
            "axes.labelpad": x.label.pad_pt,
            "axes.prop_cycle": cycler(color=a.colors),
            "axes.grid": a.grid.visible,
            "axes.grid.which": a.grid.which,
            "axes.formatter.useoffset": False,
            "axes.formatter.use_mathtext": True,
            "axes.unicode_minus": True,
            "grid.linewidth": a.grid.linewidth_pt if a.grid.linewidth_pt else 0.5 * frame_w,
            "grid.color": a.grid.color,
            "grid.alpha": a.grid.alpha,
            "grid.linestyle": a.grid.linestyle,
            "legend.frameon": a.legend.frame,
            "legend.loc": a.legend.location,
            "legend.fontsize": a.legend.size_pt if a.legend.size_pt else "medium",
            "lines.linewidth": a.lines.width_pt,
            "lines.linestyle": a.lines.style,
            "lines.marker": a.lines.marker or "None",
            "lines.markersize": a.lines.marker_size_pt,
            "scatter.marker": a.scatter.marker,
            "scatter.edgecolors": a.scatter.edgecolor,
            "image.cmap": a.image.cmap,
            "svg.fonttype": "path",   # text as outlines: identical on every computer
            "pdf.fonttype": 42,       # embedded TrueType, as journals require
            "ps.fonttype": 42,
        }
        for t, s in (("xtick", x), ("ytick", y)):
            rc[f"{t}.direction"] = s.ticks.direction
            rc[f"{t}.major.size"] = s.ticks.length_pt
            rc[f"{t}.major.width"] = s.ticks.width_pt if s.ticks.width_pt else frame_w
            rc[f"{t}.labelsize"] = s.ticks.label_size_pt if s.ticks.label_size_pt else "medium"
            rc[f"{t}.minor.visible"] = s.minor.visible
            rc[f"{t}.minor.size"] = s.minor.length_pt
            rc[f"{t}.minor.width"] = s.minor.width_pt if s.minor.width_pt else 0.75 * frame_w
        rc["xtick.top"] = x.ticks.mirror
        rc["ytick.right"] = y.ticks.mirror
        return rc

    # -- files

    def save(self, path: Union[str, Path]) -> Path:
        """Write the complete style as a `.lbd.json` style file.

        Use it to keep a style next to a paper's data or to send it to someone: the file works
        on any computer (`style="thesis.lbd.json"`) and can be imported in the viewer.

        Parameters
        ----------
        path : str or path-like
            Output file, normally `<name>.lbd.json`.

        Returns
        -------
        pathlib.Path
        """
        path = Path(path)
        data = self.model_dump()
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Union[str, Path]) -> "Style":
        """Read a `.lbd.json` style file. `lp.load_style(path)` does the same.

        Complete or partial files are accepted; missing settings take the defaults. Settings this version doesn't know (a file from a newer LBD, or a
        typo) are left out with a `StyleWarning`.

        Parameters
        ----------
        path : str or path-like

        Returns
        -------
        Style

        Raises
        ------
        StyleError
            Unreadable file or invalid settings.

        Warns
        -----
        StyleWarning
            Unknown settings were left out.
        """
        return from_dict(read_style_file(path), unknown="warn", where=Path(path).name)

    def to_mplstyle(self) -> str:
        """The style in matplotlib's `.mplstyle` format.

        Use it to give the style to people without LBD: `plt.style.use("file.mplstyle")` gives the same size, fonts,
        frame, ticks, colours and line widths. LBD-only settings (unit format, unit prefixes, fixed
        scales, colour bar size, scatter size/opacity) are not part of matplotlib and are left out.

        Returns
        -------
        str
            The file content.
        """
        return rcparams_to_mplstyle(self.to_rcparams(check_font=False), title=self.name or "LBD style")

    def diff(self) -> Dict[str, Any]:
        """Only the settings that differ from the built-in defaults (how presets are stored).

        Use it to see what a style changes, or to store a variant as a preset:
        `lp.PresetStore().save("wide", s.diff())`.

        Returns
        -------
        dict
        """
        return deep_diff(self.model_dump(), Style().model_dump())


# ---- helpers ------------------------------------------------------------------------


def deep_merge(base: Dict[str, Any], over: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """A copy of `base` with `over` merged in. Nested dicts merge; other values replace."""
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def deep_diff(value: Dict[str, Any], base: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in value.items():
        b = base.get(k)
        if isinstance(v, dict) and isinstance(b, dict) and v and b:
            d = deep_diff(v, b)
            if d:
                out[k] = d
        elif v != b:
            out[k] = copy.deepcopy(v)
    return out


GENERIC_FAMILIES = ("serif", "sans-serif", "monospace", "cursive", "fantasy")
ALWAYS_AVAILABLE_FONTS = ("DejaVu Sans", "DejaVu Serif")   # ship with matplotlib


@functools.lru_cache(maxsize=None)
def _font_problem(family: str) -> Optional[str]:
    """None if `family` can be drawn, else the error message (cached: the font lookup is slow)."""
    if family in GENERIC_FAMILIES:
        return None
    from matplotlib import font_manager

    try:
        font_manager.findfont(font_manager.FontProperties(family=family), fallback_to_default=False)
        return None
    except ValueError:
        pass
    installed = sorted({f.name for f in font_manager.fontManager.ttflist})
    similar = [n for n in difflib.get_close_matches(family, installed, n=4, cutoff=0.5)
               if n not in ALWAYS_AVAILABLE_FONTS]
    return (f"figure.font.family: the font {family!r} is not installed on this computer. Install it, "
            f"or use a font that is: {', '.join(ALWAYS_AVAILABLE_FONTS)} (always available)"
            + (f"; similar installed fonts: {', '.join(similar)}" if similar else "")
            + f"; or a generic family: {', '.join(GENERIC_FAMILIES[:3])}.")


def check_font_installed(family: str) -> None:
    """Raise StyleError, naming the fonts that can be used instead, if `family` isn't installed."""
    problem = _font_problem(family)
    if problem:
        raise StyleError(problem)


def _submodel(annotation: Any) -> Tuple[Optional[type], bool]:
    """(model class, is a dict of models) for a field annotation, else (None, False)."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation, False
    origin, args = typing.get_origin(annotation), typing.get_args(annotation)
    if origin in (dict, Dict) and len(args) == 2 and isinstance(args[1], type) and issubclass(args[1], BaseModel):
        return args[1], True
    return None, False


def _unknown_keys(data: Any, model: type, prefix: str = "") -> List[str]:
    """Paths of keys in `data` that `model` doesn't have, with a suggestion where one is close."""
    if not isinstance(data, Mapping):
        return []
    out = []
    fields = model.model_fields
    for key, val in data.items():
        path = f"{prefix}{key}"
        if key not in fields:
            close = difflib.get_close_matches(str(key), list(fields), n=1)
            out.append(f"'{path}'" + (f" (did you mean '{prefix}{close[0]}'?)" if close else ""))
            continue
        if model is AxesStyle and key in ("xaxis", "yaxis"):
            out += _unknown_keys(val, AxisStyle, path + ".")
            continue
        sub, is_dict = _submodel(fields[key].annotation)
        if sub is not None and is_dict and isinstance(val, Mapping):
            for name, item in val.items():
                out += _unknown_keys(item, sub, f"{path}.{name}.")
        elif sub is not None:
            out += _unknown_keys(val, sub, path + ".")
    return out


def _strip_unknown(data: Any, model: type) -> Any:
    """A copy of `data` without the keys `model` doesn't know (see _unknown_keys)."""
    if not isinstance(data, Mapping):
        return data
    fields = model.model_fields
    out = {}
    for key, val in data.items():
        if key not in fields:
            continue
        if model is AxesStyle and key in ("xaxis", "yaxis"):
            out[key] = _strip_unknown(val, AxisStyle)
            continue
        sub, is_dict = _submodel(fields[key].annotation)
        if sub is not None and is_dict and isinstance(val, Mapping):
            out[key] = {n: _strip_unknown(item, sub) for n, item in val.items()}
        elif sub is not None:
            out[key] = _strip_unknown(val, sub)
        else:
            out[key] = val
    return out


def _problems(e: ValidationError) -> str:
    parts = []
    for err in e.errors():
        loc = ".".join(str(p) for p in err["loc"])
        msg = err["msg"]
        if msg.startswith("Value error, "):
            msg = msg[len("Value error, "):]
        parts.append(f"{loc}: {msg}" if loc else msg)
    return "; ".join(parts)


def from_dict(data: Optional[Mapping[str, Any]], base: Optional[Dict[str, Any]] = None,
              unknown: str = "error", where: str = "") -> Style:
    """A complete Style from a (partial) dict, merged over `base` or the defaults.

    unknown="error": a setting that doesn't exist raises StyleError (direct input: a typo).
    unknown="warn": it is left out with a StyleWarning (styles read from files).
    """
    if unknown not in ("error", "warn"):
        raise ValueError("unknown must be 'error' or 'warn'")
    if data is None:
        data = {}
    if not isinstance(data, Mapping):
        raise StyleError(f"a style must be a JSON object (dict), not {type(data).__name__}")
    problems = _unknown_keys(data, Style)
    if problems:
        text = f"unknown style setting(s) {', '.join(problems)}"
        if unknown == "error":
            raise StyleError(text)
        _warn(f"{where + ': ' if where else ''}{text} ignored", StyleWarning)
        data = _strip_unknown(data, Style)
    merged = deep_merge(base or Style().model_dump(), data)
    return validate(merged)


def validate(data: Dict[str, Any]) -> Style:
    """A Style from a complete dict; StyleError (naming the setting) if anything is invalid."""
    try:
        return Style.model_validate(data)
    except ValidationError as e:
        raise StyleError(f"invalid style: {_problems(e)}") from None


def read_style_file(path: Union[str, Path]) -> Dict[str, Any]:
    """The JSON object in a style file; StyleError if it can't be read or isn't an object."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise StyleError(f"style file not found: {path}") from None
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise StyleError(f"{path.name} is not a valid style file (JSON): {e}") from None
    except OSError as e:
        raise StyleError(f"can't read the style file {path}: {e.strerror or e}") from None
    if not isinstance(data, dict):
        raise StyleError(f"{path.name}: a style file must contain a JSON object")
    return data


def _mpl_value(key: str, v: Any) -> str:
    if key == "axes.prop_cycle":
        colors = [c.lstrip("#") for c in v.by_key()["color"]]
        return "cycler('color', [" + ", ".join(repr(c) for c in colors) + "])"
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, (list, tuple)):
        return ", ".join(_mpl_value(key, x) for x in v)
    if isinstance(v, str) and v.startswith("#"):
        return v[1:]  # '#' starts a comment in .mplstyle files
    if isinstance(v, float):
        return repr(v)
    return str(v)


def rcparams_to_mplstyle(rc: Dict[str, Any], title: str = "LBD style") -> str:
    lines = [
        f"# {title}",
        "# Exported from LBD. Use with: plt.style.use('this-file.mplstyle')",
        "# LBD-only settings (unit format, unit prefixes, fixed scales per quantity, colour bar size,",
        "# scatter size/opacity) are not part of matplotlib and are not included.",
        "",
    ]
    for k in sorted(rc):
        lines.append(f"{k}: {_mpl_value(k, rc[k])}")
    return "\n".join(lines) + "\n"
