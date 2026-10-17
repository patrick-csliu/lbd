"""Public functions of lbd.plot (see the "Plotting with lbd.plot" documentation page)."""

from __future__ import annotations

import contextlib
import math
import numbers
import os
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple, Union

import matplotlib
import numpy as np

import lbd
from lbd.io import _warn

from . import render as _r
from .presets import PresetStore, default_preset_name
from .style import MM, STYLE_SUFFIX, Style, StyleError, StyleWarning, from_dict
from .units import axis_label as _axis_label
from .units import prefix_scale

StyleLike = Union[None, str, "os.PathLike[str]", Mapping[str, Any], Style]
SPEC_KEYS = frozenset(_r.SPEC_KEYS - {"kind", "values"})
_QUICK_SPEC_KEYS = frozenset({"complex", "x_scale", "y_scale", "annotations"})


# ---- styles ---------------------------------------------------------------------


def list_styles() -> List[str]:
    """Names of all style presets: the built-in ones and those made on LBD Viewer's Styles page.

    Use it to see which names you can pass as `style=` anywhere in `lbd.plot`. The viewer and
    Python share one folder: `%APPDATA%\\lbd\\styles` on Windows, `~/.config/lbd/styles` on
    Linux, or `$LBD_CONFIG_DIR/styles`.

    Returns
    -------
    list of str
        `"default"` first, then the others alphabetically.

    See Also
    --------
    load_style : the complete settings of one of them.
    PresetStore : create, change or delete presets.

    Examples
    --------
    >>> lp.list_styles()
    ['default', 'thesis']
    """
    return PresetStore().names()


def default_style() -> Style:
    """The style of the preset chosen as default on LBD Viewer's Styles page.

    This is what every function uses when you don't pass `style=`. Use it to look at the
    settings your figures get by default.

    Returns
    -------
    Style
        That preset's complete style, or the built-in `default` if none was chosen.

    Warns
    -----
    StyleWarning
        The chosen default preset no longer exists, or the viewer's settings file is broken.
    """
    return PresetStore().style(default_preset_name())


def load_style(style: StyleLike = None) -> Style:
    """A complete style from a preset name, a style file, a dict, or a Style.

    Use it to look at or change settings in Python (`s.figure.width_mm`), to start a variant
    of a preset, or to save a style file. Every `style=` argument in `lbd.plot` accepts the
    same forms, so you rarely need to call it just to plot.

    Parameters
    ----------
    style : str, path, dict or Style, optional
        - a preset name (`"thesis"`);
        - a style file: a path ending in `.json`, a path with a folder, or an existing file
          that isn't also a preset name;
        - a dict of (partial) settings, merged over the defaults;
        - a `Style` (a copy is returned);
        - `None`: the default preset chosen on the viewer's Styles page.

    Returns
    -------
    Style
        A complete, validated style (a copy; changing it changes nothing else).

    Raises
    ------
    StyleError
        Unknown preset (the message lists the available ones), unreadable style file, an
        unknown setting in a dict (with the closest known name), or an invalid value (the
        message names the setting, e.g. `figure.font.size_pt`).
    TypeError
        `style` is of another type.

    Warns
    -----
    StyleWarning
        A style *file* has settings this version doesn't know; they are ignored.

    Examples
    --------
    >>> s = lp.load_style("thesis")
    >>> s = lp.load_style("figs/paper.lbd.json")
    >>> s = lp.load_style({"figure": {"width_mm": 120}})
    >>> s.figure.width_mm
    120.0
    """
    if style is None:
        return default_style()
    if isinstance(style, Style):
        return style.model_copy(deep=True)
    if isinstance(style, Mapping):
        return from_dict(dict(style))
    if not isinstance(style, (str, os.PathLike)):
        raise TypeError(f"style must be a preset name, a style file, a dict or a Style, not {type(style).__name__}")
    text = os.fspath(style)
    if not text:
        raise StyleError("style must not be empty; use None for the default style")
    path = Path(text).expanduser()
    store = PresetStore()
    looks_like_path = isinstance(style, os.PathLike) or path.suffix.lower() == ".json" or len(path.parts) > 1
    if not looks_like_path and text in store.names():
        return store.style(text)
    if looks_like_path or path.is_file():
        s = Style.load(path)
        if not s.name:
            s.name = path.name[: -len(STYLE_SUFFIX)] if path.name.endswith(STYLE_SUFFIX) else path.stem
        return s
    raise StyleError(f"no style preset named {text!r}; available: {', '.join(store.names())}")


