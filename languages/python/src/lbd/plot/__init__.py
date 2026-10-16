"""lbd.plot: make figures that look exactly like LBD Viewer's, from Python.

    import lbd.plot as lp

    with lp.use("thesis"):              # your own matplotlib code, same size/fonts/colours as the tool
        fig, ax = plt.subplots()
        ...
    fig = lp.plot(dataset_or_path, kind="heatmap", values="S21", complex="db", style="thesis")

Needs the plotting extra:  pip install "lbd[plot]"
Guide: docs/python/plotting.md (and Help in LBD Viewer)
"""

from __future__ import annotations

try:
    import matplotlib  # noqa: F401
    import platformdirs  # noqa: F401
    import pydantic  # noqa: F401
except ImportError as e:  # pragma: no cover - depends on the environment
    raise ImportError(
        'lbd.plot needs matplotlib, pydantic and platformdirs. Install them with:  pip install "lbd[plot]"'
    ) from e

from .api import (
    activate,
    apply,
    axis_label,
    default_style,
    list_styles,
    load_style,
    plot,
    prefix,
    quick,
    save,
    subplots,
    use,
)
from .presets import BUILTIN_PRESETS, PresetStore, config_dir
from .render import COMPLEX_MODES, KINDS, RenderError, RenderWarning
from .style import STYLE_SUFFIX, Style, StyleError, StyleWarning
from .units import PREFIXES, UnitWarning

__all__ = [
    "activate", "apply", "axis_label", "default_style", "list_styles", "load_style", "plot", "prefix",
    "quick", "save", "subplots", "use",
    "BUILTIN_PRESETS", "PresetStore", "config_dir", "COMPLEX_MODES", "KINDS", "PREFIXES",
    "RenderError", "RenderWarning", "STYLE_SUFFIX", "Style", "StyleError", "StyleWarning", "UnitWarning",
]