@contextlib.contextmanager
def use(style: StyleLike = None) -> Iterator[Style]:
    """Draw your own matplotlib figures in a style, inside a `with` block.

    **Use it when** you make a figure LBD Viewer doesn't offer (fits, histograms, combined
    panels) and want it to match the others. Inside the block, `plt.subplots()` /
    `plt.figure()` get the style's size and constrained layout; lines, markers, colours, fonts,
    frame, ticks and grid follow the style; and `fig.savefig()` uses the style's dpi and embeds
    fonts. Afterwards matplotlib's previous settings come back.

    Create, draw **and save** inside the block: matplotlib reads some settings while drawing.
    To save later, use [`save`][lbd.plot.save].

    Parameters
    ----------
    style : str, path, dict or Style, optional
        As for [`load_style`][lbd.plot.load_style]. `None`: the default preset.

    Yields
    ------
    Style
        The style in use.

    See Also
    --------
    activate : the same for a whole session or notebook.
    apply : restyle a figure that was made without the style.

    Examples
    --------
    >>> with lp.use("thesis"):
    ...     fig, (a1, a2) = plt.subplots(1, 2)
    ...     a1.plot(x, y)
    ...     a2.errorbar(x, y, yerr=dy, fmt="o")
    ...     fig.savefig("fig3.pdf")
    """
    s = load_style(style)
    with matplotlib.rc_context(s.to_rcparams()):
        yield s


def activate(style: StyleLike = None) -> Style:
    """Apply a style for the rest of the session, like `plt.style.use()`.

    **Use it when** every figure of a notebook or script should have the style, so you don't
    have to wrap each one in `with lp.use(...)`. Undo with `plt.rcdefaults()` or by activating
    another style.

    Parameters
    ----------
    style : str, path, dict or Style, optional
        As for [`load_style`][lbd.plot.load_style]. `None`: the default preset.

    Returns
    -------
    Style
        The style now active.

    Examples
    --------
    >>> lp.activate("paper")
    """
    s = load_style(style)
    matplotlib.rcParams.update(s.to_rcparams())
    return s


def _size_mm(v: Any, what: str) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, numbers.Real) or not math.isfinite(v) or v <= 0:
        raise ValueError(f"{what} must be a positive number of millimetres, not {v!r}")
    return float(v)


def subplots(nrows: int = 1, ncols: int = 1, style: StyleLike = None, width_mm: Optional[float] = None,
             height_mm: Optional[float] = None, **kwargs):
    """`plt.subplots()` with the style's size (or a size you give in mm) and constrained layout.

    **Use it when** a figure needs another size than the style's (a full-width panel figure)
    or a grid of axes. Call it inside `with lp.use(style):` so what you draw follows the style
    too, or call [`apply`][lbd.plot.apply] at the end.

    Parameters
    ----------
    nrows, ncols : int, optional
        Grid of axes, as in `plt.subplots`.
    style : str, path, dict or Style, optional
        As for [`load_style`][lbd.plot.load_style]. `None`: the default preset.
    width_mm, height_mm : float, optional
        Figure size in mm instead of the style's.
    **kwargs
        Passed on to `plt.subplots` (e.g. `sharex=True`, `gridspec_kw=...`).

    Returns
    -------
    fig : matplotlib.figure.Figure
    axs : Axes or array of Axes

    Raises
    ------
    ValueError
        `nrows`/`ncols` below 1, or a size that isn't a positive number.

    Examples
    --------
    >>> with lp.use("thesis"):
    ...     fig, axs = lp.subplots(2, 1, height_mm=120, sharex=True)
    """
    import matplotlib.pyplot as plt

    for name, n in (("nrows", nrows), ("ncols", ncols)):
        if isinstance(n, bool) or not isinstance(n, numbers.Integral) or n < 1:
            raise ValueError(f"{name} must be a whole number >= 1, not {n!r}")
    s = load_style(style)
    w = _size_mm(width_mm, "width_mm") or s.figure.width_mm
    h = _size_mm(height_mm, "height_mm") or s.figure.height_mm
    if "figsize" in kwargs:
        raise TypeError("give the size as width_mm= / height_mm= instead of figsize=")
    kwargs.setdefault("layout", "constrained")
    with matplotlib.rc_context(s.to_rcparams()):
        fig, axs = plt.subplots(nrows, ncols, figsize=(w * MM, h * MM), **kwargs)
    return fig, axs


def apply(target, style: StyleLike = None) -> Style:
    """Restyle an existing figure that was made without the style.

    **Use it when** a figure comes from elsewhere (another library, old code) and you can't
    draw it inside [`use`][lbd.plot.use]. It sets the background colours; the frame (width,
    colour, visible sides); ticks (direction, length, width, mirroring, minor ticks); the grid;
    label, title, tick and legend text sizes; and the font family of existing text.

    It does **not** change what is already drawn: line and marker colours, widths and sizes,
    and the figure size stay as they are. For those, draw inside `lp.use(style)`.

    Parameters
    ----------
    target : matplotlib Figure, Axes, or a list/array of Axes
        What to restyle (a Figure restyles all its axes).
    style : str, path, dict or Style, optional
        As for [`load_style`][lbd.plot.load_style]. `None`: the default preset.

    Returns
    -------
    Style
        The style applied.

    Raises
    ------
    TypeError
        `target` is not a Figure or Axes.

    Examples
    --------
    >>> fig, ax = plt.subplots()
    >>> ax.hist(x, bins=10)
    >>> lp.apply(fig, "paper")
    """
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure, SubFigure
    from matplotlib.ticker import AutoMinorLocator, NullLocator

    if isinstance(target, (Figure, SubFigure)):
        fig, axes = target, list(target.axes)
    elif isinstance(target, Axes):
        fig, axes = target.figure, [target]
    else:
        items = list(np.ravel(np.asarray(target, dtype=object))) if isinstance(target, (list, tuple, np.ndarray)) else None
        if not items or not all(isinstance(a, Axes) for a in items):
            raise TypeError(f"target must be a matplotlib Figure, Axes or a list of Axes, not {type(target).__name__}")
        fig, axes = items[0].figure, items
    s = load_style(style)
    rc = s.to_rcparams()
    a = s.figure.axes
    font = s.figure.font
    fig.set_facecolor(s.figure.facecolor)
    for ax in axes:
        ax.set_facecolor(a.facecolor)
        for side, spine in ax.spines.items():
            if side in ("top", "right", "bottom", "left"):
                spine.set_visible(getattr(a.frame, side))
                spine.set_linewidth(a.frame.linewidth_pt)
                spine.set_edgecolor(a.frame.color)
        for name, axis in (("x", ax.xaxis), ("y", ax.yaxis)):
            st = s.axis_style(name)
            ax.tick_params(axis=name, which="major", direction=st.ticks.direction, length=st.ticks.length_pt,
                           width=rc[f"{name}tick.major.width"], labelsize=st.ticks.label_size_pt or font.size_pt,
                           color=a.frame.color)
            ax.tick_params(axis=name, which="minor", direction=st.ticks.direction, length=st.minor.length_pt,
                           width=rc[f"{name}tick.minor.width"], color=a.frame.color)
            if name == "x":
                ax.tick_params(axis="x", which="both", top=st.ticks.mirror, bottom=True)
            else:
                ax.tick_params(axis="y", which="both", right=st.ticks.mirror, left=True)
            if axis.get_scale() == "linear":
                axis.set_minor_locator(AutoMinorLocator() if st.minor.visible else NullLocator())
            elif st.minor.visible is False:
                axis.set_minor_locator(NullLocator())
            axis.label.set_size(st.label.size_pt or font.size_pt)
            axis.labelpad = st.label.pad_pt
        if a.grid.visible:
            ax.grid(True, which=a.grid.which, linewidth=rc["grid.linewidth"], color=a.grid.color,
                    alpha=a.grid.alpha, linestyle=a.grid.linestyle)
        else:
            ax.grid(False, which="both")
        ax.title.set_size(a.title.size_pt or font.size_pt)
        ax.title.set_fontweight(a.title.weight)
        texts = [ax.title, ax.xaxis.label, ax.yaxis.label, *ax.get_xticklabels(), *ax.get_yticklabels(), *ax.texts]
        legend = ax.get_legend()
        if legend is not None:
            legend.set_frame_on(a.legend.frame)
            for t in legend.get_texts():
                t.set_size(a.legend.size_pt or font.size_pt)
            texts += list(legend.get_texts())
        for t in texts:
            t.set_fontfamily(rc["font.family"])
    return s


def prefix(values, unit: str, to: str = "auto", style: StyleLike = None, axis: str = "x") -> Tuple[np.ndarray, str]:
    """Put a unit prefix on data: 7e9 Hz becomes 7 GHz (the numbers are scaled to match).

    **Use it when** you plot data yourself and want the same readable units as LBD Viewer, or
    a prefix of your choice. LBD only adds prefixes; it never converts between units (N to
    dyne): store and pass the data in the unit you want to show, then pick the prefix.

    Parameters
    ----------
    values : array_like
        The data, in `unit`.
    unit : str
        Its unit, e.g. `"Hz"`. Give the unit without a prefix (`"Hz"`, not `"GHz"`).
    to : str, optional
        - `"auto"` (default): choose the prefix from the largest absolute value, in steps of
          1000 (… µ m k M G …), like the viewer. Works for base units (`Hz s V A W Ω Ohm F H T
          K m g J C S Pa N eV Wb`); any other unit comes back unchanged, with a warning.
        - a prefix: `"q" "r" "y" "z" "a" "f" "p" "n" "µ"` (or `"u"`) `"m" "c" "d" "da" "h"
          "k" "M" "G" "T" "P" "E" "Z" "Y" "R" "Q"`, for **any** unit: `to="M"` gives MHz,
          `to="c"` on `"m"` gives cm, `to="m"` on `"Oe"` gives mOe.
        - `""`: no prefix (the data comes back unchanged).
    style : str, path, dict or Style, optional
        With `to="auto"`: if this style turns automatic prefixes off
        (`axis.label.auto_prefix`), nothing is changed. Ignored for an explicit `to`.
    axis : {"x", "y"}, optional
        Which axis's setting to read from `style`.

    Returns
    -------
    values : numpy.ndarray
        The scaled data (`values / 10**exponent`).
    unit : str
        The new unit, e.g. `"GHz"`.

    Raises
    ------
    ValueError
        Unknown prefix, a prefix for an empty unit, or `axis` not `"x"`/`"y"`.
    TypeError
        `unit` isn't a string or `values` isn't numeric.

    Warns
    -----
    UnitWarning
        `to="auto"` with a unit that gets no automatic prefix (e.g. `"dBm"`, `"Oe"`); pass a
        prefix, or `to=""` to keep the unit without the warning.

    Examples
    --------
    >>> f_ghz, f_unit = lp.prefix(np.linspace(4e9, 8e9, 401), "Hz")   # -> GHz
    >>> f_mhz, _ = lp.prefix(np.linspace(4e9, 8e9, 401), "Hz", to="M")
    >>> lp.axis_label("Frequency", f_unit)
    'Frequency (GHz)'
    """
    if axis not in ("x", "y"):
        raise ValueError(f"axis must be 'x' or 'y', not {axis!r}")
    if to == "auto" and style is not None and not load_style(style).axis_style(axis).label.auto_prefix:
        return np.asarray(values), unit
    factor, new_unit = prefix_scale(values, unit, to)
    arr = np.asarray(values)
    return (arr * factor if factor != 1.0 else arr), new_unit


def axis_label(label: str, unit: str = "", style: StyleLike = None, axis: str = "x") -> str:
    """An axis title with its unit, written the way the style says: `Frequency (GHz)`.

    **Use it when** you label your own figures, so they match the viewer's: the format
    (`Frequency (GHz)`, `Frequency [GHz]` or `Frequency / GHz`) comes from the style setting
    `axis.label.unit_format`, so changing the style changes every label. Pair it with
    [`prefix`][lbd.plot.prefix], which gives the unit.

    Parameters
    ----------
    label : str
        The quantity, e.g. `"Frequency"`.
    unit : str, optional
        The unit, e.g. `"GHz"`. Without a unit only the label is returned.
    style : str, path, dict or Style, optional
        As for [`load_style`][lbd.plot.load_style]. `None`: the default preset. Use the same
        style as the figure.
    axis : {"x", "y"}, optional
        Which axis's settings to use (they can differ with `xaxis`/`yaxis` overrides).

    Returns
    -------
    str
        `"Frequency (GHz)"`, `"Frequency [GHz]"` or `"Frequency / GHz"`.

    Raises
    ------
    ValueError
        `axis` is not `"x"` or `"y"`.
    TypeError
        `label` or `unit` is not a string.

    Examples
    --------
    >>> lp.axis_label("Frequency", "GHz", style={"figure": {"axes": {"axis": {"label": {"unit_format": "slash"}}}}})
    'Frequency / GHz'
    """
    if axis not in ("x", "y"):
        raise ValueError(f"axis must be 'x' or 'y', not {axis!r}")
    fmt = load_style(style).axis_style(axis).label.unit_format
    return _axis_label(label, unit, fmt)


_METADATA_FORMATS = {"png", "pdf", "svg"}
JPG_NOTE = ("JPG compresses with loss: thin lines and small text get blurred edges. For papers use PDF; "
            "for Word or slides use PNG")


def save(fig, path: Union[str, Path], style: StyleLike = None, title: Optional[str] = None,
         dpi: Optional[int] = None) -> Path:
    """Save a figure like LBD Viewer's export: exact size, the style's dpi, embedded fonts.

    **Use it when** you save a figure outside its `with lp.use(...)` block, or a figure from
    [`plot`][lbd.plot.plot]: it saves inside the style, so the result is identical to saving
    in the block. The format follows the extension (`.pdf`, `.svg`, `.png`, …); PDF, SVG and
    PNG get `Creator`/`Software` and `Title` metadata.

    Parameters
    ----------
    fig : matplotlib.figure.Figure
        The figure.
    path : str or path-like
        Output file, with an extension.
    style : str, path, dict or Style, optional
        As for [`load_style`][lbd.plot.load_style]. `None`: the default preset.
    title : str, optional
        Stored as the file's title metadata (PDF, SVG, PNG).
    dpi : int, optional
        Resolution instead of the style's `figure.dpi`.

    Returns
    -------
    pathlib.Path
        The file written.

    Raises
    ------
    ValueError
        No or an unsupported extension, or `dpi` not a positive whole number.
    TypeError
        `fig` is not a matplotlib Figure.

    Warns
    -----
    LBDWarning
        `title` was given for a format that can't store it; or the format is JPG, which blurs
        lines and text (use PDF or PNG for figures).

    Examples
    --------
    >>> lp.save(fig, "fig2.pdf", style="thesis", title="Power sweep")
    """
    from matplotlib.figure import Figure

    if not isinstance(fig, Figure):
        raise TypeError(f"fig must be a matplotlib Figure, not {type(fig).__name__}")
    path = Path(path)
    fmt = path.suffix.lower().lstrip(".")
    supported = fig.canvas.get_supported_filetypes()
    if not fmt:
        raise ValueError(f"{path.name} has no extension; add one such as .pdf, .svg or .png")
    if fmt not in supported:
        raise ValueError(f"can't save .{fmt} files; supported: {', '.join(sorted(supported))}")
    if dpi is not None and (isinstance(dpi, bool) or not isinstance(dpi, numbers.Integral) or dpi <= 0):
        raise ValueError(f"dpi must be a positive whole number, not {dpi!r}")
    if title is not None and not isinstance(title, str):
        raise TypeError(f"title must be text, not {type(title).__name__}")
    if title and fmt not in _METADATA_FORMATS:
        _warn(f"a title can't be stored in .{fmt} files; it is left out")
    if fmt in ("jpg", "jpeg"):
        _warn(f"{path.name}: {JPG_NOTE}")
    s = load_style(style)
    creator = f"LBD {lbd.__version__} (matplotlib {matplotlib.__version__})"
    title = title or ""
    meta: Optional[Dict[str, Any]] = {
        "png": {"Software": creator, "Title": title},
        "pdf": {"Creator": creator, "Title": title},
        "svg": {"Creator": creator, "Title": title, "Date": None},
    }.get(fmt)
    extra = {"pil_kwargs": {"quality": 95}} if fmt in ("jpg", "jpeg") else {"metadata": meta}
    with matplotlib.rc_context(s.to_rcparams()):
        fig.savefig(path, dpi=dpi or s.figure.dpi, **extra)
    return path


# ---- the tool's plot types ---------------------------------------------------------


def plot(data, kind: Optional[str] = None, values: Union[None, str, Sequence[str]] = None, *,
         style: StyleLike = None, ax=None, file_style: bool = True, **spec: Any):
    """Draw a dataset the way LBD Viewer does: curves, scatter or a heat map.

    **Use it when** your data is an `lbd.Dataset` (in memory, never saved, or read from a file)
    or an `.lbd` file and you want the viewer's figure, reproducibly. It runs the viewer's own
    drawing code, so the same data, settings and style give the same figure. Settings saved in
    the dataset's view (`d.plot`) are used unless overridden here. For plain arrays use
    [`quick`][lbd.plot.quick]; for other figure types draw inside [`use`][lbd.plot.use].

    Parameters
    ----------
    data : lbd.Dataset or path
        A dataset in memory (it never needs to be saved), or an `.lbd` file (only the needed
        values are read).
    kind : {"auto", "curve", "scatter", "heatmap"}, optional
        The plot type. `None`/`"auto"`: curves, or a heat map when the value has two or more axes
        with more than one point.
    values : str or list of str, optional
        The value(s) to plot. Default: the saved view's, else the first value with axes. Single
        numbers (values without axes) can't be plotted.
    style : optional
        As for [`load_style`][lbd.plot.load_style]. `None` works like the viewer: the dataset's
        own preset (`style_name`) if it exists here, else the default preset.
    ax : matplotlib Axes, optional
        Draw into this Axes (one panel of a larger figure) instead of a new figure.
    file_style : bool, optional
        Apply the style changes saved in the dataset (`d.style`) on top of `style`, as the
        viewer does (default). `False` uses `style` alone.
    **spec
        Plot settings: `complex` (`abs`, `db`, `phase`, `phase_deg`, `real`, `imag`, and `iq`
        for scatter), `x`, `y`, `series`, `color`, `index`, `x_scale`, `y_scale`, `title`,
        `x_label`, `y_label`, `z_label`. See the plot settings page of the documentation.

    Returns
    -------
    matplotlib.figure.Figure or Axes
        A normal matplotlib figure (or `ax`): keep editing it, then show or save it.

    Raises
    ------
    RenderError
        The plot can't be made: an unknown value or axis, a heat map of a 1-D value, an index
        out of range, … (the message lists the valid choices), or the data of a value isn't
        loaded.
    TypeError
        Unknown keyword argument, or `data` isn't a Dataset or a path.

    Warns
    -----
    RenderWarning
        A setting doesn't apply to this plot type and was ignored (e.g. `color` on a curve),
        or the file's saved view refers to something that no longer exists.

    Examples
    --------
    >>> fig = lp.plot("sweep.lbd")                                   # the file's saved view
    >>> fig = lp.plot(d, "heatmap", "S21", complex="db", style="thesis")
    >>> fig = lp.plot(d, "curve", "S21", complex="phase_deg", series="power")
    """
    unknown = set(spec) - SPEC_KEYS
    if unknown:
        raise TypeError(f"unknown plot setting(s) {sorted(unknown)}; allowed: {sorted(SPEC_KEYS)}")
    if kind is not None and not isinstance(kind, str):
        raise TypeError(f"kind must be a string such as 'curve', not {type(kind).__name__}")
    if not isinstance(file_style, bool):
        raise TypeError("file_style must be True or False")
    full_spec: Dict[str, Any] = dict(spec)
    if kind:
        full_spec["kind"] = kind
    if values is not None:
        full_spec["values"] = [values] if isinstance(values, str) else list(values)

    if isinstance(data, (str, os.PathLike)):
        header = lbd.info(data)
        import warnings

        with warnings.catch_warnings():  # checked again below, on the loaded data
            warnings.simplefilter("ignore", _r.RenderWarning)
            resolved = _r.resolve_spec(header, full_spec)
        d = lbd.load(data, values=_r.needed_values(header, resolved))
    elif isinstance(data, lbd.Dataset):
        d = data
    else:
        raise TypeError(f"data must be an lbd.Dataset or a path to an .lbd file, not {type(data).__name__}")
    resolved = _r.resolve_spec(d, full_spec)
    missing = [n for n in _r.needed_values(d, resolved) if d.values[n].data is None]
    if missing:
        raise _r.RenderError(f"the data of {missing} is not loaded (dataset read with lbd.info or "
                             "load(values=...)); load it with lbd.load(path)")

    s = _style_for(d, style, file_style)
    with matplotlib.rc_context(s.to_rcparams()):
        if ax is None:
            import matplotlib.pyplot as plt

            fig = plt.figure(figsize=(s.figure.width_mm * MM, s.figure.height_mm * MM), layout="constrained")
            _r.build_figure(d, resolved, s, fig=fig)
            return fig
        from matplotlib.axes import Axes

        if not isinstance(ax, Axes):
            raise TypeError(f"ax must be a matplotlib Axes, not {type(ax).__name__}")
        _r.build_figure(d, resolved, s, ax=ax)
        return ax


def _style_for(d: "lbd.Dataset", style: StyleLike, file_style: bool) -> Style:
    store = PresetStore()
    own = d.style if file_style else None
    if style is None:
        name = default_preset_name()
        if d.style_name:
            if d.style_name in store.names():
                name = d.style_name
            else:
                _warn(f"{(d.path.name + ': ') if d.path else ''}the style preset {d.style_name!r} named by this "
                      f"file doesn't exist here; using {name!r}", StyleWarning)
        return store.resolve(name, file_style=own)
    base = load_style(style)
    if not own:
        return base
    return from_dict(own, base=base.model_dump(), unknown="warn", where="the file's own style")


def quick(x, y=None, kind: Optional[str] = None, *, z=None, color=None,
          x_label: str = "x", x_unit: str = "", y_label: str = "y", y_unit: str = "",
          z_label: str = "z", z_unit: str = "", color_label: str = "color", color_unit: str = "",
          title: Optional[str] = None, style: StyleLike = None, ax=None, **spec: Any):
    """Plot plain arrays with LBD's look, without making a Dataset or a file.

    **Use it when** you have numbers in arrays (a fit, a simulation, a quick check) and want
    the viewer's look in one line. It builds a temporary Dataset and calls
    [`plot`][lbd.plot.plot], so the result is identical to the viewer's figures.

    Parameters
    ----------
    x : array_like
        Horizontal coordinates. Curves need 1-D `x`. For a scatter plot with `x` that isn't a
        sorted 1-D coordinate (e.g. I/Q data) the points are plotted pairwise against `y`.
    y : array_like or dict of str to array_like
        The data (same shape as `x`), or several named series (the names become the legend).
        For a heat map: the vertical coordinates.
    kind : {"curve", "scatter", "heatmap"}, optional
        Default `"curve"`, or `"heatmap"` when `z` is given.
    z : array_like, optional
        Heat-map values, shape `(len(y), len(x))`.
    color : array_like, optional
        Scatter only: colour the points by this quantity (same shape as `y`).
    x_label, x_unit, y_label, y_unit, z_label, z_unit, color_label, color_unit : str, optional
        Labels and units. Base units get automatic prefixes like in the viewer.
    title : str, optional
        Title above the plot.
    style, ax
        As for [`plot`][lbd.plot.plot].
    **spec
        `complex`, `x_scale`, `y_scale`, `annotations` (see the plot settings page).

    Returns
    -------
    matplotlib.figure.Figure or Axes

    Raises
    ------
    TypeError
        `y` missing, `color` for a curve or heat map, an unknown keyword argument.
    ValueError
        Arrays of the wrong shape or length (the message names which), empty data, an unknown
        `kind`.

    Examples
    --------
    >>> lp.quick(t, v, x_label="Time", x_unit="s", y_label="Signal", y_unit="V")
    >>> lp.quick(t, {"data": v, "fit": v_fit})
    >>> lp.quick(i, q, kind="scatter", color=power, color_label="Power", color_unit="dBm")
    >>> lp.quick(f, p, z=Z, z_label="|S21|", z_unit="dB")
    """
    unknown = set(spec) - _QUICK_SPEC_KEYS
    if unknown:
        raise TypeError(f"quick() doesn't take {sorted(unknown)}; it takes {sorted(_QUICK_SPEC_KEYS)} besides its "
                        "own arguments (use lp.plot for the other settings)")
    if kind is not None and kind not in ("curve", "scatter", "heatmap"):
        raise ValueError(f"kind must be 'curve', 'scatter' or 'heatmap', not {kind!r}")
    if y is None:
        raise TypeError("quick() needs y (and z for a heat map)")
    kind = kind or ("heatmap" if z is not None else "curve")
    extra = {"title": title} if title else {}
    d = lbd.Dataset(title=title or "")
    x = _numeric(x, "x")

    if kind == "heatmap":
        if z is None:
            raise TypeError("a heat map needs z (shape (len(y), len(x)))")
        if color is not None:
            raise TypeError("color is for scatter plots; a heat map is coloured by z")
        y_arr, z_arr = _numeric(y, "y"), _numeric(z, "z")
        if x.ndim != 1 or y_arr.ndim != 1:
            raise ValueError(f"for a heat map x and y must be 1-D coordinates, got shapes {x.shape} and {y_arr.shape}")
        if z_arr.shape != (len(y_arr), len(x)):
            raise ValueError(f"z must have shape (len(y), len(x)) = {(len(y_arr), len(x))}, got {z_arr.shape}")
        d.add_axis("x", x, unit=x_unit, label=x_label)
        d.add_axis("y", y_arr, unit=y_unit, label=y_label)
        d.add_value("z", z_arr, axes=["y", "x"], unit=z_unit, label=z_label)
        return plot(d, "heatmap", "z", style=style, ax=ax, file_style=False, **extra, **spec)
    if z is not None:
        raise TypeError(f"z is only used by heat maps, not kind={kind!r}")

    series = dict(y) if isinstance(y, Mapping) else {y_label: y}
    if not series:
        raise ValueError("y is an empty dict; give at least one series")
    arrays = {str(lab): _numeric(arr, f"y[{lab!r}]" if isinstance(y, Mapping) else "y") for lab, arr in series.items()}
    for lab, arr in arrays.items():
        if arr.shape != x.shape:
            raise ValueError(f"{'series ' + repr(lab) if isinstance(y, Mapping) else 'y'} has shape {arr.shape} "
                             f"but x has shape {x.shape}; they must match point by point")
    c_arr = None
    if color is not None:
        if kind != "scatter":
            raise TypeError("color is for scatter plots (kind='scatter')")
        c_arr = _numeric(color, "color")
        if c_arr.shape != x.shape:
            raise ValueError(f"color has shape {c_arr.shape} but x has shape {x.shape}")

    pairwise = x.ndim != 1 or (kind == "scatter" and x.size > 1 and not np.all(np.diff(x) >= 0))
    if pairwise:
        if kind == "curve":
            raise ValueError(f"for curves x must be 1-D, got shape {x.shape}; use kind='scatter' to plot points pairwise")
        # x isn't a sorted 1-D coordinate (e.g. I/Q data): plot value against value
        d.add_axis("i", np.arange(x.size, dtype=float), label="index")
        d.add_value("x", x.ravel(), axes="i", unit=x_unit, label=x_label)
        axes = "i"
    else:
        d.add_axis("x", x, unit=x_unit, label=x_label)
        axes = "x"
    names = []
    for k, (lab, arr) in enumerate(arrays.items(), start=1):
        name = f"y{k}"
        d.add_value(name, arr.ravel() if pairwise else arr, axes=axes, unit=y_unit, label=lab)
        names.append(name)
    plot_spec: Dict[str, Any] = dict(spec)
    if c_arr is not None:
        d.add_value("c", c_arr.ravel() if pairwise else c_arr, axes=axes, unit=color_unit, label=color_label)
        plot_spec["color"] = "c"
    if kind == "scatter":
        plot_spec["x"] = "x"
    if len(names) > 1:
        plot_spec["y_label"] = y_label
    return plot(d, kind, names, style=style, ax=ax, file_style=False, **extra, **plot_spec)


def _numeric(a: Any, what: str) -> np.ndarray:
    arr = np.asarray(a)
    if arr.dtype.kind not in "biufc":
        raise ValueError(f"{what} must be numbers, got {arr.dtype}")
    if arr.size == 0:
        raise ValueError(f"{what} is empty")
    if arr.ndim == 0:
        raise ValueError(f"{what} must be an array, not a single number")
    return arr
