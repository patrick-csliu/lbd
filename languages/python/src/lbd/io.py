"""Read and write LBD (.lbd) files. See spec/LBD-v1.md.

Invalid input raises `LBDError` (or `TypeError` for arguments of the wrong type); input that is
stored but changed or partly ignored (e.g. long double stored as float64) gives an `LBDWarning`.
Nothing is dropped or altered without one of the two.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import json
import os
import re
import sys
import time
import uuid as _uuid
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Union

import h5py
import numpy as np

__version__ = "1.3.0.dev0"
FORMAT_VERSION = "2.0"         # the newest format this module reads and writes
_GRID_VERSION = "1.2"          # what a file without an axis group is written as (spec §6)
_FORMAT_MAJOR = int(FORMAT_VERSION.split(".")[0])
_LATEST_MINOR = {1: 2, 2: 0}   # the newest minor version known, per major version

_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")
_STR_DTYPE = h5py.string_dtype("utf-8")
_ALLOWED_DTYPES = (
    "float32", "float64",
    "int8", "int16", "int32", "int64",
    "uint8", "uint16", "uint32", "uint64",
    "complex64", "complex128",
    "bool",
)
# Arrays smaller than this are never compressed; chunking overhead isn't worth it.
_COMPRESS_MIN_SIZE = 1024
# The keys a saved plot spec may have (see the "Plot settings" documentation page).
PLOT_SPEC_KEYS = frozenset({"kind", "values", "complex", "x", "y", "series", "color", "index", "x_scale",
                            "y_scale", "title", "x_label", "y_label", "z_label", "annotations"})
_INT64 = np.iinfo(np.int64)

PathLike = Union[str, "os.PathLike[str]"]
_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))


class LBDError(ValueError):
    """The file is not a valid LBD file, or the data can't be stored in one.

    Raised for invalid names, shapes or types, files that aren't LBD files or break the format
    rules, and metadata that can't be stored. Catch `LBDError` to handle `LBDVersionError` too.
    It is a `ValueError`, so `except ValueError` catches it as well.
    """


class LBDVersionError(LBDError):
    """The file was written with a newer, incompatible major format version.

    Update `lbd` to read it. (A newer *minor* version is read, with a warning.)
    """


class LBDWarning(UserWarning):
    """Something was stored or read, but not exactly as given.

    Examples: a long-double array stored as float64, a file written by a newer minor format
    version, a saved view that isn't valid JSON. Every warning of LBD (also those of `lbd.plot`)
    is an `LBDWarning`, so one filter silences them all:

    >>> import warnings
    >>> warnings.simplefilter("ignore", lbd.LBDWarning)
    """


def _warn(message: str, category: type = LBDWarning) -> None:
    """Warn, attributing the warning to the first caller outside the lbd package."""
    level, frame = 2, sys._getframe(1)   # stacklevel 2 = the caller of _warn
    while frame is not None and os.path.abspath(frame.f_code.co_filename).startswith(_PACKAGE_DIR):
        frame = frame.f_back
        level += 1
    warnings.warn(message, category, stacklevel=level)


def version() -> Dict[str, str]:
    """Package version and the LBD format version it reads and writes.

    Use it to check which `lbd` is installed, e.g. in a bug report, or to compare with the
    version LBD Viewer shows.

    Returns
    -------
    dict
        `{"package": "1.0.0", "lbd_version": "1.0"}`: the version of this module and the newest
        file format it reads and writes (a file is written with the lowest version its content
        needs).

    Examples
    --------
    >>> lbd.version()["lbd_version"]
    '1.0'
    """
    return {"package": __version__, "lbd_version": FORMAT_VERSION}


@dataclass
class Axis:
    """A 1-D axis of a dataset: coordinates with a unit and a label.

    Created by [`Dataset.add_axis`][lbd.Dataset.add_axis]; `len(axis)` is the number of points.
    You normally read axes (`d.axes["freq"].data`) rather than create them directly; an `Axis`
    changed by hand is checked again when the dataset is saved.

    Attributes
    ----------
    name : str
        Axis name, e.g. `"freq"`.
    data : numpy.ndarray
        1-D coordinates (integer or floating point).
    unit : str
        Unit, `""` for dimensionless. Prefer base units (`"Hz"`, not `"GHz"`).
    label : str
        Display text used on plot axes, e.g. `"Frequency"`.
    elements : list of str or None
        A text for each position, in order (format 1.2): `["ground", "excited"]` for an axis
        swept over named states. `None`: the positions are known by their numbers.
    role : str or None
        `"point"` for an axis made by [`Dataset.add_value`][lbd.Dataset.add_value] for a
        dimension inside a value's data point (format 1.2); `None` for a sweep axis.
    grows : bool
        An axis of unknown length (`add_axis(..., grows=True)`): [`write`][lbd.Dataset.write]
        adds its points. Not stored in the file (a saved file has the points written).
    """

    name: str
    data: np.ndarray
    unit: str = ""
    label: str = ""
    elements: Optional[List[str]] = None
    role: Optional[str] = None
    grows: bool = False

    def __len__(self) -> int:
        return len(self.data)


@dataclass
class Value:
    """An N-D value of a dataset, with one axis per dimension.

    Created by [`Dataset.add_value`][lbd.Dataset.add_value] or read from a file.

    Attributes
    ----------
    name : str
        Value name, e.g. `"S21"`.
    data : numpy.ndarray or None
        The array: 0-D for a scalar, `bool` for boolean values. `None` if the file was read
        without this value's data (see [`load`][lbd.load] with `values=`).
    axes : list of str
        The axis name of each dimension, in order.
    unit : str
        Unit, `""` for dimensionless.
    label : str
        Display text, e.g. `"|S21|"`.
    shape : tuple
        Array shape, available even when `data` is `None`.
    dtype : str
        LBD type name, e.g. `"complex128"` or `"bool"`.
    point_axes : list of str
        The axes of one data point (format 1.2), the last of `axes`: empty when each data point
        is one number.
    elements : list
        For each dimension of a data point, the text of each position, or `None` when it is
        known by number (format 1.2; a copy of its point axes' `elements`).
    measured : numpy.ndarray or None
        For an integer or boolean value filled piece by piece (`add_value` without data, then
        `write`): `True` where something was written. `None` for every other value (float and
        complex values use `NaN` for "not measured").
    """

    name: str
    data: Optional[np.ndarray]
    axes: List[str] = field(default_factory=list)
    unit: str = ""
    label: str = ""
    # Shape and dtype are kept even when the data itself was not loaded.
    shape: tuple = ()
    dtype: str = ""
    point_axes: List[str] = field(default_factory=list)
    elements: List[Optional[List[str]]] = field(default_factory=list)
    measured: Optional[np.ndarray] = None

    @property
    def point_shape(self) -> tuple:
        """The shape of one data point: `()` for one number, `(3,)` for a vector of 3 …"""
        return tuple(self.shape[len(self.shape) - len(self.point_axes):]) if self.point_axes else ()


class Dataset:
    """The content of one `.lbd` file: axes, values, metadata and an optional saved view.

    Build one and [`save`][lbd.Dataset.save] it, or get one from [`load`][lbd.load] or
    [`info`][lbd.info]. `d[name]` returns the value (or else the axis) with that name, and
    `name in d` tests whether it exists.

    A measurement is a set of **axes** (what was swept: power, frequency, time) and **values**
    measured on them (S21, a voltage trace). Add the axes first, then the values; every
    dimension of a value is tied to one axis, so plots and other languages know what each
    dimension means.

    Parameters
    ----------
    title : str, optional
        Short title, shown in LBD Viewer.
    description : str, optional
        Free text.

    Attributes
    ----------
    title, description : str
        Editable text.
    axes : dict of str to Axis
        Axes by name. Add with `add_axis`.
    values : dict of str to Value
        Values by name. Add with `add_value`.
    meta : dict
        Free metadata; nested dicts become groups. Allowed: str, int, float, complex, bool
        (stored as 0/1), numeric arrays, lists of str, nested dicts. `None` is refused at save.
    plot : dict or None
        Default view for LBD Viewer and `lbd.plot.plot`: a plot spec such as
        `{"kind": "heatmap", "complex": "db"}`.
    style : dict or None
        Style changes for this file only, e.g. `{"figure": {"width_mm": 120}}`.
    style_name : str or None
        Name of a style preset to use for this file.
    matplotlib : str or None
        The matplotlib version that last wrote the saved view (`plot`, `style`), e.g. `"3.11.2"`.
        Set by `save` and `lbd.set_plot` when matplotlib is installed; only informational (it
        tells which matplotlib the view's annotations were written for).
    created : str, datetime or None
        When the data was created (measured), as ISO-8601 text with a UTC offset, e.g.
        `"2026-10-13T16:09:00+08:00"`. Give it (here or in `Dataset(created=...)`) as a
        `datetime` or such a text; a time without an offset is taken in this computer's time
        zone. Not given: `save` fills in the time of the first save. A loaded file keeps its
        `created`, and saving it again keeps it; only a new value changes it.
    writer : str or None
        The program that wrote the file, e.g. `"python lbd 1.3.0"`. Set by `save`.
    id : str or None
        The measurement's identity, a UUID (version 7) written into the file at its first save,
        e.g. `"0192d4e2-7b3a-7c1e-9f2a-1c2b3d4e5f60"`. Read-only. Saving again to the same file
        keeps it; saving to another file gives the new file a new id (and `parent_id`); a file
        copied by the file system keeps it. LBD Viewer's Library uses it to recognise the same
        measurement in two places. `None` for a new dataset not saved yet, or a file written
        before format 1.1.
    parent_id : str or None
        The id of the file this one was made from (saved to another file, or `new_id`).
    lbd_version : str
        Format version of the file it was read from or last saved to (`"1.2"` for a new
        dataset: files without an axis group are written as 1.2).
    path : pathlib.Path or None
        Where the dataset was last loaded from or saved to.

    Raises
    ------
    TypeError
        `title` or `description` is not a string.
    LBDError
        `created` is not a date and time.

    Examples
    --------
    >>> d = lbd.Dataset(title="Resonator power sweep")
    >>> d.add_axis("power", p, unit="dBm", label="Power")
    >>> d.add_axis("freq", f, unit="Hz", label="Frequency")
    >>> d.add_value("S21", s21, axes=["power", "freq"])       # s21.shape == (len(p), len(f))
    >>> d.meta["T_mK"] = 12
    >>> d.save("sweep.lbd")
    """

    def __init__(self, title: str = "", description: str = "", created: Any = None):
        self.title = _check_text(title, "title")
        self.description = _check_text(description, "description")
        self.created: Optional[str] = None if created is None else _created_text(created)
        self.writer: Optional[str] = None
        self.lbd_version: str = _GRID_VERSION
        self.axes: Dict[str, Axis] = {}
        self.values: Dict[str, Value] = {}
        self.meta: Dict[str, Any] = {}
        self.plot: Optional[Dict[str, Any]] = None
        self.style: Optional[Dict[str, Any]] = None
        self.style_name: Optional[str] = None
        self.matplotlib: Optional[str] = None
        self.path: Optional[Path] = None
        self._id: Optional[str] = None
        self._parent_id: Optional[str] = None
        self._placeholders: Optional[set] = None   # lbd.Writer: names of values whose data is in the file

    @property
    def id(self) -> Optional[str]:
        """The measurement's identity (a UUID version 7), or None before the first save."""
        return self._id

    @property
    def parent_id(self) -> Optional[str]:
        """The id of the file this one was made from, or None."""
        return self._parent_id

    def new_id(self) -> str:
        """Make this a separate measurement: a new id, the old one becomes `parent_id`.

        Saving to another file does this by itself; use it when a dataset loaded from a file is
        meant to become a new measurement saved over that same file. Returns the new id.
        """
        if self._id is not None:
            self._parent_id = self._id
        self._id = new_uuid7()
        return self._id

    # ---- building -------------------------------------------------------

    def add_axis(self, name: str, data: Any = None, unit: str = "", label: Optional[str] = None,
                 elements: Optional[Sequence[str]] = None, grows: bool = False) -> Axis:
        """Add a 1-D axis: the coordinates of one swept quantity.

        Add every axis before the values that use it.

        Parameters
        ----------
        name : str
            Axis name: starts with a letter, then letters, digits and `_` (at most 63), and not
            used by another axis or value.
        data : array_like, optional
            1-D, finite real numbers (integer or float; not bool or complex), at least one.
            Ranges and lists work. `float16` is stored as `float32`. May be left out when
            `elements` is given: the positions are then numbered 0, 1, 2 …
        unit : str, optional
            Unit, `""` for dimensionless. Prefer base units (`"Hz"`, not `"GHz"`): plots then
            choose a readable prefix.
        label : str, optional
            Display text for plot axes. Defaults to `name`.
        elements : list of str, optional
            A text for each position of the axis, in order, e.g. `["ground", "excited"]`: plots,
            cursors and sliders show them instead of the numbers (format 1.2).
        grows : bool, optional
            An axis of unknown length (a log, "until I stop it"): give no `data`;
            [`write`][lbd.Dataset.write] adds its points (`d.write(time=t, T=x)`). It must be the
            first axis of the values on it.

        Returns
        -------
        Axis
            The new axis.

        Raises
        ------
        LBDError
            Invalid or already used name; data not 1-D, empty, not real numeric, or containing
            NaN/inf; a masked array; neither `data` nor `elements`; `elements` of another length
            than the axis.
        TypeError
            `unit` or `label` is not a string; `elements` is not a list of strings.

        Warns
        -----
        LBDWarning
            The coordinates are neither increasing nor decreasing (heat maps of such an axis
            are drawn in the given order, which is rarely what you want), or long double data
            is stored as float64.

        Examples
        --------
        >>> d.add_axis("t", np.linspace(0, 1e-6, 201), unit="s", label="Time")
        >>> d.add_axis("state", elements=["ground", "excited"])        # numbered 0, 1
        >>> d.add_axis("time", unit="s", grows=True)                   # points added by write
        """
        self._check_new_name(name)
        unit = _check_text(unit, "unit")
        label = name if label is None else _check_text(label, "label")
        if grows:
            if data is not None or elements is not None:
                raise LBDError(f"axis '{name}' grows: give no data or elements; write adds its points")
            axis = Axis(name, np.empty(0), unit=unit, label=label, grows=True)
            self.axes[name] = axis
            return axis
        if data is None:
            if elements is None:
                raise LBDError(f"axis '{name}' needs its coordinates (data) or its elements")
            data = np.arange(len(_check_elements(elements, None, f"axis '{name}'")))
        arr = _as_array(data, f"axis '{name}'")
        if arr.ndim != 1:
            raise LBDError(f"axis '{name}' must be 1-D, got shape {arr.shape}")
        if arr.dtype.kind not in "iuf":
            raise LBDError(f"axis '{name}' must be real numeric (integer or float), got dtype {arr.dtype}")
        if arr.size == 0:
            raise LBDError(f"axis '{name}' is empty; an axis needs at least one point")
        if arr.dtype.kind == "f" and not np.all(np.isfinite(arr)):
            raise LBDError(f"axis '{name}' contains NaN or inf; axis coordinates must be finite")
        if arr.size > 2:
            steps = np.diff(arr.astype(float))
            if not (np.all(steps > 0) or np.all(steps < 0)):
                _warn(f"axis '{name}' is not strictly increasing or decreasing; plots draw its points "
                      "in the given order")
        arr = _normalize_dtype(arr, f"axis '{name}'")
        if elements is not None:
            elements = _check_elements(elements, arr.size, f"axis '{name}'")
        axis = Axis(name, arr, unit=unit, label=label, elements=elements)
        self.axes[name] = axis
        return axis

    def add_value(
        self,
        name: str,
        data: Any = None,
        axes: Union[str, Sequence[str], None] = None,
        unit: str = "",
        label: Optional[str] = None,
        dtype: str = "auto",
        shape: Optional[Sequence[int]] = None,
        elements: Optional[Sequence[Any]] = None,
    ) -> Value:
        """Add an N-D value whose dimensions are tied to existing axes.

        Each data point is one number, unless `shape` says otherwise: then `data`'s dimensions
        are the value's axes first, then the data point's (format 1.2).

        Parameters
        ----------
        name : str
            Value name (same rules as axis names).
        data : array_like, optional
            Numbers or booleans. A plain number makes a scalar value (no axes). Left out: the
            value is filled later by [`write`][lbd.Dataset.write] — every point starts as `NaN`
            (not measured yet), or for integers and booleans as 0 with `measured` False.
        axes : str or sequence of str, optional
            One axis name per dimension of `data` (before the data point's dimensions), in
            order: a list (`["power", "freq"]`), one name (`"freq"`), a comma-separated string
            (`"power,freq"`), or `None` for a scalar. The axes must already exist, each may
            appear once, and each dimension's size must equal its axis length.
        unit : str, optional
            Unit, `""` for dimensionless.
        label : str, optional
            Display text. Defaults to `name`.
        dtype : str, optional
            `"auto"` (default) keeps the type of `data`. Or store as one of `float32`,
            `float64`, `int8`…`int64`, `uint8`…`uint64`, `complex64`, `complex128`, `bool`.
            The conversion must not lose information: floats stored as integers must be whole
            numbers in range, integers must fit the smaller type, `bool` needs 0/1 data, and
            complex data needs a complex type.
        shape : tuple of int, optional
            The shape of one data point, like numpy: `(3,)` for a vector of 3, `(2, 2)` for a
            matrix. Default `()`: one number. `data`'s last dimensions must have this shape.
            For each dimension of the data point an axis is made, named `<name>_dim1`,
            `<name>_dim2` … (positions 0, 1, 2 …).
        elements : list, optional
            The text of each position in a data point: one list for a vector
            (`["u", "v", "w"]`), one list per dimension for more (`[["I", "Q"], ["I", "Q"]]`;
            `None` leaves a dimension numbered).

        Returns
        -------
        Value
            The new value.

        Raises
        ------
        LBDError
            Invalid or used name; number of axes and `shape` don't match `data.ndim`; unknown or
            repeated axis; a dimension's size differs from its axis length; the data point's
            shape differs from `shape`; `elements` of the wrong length; a data point axis name
            already used; non-numeric or masked data; unknown `dtype`; or a conversion to
            `dtype` that would change the numbers.
        TypeError
            `axes`, `unit`, `label` or `dtype` has the wrong type (e.g. a dict for `axes`).

        Warns
        -----
        LBDWarning
            Long double data stored as float64 / complex128.

        Examples
        --------
        >>> d.add_value("S21", s21, axes=["power", "freq"])
        >>> d.add_value("trace", v, axes="t", unit="V")
        >>> d.add_value("mask", v > 0.5, axes="t")                 # stored as bool
        >>> d.add_value("raw", counts, axes="t", dtype="float32")  # force a type
        >>> d.add_value("fit_Q", 12345.6)                          # scalar, no axes
        >>> d.add_value("bloch", b, axes="amp", shape=(3,), elements=["x", "y", "z"])   # (n_amp, 3)
        """
        self._check_new_name(name)
        unit = _check_text(unit, "unit")
        label = name if label is None else _check_text(label, "label")
        if not isinstance(dtype, str):
            raise TypeError(f"dtype must be a string such as 'float32' or 'auto', not {type(dtype).__name__}")
        axes_list = _axes_argument(axes)
        point = _check_shape(shape, name)
        measured = None
        placeholder = None
        if data is None:                      # filled later by write: "not measured yet"
            for ax in axes_list:
                if ax not in self.axes:
                    raise LBDError(f"value '{name}': axis '{ax}' does not exist; add it with add_axis first")
            kind = "float64" if dtype == "auto" else dtype
            if kind not in _ALLOWED_DTYPES:
                raise LBDError(f"value '{name}': unknown dtype {dtype!r}; use one of {', '.join(_ALLOWED_DTYPES)}")
            full = tuple(len(self.axes[a]) for a in axes_list) + point
            fill = np.nan if kind.startswith(("float", "complex")) else 0
            if kind not in ("float32", "float64", "complex64", "complex128"):
                measured = np.zeros(full, dtype=bool)
            if self._placeholders is not None:   # lbd.Writer: the data lives in the file
                placeholder = np.broadcast_to(np.array(fill, dtype=kind), full)
                measured = None if measured is None else np.broadcast_to(np.False_, full)
            else:
                data = np.full(full, fill, dtype=kind)
            dtype = "auto"
        arr = placeholder if placeholder is not None else _coerce_value(data, dtype, name)
        if len(axes_list) + len(point) != arr.ndim:
            if len(axes_list) < arr.ndim and not point:
                raise LBDError(
                    f"value '{name}' has {arr.ndim} dimension(s) but {len(axes_list)} axes were given: "
                    f"{axes_list}; if each data point holds several numbers, say so with "
                    f"shape={tuple(arr.shape[len(axes_list):])}")
            raise LBDError(
                f"value '{name}' has {arr.ndim} dimension(s) {tuple(arr.shape)}, but its axes {axes_list} "
                f"and shape={point} make {len(axes_list) + len(point)}")
        if len(set(axes_list)) != len(axes_list):
            raise LBDError(f"value '{name}': an axis appears more than once in {axes_list}")
        growing = [a for a in axes_list if a in self.axes and self.axes[a].grows]
        if growing and axes_list[0] != growing[0] or len(growing) > 1:
            raise LBDError(f"value '{name}': a growing axis must be its first axis, and only one "
                           f"(here {axes_list}, growing {growing})")
        for i, ax in enumerate(axes_list):
            if ax not in self.axes:
                raise LBDError(f"value '{name}': axis '{ax}' does not exist; add it with add_axis first")
            if len(self.axes[ax]) != arr.shape[i]:
                hint = (f"; the value's axes come first, then the data point (e.g. use `.T`)"
                        if point and arr.shape[-len(point):] != point else "")
                raise LBDError(
                    f"value '{name}': dimension {i} has size {arr.shape[i]} "
                    f"but axis '{ax}' has length {len(self.axes[ax])}{hint}"
                )
        if point and tuple(arr.shape[len(axes_list):]) != point:
            raise LBDError(f"value '{name}': its data points have shape {tuple(arr.shape[len(axes_list):])}, "
                           f"not shape={point}")
        named = _value_elements(elements, point, name)
        point_names = [f"{name}_dim{k + 1}" for k in range(len(point))]
        for p in point_names:
            if p in self.axes or p in self.values:
                raise LBDError(f"value '{name}' needs the name '{p}' for an axis of its data points, but it "
                               "is already used; rename that axis or value")
        for p, n, el in zip(point_names, point, named):
            self.axes[p] = Axis(p, np.arange(n), label=f"{label} ({p.rsplit('_', 1)[1]})" if len(point) > 1 else label,
                                elements=el, role="point")
        value = Value(name, arr, axes_list + point_names, unit=unit, label=label, shape=arr.shape,
                      dtype=str(arr.dtype), point_axes=point_names, elements=named, measured=measured)
        self.values[name] = value
        if placeholder is not None:
            self._placeholders.add(name)
        return value

    def write(self, names: Optional[Mapping[str, Any]] = None, **more: Any) -> None:
        """Put measured data into values made by `add_value`: a point, a trace, a whole map, or
        several values at once, at the place the axes say.

        Each name is an axis or a value (as keywords, or in the dict `names` for a name that
        can't be a keyword, e.g. `d.write({"if": 3}, S21=z)`):

        - a **fixed axis**: an index (`power=3`), or one of its elements (`state="excited"`);
        - a **growing axis** (`add_axis(..., grows=True)`): its coordinate (`time=12.5`), or an
          array of them, adding as many points;
        - a **value**: its data, shaped as the value's axes that weren't given (and its data
          point), in order: a point is one number, a trace at `power=3` of `S21[power, freq]`
          is one number per frequency.

        Writing again to the same place replaces the data there.

        Raises
        ------
        LBDError
            An unknown name; no value given; a position out of range or an unknown element; a
            position for an axis a value doesn't lie on; a growing axis without its coordinate;
            data of another shape than the place needs (the message says which); complex data for
            a real value, or numbers an integer or boolean value can't hold exactly.

        Examples
        --------
        >>> d.write(power=i, S21=trace)                    # a trace
        >>> d.write(power=i, freq=j, S21=z, T=t)           # a point, and T at power i
        >>> d.write(time=12.5, T=4.2)                      # a row of a growing axis
        """
        plan = self._plan_write(names, more)
        self._apply_write(plan)

    def _plan_write(self, names: Optional[Mapping[str, Any]], more: Mapping[str, Any]) -> Dict[str, Any]:
        """Check a write against the dataset's shapes; returns what to put where (data not
        needed: `lbd.Writer` uses the same plan)."""
        given: Dict[str, Any] = {}
        if names is not None:
            if not isinstance(names, Mapping):
                raise TypeError(f"write: the first argument must be a dict of names, not {type(names).__name__}")
            given.update(names)
        for k, v in more.items():
            if k in given:
                raise LBDError(f"write: '{k}' is given twice")
            given[k] = v
        unknown = [k for k in given if k not in self.axes and k not in self.values]
        if unknown:
            raise LBDError(f"write: no axis or value named {unknown}; axes: {list(self.axes)}, values: {list(self.values)}")
        values = {k: v for k, v in given.items() if k in self.values}
        if not values:
            raise LBDError("write: give at least one value with its data, e.g. write(power=3, S21=trace)")
        positions = {k: v for k, v in given.items() if k in self.axes}
        growing = [a for a in positions if self.axes[a].grows]
        if len(growing) > 1:
            raise LBDError(f"write: one growing axis at a time, not {growing}")
        grow = None
        if growing:
            g = growing[0]
            coords = np.asarray(positions[g], dtype=float)
            if coords.ndim > 1 or not np.all(np.isfinite(coords)):
                raise LBDError(f"write: '{g}' takes a coordinate or a 1-D array of them, finite numbers")
            grow = (g, coords)
        index_of: Dict[str, int] = {}
        for a, x in positions.items():
            if self.axes[a].grows:
                continue
            index_of[a] = self._position(a, x)
        puts = []
        for name, data in values.items():
            v = self.values[name]
            for a in positions:
                if a not in v.axes:
                    raise LBDError(f"write: '{name}' doesn't lie on '{a}' (its axes: {v.axes})")
            index, shape = [], []
            for a in v.axes:
                ax = self.axes[a]
                if ax.grows:
                    if grow is None or grow[0] != a:
                        raise LBDError(f"write: '{name}' lies on the growing axis '{a}': give its coordinate "
                                       f"({a}=…), which adds a point")
                    start, n = len(ax.data), grow[1].size
                    if grow[1].ndim == 0:
                        index.append(start)
                    else:
                        index.append(slice(start, start + n))
                        shape.append(n)
                elif a in index_of:
                    index.append(index_of[a])
                else:
                    index.append(slice(None))
                    shape.append(len(ax.data))
            arr = np.asarray(data)
            if arr.shape != tuple(shape) and not (arr.size == 1 and shape == []):
                given_axes = [a for a in v.axes if a in positions]
                raise LBDError(f"write: '{name}' at {given_axes or 'every place'} needs data of shape {tuple(shape)} "
                               f"({', '.join(a for a in v.axes if a not in index_of and not self.axes[a].grows) or 'one number'}), "
                               f"not {arr.shape}")
            puts.append((name, tuple(index), _check_fits(arr.reshape(shape) if arr.size == 1 and shape == [] else arr,
                                                         v.dtype, name)))
        return {"grow": grow, "puts": puts}

    def _position(self, axis: str, x: Any) -> int:
        """An index of a fixed axis, from an index or one of its elements."""
        ax = self.axes[axis]
        n = len(ax.data)
        if isinstance(x, str):
            if ax.elements is None or x not in ax.elements:
                raise LBDError(f"write: '{axis}' has no element {x!r}"
                               + (f"; its elements: {ax.elements}" if ax.elements else "; give an index"))
            return ax.elements.index(x)
        if isinstance(x, (bool, np.bool_)) or not isinstance(x, (int, np.integer)):
            raise LBDError(f"write: '{axis}' takes one position: an index (0 … {n - 1})"
                           + (" or one of its elements" if ax.elements else "") + f", not {x!r}")
        if not -n <= int(x) < n:
            raise LBDError(f"write: index {int(x)} is out of range for '{axis}' (it has {n} points: 0 … {n - 1})")
        return int(x) % n

    def _apply_write(self, plan: Dict[str, Any]) -> None:
        if plan["grow"] is not None:
            g, coords = plan["grow"]
            n = max(coords.size, 1)
            ax = self.axes[g]
            ax.data = np.concatenate([ax.data, np.atleast_1d(coords)]) if ax.data.size else np.atleast_1d(coords).copy()
            for v in self.values.values():
                if v.axes and v.axes[0] == g:
                    if v.data is None:
                        raise LBDError(f"write: value '{v.name}' was not loaded")
                    pad = np.full((n,) + v.data.shape[1:], np.nan, dtype=v.data.dtype) \
                        if v.data.dtype.kind in "fc" else np.zeros((n,) + v.data.shape[1:], dtype=v.data.dtype)
                    if v.data.dtype.kind not in "fc" and v.measured is None:
                        v.measured = np.ones(v.data.shape, dtype=bool)
                    v.data = np.concatenate([v.data, pad])
                    if v.measured is not None:
                        v.measured = np.concatenate([v.measured, np.zeros((n,) + v.measured.shape[1:], dtype=bool)])
                    v.shape = v.data.shape
        for name, index, arr in plan["puts"]:
            v = self.values[name]
            if v.data is None:
                raise LBDError(f"write: value '{name}' was not loaded; load the file without `values=`")
            v.data[index] = arr
            if v.measured is not None:
                v.measured[index] = True

    def _check_new_name(self, name: str) -> None:
        _check_name(name)
        if name in self.axes or name in self.values:
            raise LBDError(f"name '{name}' is already used by an axis or value")

    # ---- access ---------------------------------------------------------

    def __getitem__(self, name: str) -> Union[Axis, Value]:
        if name in self.values:
            return self.values[name]
        if name in self.axes:
            return self.axes[name]
        raise KeyError(f"no axis or value named {name!r}; values: {list(self.values)}, axes: {list(self.axes)}")

    def __contains__(self, name: object) -> bool:
        return name in self.values or name in self.axes

    def __repr__(self) -> str:
        lines = [f"<lbd.Dataset {self.title!r}>"]
        for a in self.axes.values():
            lines.append(f"  axis  {a.name}[{len(a)}] {a.unit}".rstrip())
        for v in self.values.values():
            dims = ",".join(v.axes)
            lines.append(f"  value {v.name}({dims}) {v.dtype} {v.unit}".rstrip())
        return "\n".join(lines)

    # ---- saving ---------------------------------------------------------

    def save(self, path: PathLike, compression: Optional[str] = None) -> Path:
        """Write the dataset to an `.lbd` file.

        Everything is checked again first, also axes, values and attributes changed by hand
        after `add_axis` / `add_value`. The file is written under a temporary name
        (`<name>.lbd.tmp-<pid>`) and then renamed, so LBD Viewer or another program never sees a
        half-written file. If writing fails, the temporary file is removed and an existing file
        at `path` is left untouched. Sets `writer` and `path`, and `created` if it wasn't set
        (the time of this first save); a `created` that is set, also one read by `load`, is
        written unchanged. Gives the dataset its `id` at the first save; saving to another
        file than the one it was loaded from or last saved to gives a new `id`, the old one
        becoming `parent_id` (the new file is a new measurement made from that one).

        Parameters
        ----------
        path : str or path-like
            File to write. Use the `.lbd` extension (other extensions give a warning). An
            existing file is replaced.
        compression : {None, "gzip"}, optional
            `"gzip"` compresses arrays of 1024 elements or more (lossless, level 4). All readers
            decompress transparently.

        Returns
        -------
        pathlib.Path
            The path written.

        Raises
        ------
        LBDError
            Anything that breaks the format: metadata that can't be stored (e.g. `None`), a value
            read without its data, a value whose shape no longer matches its axes, a `plot` with
            unknown keys or NaN, a `style` that isn't a dict, an invalid `compression`, a
            `created` that isn't a date and time.
        OSError
            File-system problems. On Windows, a file another program keeps open (e.g. LBD Viewer
            reading it, a sync client) can't be replaced: `save` waits up to 3 s for it, then
            raises `PermissionError` naming the file.

        Warns
        -----
        LBDWarning
            The extension isn't `.lbd`.

        Examples
        --------
        >>> d.save("sweep.lbd")
        >>> d.save("big.lbd", compression="gzip")
        """
        path = Path(path)
        if path.name.lower().endswith(WRITING_SUFFIX):
            raise LBDError(f"{path.name}: a '{WRITING_SUFFIX}' file is written only by lbd.Writer; "
                           "save to the .lbd name")
        if path.suffix.lower() != ".lbd":
            _warn(f"{path.name}: LBD files should use the .lbd extension")
        if compression not in (None, "gzip"):
            raise LBDError(f"compression must be None or 'gzip', not {compression!r}")
        self._check_complete()
        plot_json = None if self.plot is None else _plot_json(self.plot, "plot")
        style_json = None if self.style is None else _style_json(self.style, "style")
        style_name = None if self.style_name is None else _check_style_name(self.style_name)
        mpl = None
        if plot_json is not None or style_json is not None or style_name is not None:
            mpl = _matplotlib_version() or self.matplotlib

        created = _created_text(self.created) if self.created is not None else \
            _dt.datetime.now().astimezone().isoformat(timespec="seconds")
        writer = f"python lbd {__version__}"
        ident, parent = self._id, self._parent_id
        if ident is None:
            ident = new_uuid7()
        elif self.path is not None and not _same_target(self.path, path):
            ident, parent = new_uuid7(), ident        # another file: a new measurement made from this one
        tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
        try:
            with h5py.File(tmp, "w") as f:
                self._write(f, compression, created, writer, plot_json, style_json, style_name, mpl)
                f.attrs["id"] = ident
                if parent is not None:
                    f.attrs["parent_id"] = parent
            _replace(tmp, path)
        finally:
            if tmp.exists():
                tmp.unlink()
        self.created, self.writer, self.path = created, writer, path
        self._id, self._parent_id = ident, parent
        return path

    def _check_complete(self, live: bool = False) -> None:
        """Check the whole dataset before writing, including parts changed by hand (`live`: for
        lbd.Writer, whose growing axes start empty)."""
        _check_text(self.title, "title")
        _check_text(self.description, "description")
        for key, a in self.axes.items():
            if not isinstance(a, Axis):
                raise LBDError(f"axes['{key}'] is a {type(a).__name__}, not an lbd.Axis")
            if a.name != key:
                raise LBDError(f"axes['{key}'] is named '{a.name}'; the key and the name must match")
            _check_name(a.name)
            _check_text(a.unit, f"axis '{key}' unit")
            _check_text(a.label, f"axis '{key}' label")
            arr = np.asarray(a.data)
            if a.grows and arr.size == 0:
                if live:
                    continue
                raise LBDError(f"the growing axis '{key}' has no points yet; write some before saving")
            if arr.ndim != 1 or arr.size == 0 or arr.dtype.kind not in "iuf":
                raise LBDError(f"axis '{key}' must hold 1-D, non-empty real numbers; got {arr.dtype} {arr.shape}")
            if arr.dtype.kind == "f" and not np.all(np.isfinite(arr)):
                raise LBDError(f"axis '{key}' contains NaN or inf")
            if a.elements is not None:
                _check_elements(a.elements, arr.size, f"axis '{key}'")
            if a.role not in (None, "point"):
                raise LBDError(f"axis '{key}' has role {a.role!r}; it must be None (a sweep axis) or 'point'")
        for key, v in self.values.items():
            if not isinstance(v, Value):
                raise LBDError(f"values['{key}'] is a {type(v).__name__}, not an lbd.Value")
            if v.name != key:
                raise LBDError(f"values['{key}'] is named '{v.name}'; the key and the name must match")
            _check_name(v.name)
            if key in self.axes:
                raise LBDError(f"'{key}' is used by an axis and a value")
            _check_text(v.unit, f"value '{key}' unit")
            _check_text(v.label, f"value '{key}' label")
            if v.data is None:
                raise LBDError(f"value '{key}' was not loaded; load the file without `values=` to re-save it")
            arr = np.asarray(v.data)
            if arr.dtype.kind not in "biufc" or                     str(_normalize_dtype(np.empty(0, arr.dtype), key, quiet=True).dtype) not in _ALLOWED_DTYPES:
                raise LBDError(f"value '{key}' has unsupported dtype {arr.dtype}")
            if len(v.axes) != arr.ndim or len(set(v.axes)) != len(v.axes):
                raise LBDError(f"value '{key}' has {arr.ndim} dimension(s) but axes={v.axes}")
            for i, ax in enumerate(v.axes):
                if ax not in self.axes:
                    raise LBDError(f"value '{key}' refers to missing axis '{ax}'")
                if len(self.axes[ax]) != arr.shape[i]:
                    raise LBDError(f"value '{key}': dimension {i} has size {arr.shape[i]} "
                                   f"but axis '{ax}' has length {len(self.axes[ax])}")
            if v.measured is not None and np.shape(v.measured) != arr.shape:
                raise LBDError(f"value '{key}': its measured mask has shape {np.shape(v.measured)}, not {arr.shape}")
        if not isinstance(self.meta, Mapping):
            raise LBDError(f"meta must be a dict, not {type(self.meta).__name__}")

    def _write(self, f: h5py.File, compression: Optional[str], created: str, writer: str,
               plot_json: Optional[str], style_json: Optional[str], style_name: Optional[str],
               mpl: Optional[str] = None) -> None:
        f.attrs["lbd_format"] = "LBD"
        self.lbd_version = _version_needed(self)
        f.attrs["lbd_version"] = self.lbd_version
        f.attrs["title"] = self.title
        f.attrs["description"] = self.description
        f.attrs["created"] = created
        f.attrs["writer"] = writer

        g_axes = f.create_group("axes")
        for a in self.axes.values():
            ds = _create_dataset(g_axes, a.name, _normalize_dtype(np.asarray(a.data), a.name), compression)
            ds.attrs["unit"] = a.unit
            ds.attrs["label"] = a.label
            if a.elements is not None:
                ds.attrs.create("elements", np.array(a.elements, dtype=object), dtype=_STR_DTYPE)
            if a.role is not None:
                ds.attrs["role"] = a.role

        g_values = f.create_group("values")
        for v in self.values.values():
            data = _normalize_dtype(np.asarray(v.data), v.name)
            is_bool = data.dtype == np.bool_
            if is_bool:
                data = data.astype(np.uint8)
            ds = _create_dataset(g_values, v.name, data, compression)
            ds.attrs["unit"] = v.unit
            ds.attrs["label"] = v.label
            ds.attrs["axes"] = ",".join(v.axes)
            if is_bool:
                ds.attrs["lbd_bool"] = np.int64(1)

        masks = {v.name: v.measured for v in self.values.values()
                 if v.measured is not None and not np.all(v.measured)}
        if masks:                             # integer / boolean points never measured (stopped early)
            g_measured = f.create_group("measured")
            for name, m in masks.items():
                _create_dataset(g_measured, name, np.asarray(m, dtype=np.uint8), compression)

        _write_meta(f.create_group("meta"), self.meta, "meta")

        if plot_json is not None or style_json is not None or style_name is not None:
            g_plot = f.create_group("plot")
            if plot_json is not None:
                g_plot.attrs["spec"] = plot_json
            if style_json is not None:
                g_plot.attrs["style"] = style_json
            if style_name is not None:
                g_plot.attrs["style_name"] = style_name
            if mpl:
                g_plot.attrs["matplotlib"] = mpl


WRITING_SUFFIX = ".writing"   # name.lbd.writing: being written by lbd.Writer (spec §7)
REPLACE_WAIT = 3.0   # seconds `save` waits for a file another program has open (Windows)


def _replace(tmp: Path, path: Path) -> None:
    """Put the finished temporary file in place of `path`. On Windows this fails while another
    program has `path` open, even for a moment (LBD Viewer reading the new version, a sync
    client, an antivirus scan), so it tries again for up to REPLACE_WAIT seconds."""
    deadline = time.monotonic() + REPLACE_WAIT
    while True:
        try:
            os.replace(tmp, path)
            return
        except PermissionError as e:
            if time.monotonic() > deadline:
                raise PermissionError(
                    f"can't write {path}: another program kept it open for {REPLACE_WAIT:g} s "
                    "(e.g. LBD Viewer or a sync client). Close it there and save again.") from e
            time.sleep(0.05)


def _matplotlib_version() -> Optional[str]:
    """The installed matplotlib's version, without importing it; None if it isn't installed."""
    from importlib import metadata

    try:
        return metadata.version("matplotlib")
    except metadata.PackageNotFoundError:
        return None


# ---- loading ---------------------------------------------------------------


def load(path: PathLike, values: Union[None, str, Iterable[str]] = None) -> Dataset:
    """Read an `.lbd` file.

    Parameters
    ----------
    path : str or path-like
        File to read.
    values : str or iterable of str, optional
        Name(s) of the values whose data to read. `None` (default) reads all. Values not listed
        are still described (`shape`, `dtype`, `axes`, `unit`, `label`) but their `data` is
        `None`. Axes and metadata are always read. Use it for big files when you need only a
        few values.

    Returns
    -------
    Dataset
        The file's content.

    Raises
    ------
    LBDError
        Not an LBD (or not an HDF5) file, or its content breaks the format rules (e.g. a value
        refers to a missing axis).
    LBDVersionError
        The file's major format version is newer than this module supports.
    KeyError
        `values` names a value that doesn't exist.
    FileNotFoundError, OSError
        The file doesn't exist or can't be read.

    Warns
    -----
    LBDWarning
        The file's minor format version is newer; its saved view isn't a valid JSON object; it
        has metadata LBD can't read (datasets in `/meta`, text that isn't UTF-8).

    Examples
    --------
    >>> d = lbd.load("sweep.lbd")
    >>> d["S21"].data.shape
    (11, 401)
    >>> d = lbd.load("big.lbd", values="S21")   # read only S21's data
    """
    path = Path(path)
    if values is None:
        wanted = None
    elif isinstance(values, str):
        wanted = {values}
    else:
        try:
            wanted = set(values)
        except TypeError:
            raise TypeError(f"values must be a name or a list of names, not {type(values).__name__}") from None
        bad = [v for v in wanted if not isinstance(v, str)]
        if bad:
            raise TypeError(f"value names must be strings, got {bad!r}")
    writing = path.name.lower().endswith(WRITING_SUFFIX)
    if writing:
        _warn(f"{path.name} is still being written, or its writer stopped before finishing "
              "(lbd.writing_status tells which); reading what was written so far")
    with _reading(path, writing) as f:
        d = _read_header(f, path)
        for group in ("axes", "values"):
            if not isinstance(f.get(group), h5py.Group):
                raise LBDError(f"{path.name} has no /{group} group; it breaks the LBD format")
        for name, ds in f["axes"].items():
            d.axes[name] = _read_axis(name, ds, path)
        described = {name: _describe_value(name, ds, path) for name, ds in f["values"].items()}
        if writing:                     # a growing axis and its values may be caught mid-write
            _same_lengths(d.axes, described)
        masks = f["measured"] if isinstance(f.get("measured"), h5py.Group) else None
        for name, ds in f["values"].items():
            v = described[name]
            part = tuple(slice(0, n) for n in v.shape)
            if wanted is None or name in wanted:
                v.data = _read_value_data(ds, v, path, part)
                if masks is not None and name in masks:
                    m = np.asarray(masks[name][part] if masks[name].ndim == len(part) else masks[name][()]).astype(bool)
                    if m.shape == tuple(v.shape):
                        v.measured = m
                    else:
                        _warn(f"{path.name}: the measured mask of '{name}' has shape {m.shape}, not {tuple(v.shape)}; "
                              "it is ignored")
            d.values[name] = v
        if wanted is not None:
            missing = wanted - set(d.values)
            if missing:
                raise KeyError(f"{path.name}: no value(s) named {sorted(missing)}; it has {list(d.values)}")
    _validate_loaded(d, path)
    return d


def info(path: PathLike) -> Dataset:
    """Read everything except value data: fast, even for very large files.

    The same as `load(path, values=[])`. Use it to list or check many files, or to look at a
    file's axes, shapes and metadata before deciding what to read.

    Parameters
    ----------
    path : str or path-like
        File to read.

    Returns
    -------
    Dataset
        Axes, metadata and saved view; every value's `data` is `None`.

    Raises
    ------
    LBDError, LBDVersionError, OSError
        As for [`load`][lbd.load].

    Examples
    --------
    >>> for p in Path("data").rglob("*.lbd"):
    ...     i = lbd.info(p)
    ...     print(p.name, i.title, {n: v.shape for n, v in i.values.items()})
    """
    return load(path, values=())


_UNSET: Any = object()


def set_plot(path: PathLike, *, spec: Any = _UNSET, style: Any = _UNSET, style_name: Any = _UNSET) -> None:
    """Change only the saved view of an existing file; the data is not touched or rewritten.

    This is what LBD Viewer's *Save this view to the file* uses. Use it to give files a default
    plot from a script (e.g. after a measurement) without loading and re-saving the data. For
    each argument: pass a value to set it, `None` to remove it, or leave it out to keep it.

    Parameters
    ----------
    path : str or path-like
        An existing `.lbd` file.
    spec : dict or None, optional
        The default plot spec, e.g. `{"kind": "heatmap", "values": ["S21"], "complex": "db"}`.
        Only the plot setting keys are allowed (see the plot settings page).
    style : dict or None, optional
        Style changes for this file, e.g. `{"figure": {"width_mm": 120}}`.
    style_name : str or None, optional
        Name of a style preset for this file.

    Raises
    ------
    TypeError
        No argument besides `path` was given.
    LBDError
        Not an LBD file; a spec with unknown keys or NaN; a style that isn't a dict; an empty
        style name.
    LBDVersionError
        The file's major format version is newer than supported.

    Warns
    -----
    LBDWarning
        The file doesn't have the `.lbd` extension.

    Examples
    --------
    >>> lbd.set_plot("sweep.lbd", spec={"kind": "heatmap", "values": ["S21"], "complex": "db"})
    >>> lbd.set_plot("sweep.lbd", style={"quantities": {"S21.db": {"vmin": -30, "vmax": 0}}})
    >>> lbd.set_plot("sweep.lbd", spec=None, style=None, style_name=None)   # remove everything
    """
    if spec is _UNSET and style is _UNSET and style_name is _UNSET:
        raise TypeError("set_plot needs at least one of spec=, style= or style_name=")
    path = Path(path)
    if path.suffix.lower() != ".lbd":
        _warn(f"{path.name}: LBD files should use the .lbd extension")
    changes = {}
    if spec is not _UNSET:
        changes["spec"] = None if spec is None else _plot_json(spec, "spec")
    if style is not _UNSET:
        changes["style"] = None if style is None else _style_json(style, "style")
    if style_name is not _UNSET:
        changes["style_name"] = None if style_name is None else _check_style_name(style_name)
    with _open(path, "r+") as f:
        if _attr_str(f, "lbd_format", "", path) != "LBD":
            raise LBDError(f"{path.name} is not an LBD file (missing lbd_format='LBD')")
        _check_version(_attr_str(f, "lbd_version", "", path), path)
        g = f.require_group("plot")
        for key, text in changes.items():
            if text is None:
                if key in g.attrs:
                    del g.attrs[key]
            else:
                g.attrs[key] = text
        if not any(k in g.attrs for k in ("spec", "style", "style_name")):
            del f["plot"]                      # nothing left (a version alone means nothing)
        else:
            mpl = _matplotlib_version()
            if mpl:
                g.attrs["matplotlib"] = mpl


@contextlib.contextmanager
def _reading(path: Path, writing: bool) -> Iterator[h5py.File]:
    """The open file to read; a file this process is writing is read through its Writer (HDF5
    shares one handle per file within a process)."""
    if writing:
        from .writer import _own_writer

        w = _own_writer(path)
        if w is not None:
            with w._reading() as f:
                if f is not None:
                    yield f
                    return
    with _open(path, "r", swmr=writing) as f:
        yield f


def _open(path: Path, mode: str, swmr: bool = False) -> h5py.File:
    if not path.exists():
        raise FileNotFoundError(f"no such file: {path}")
    if path.is_dir():
        raise LBDError(f"{path} is a folder, not an LBD file")
    try:
        if swmr:                        # a file being written (spec §7): never lock it
            return h5py.File(path, "r", libver="latest", swmr=True, locking=False)
        return h5py.File(path, mode)
    except OSError as e:
        if not h5py.is_hdf5(path):
            raise LBDError(f"{path.name} is not an LBD file (not an HDF5 file)") from None
        raise OSError(f"can't open {path}: {e}") from e


def _read_header(f: h5py.File, path: Path) -> Dataset:
    fmt = _attr_str(f, "lbd_format", "", path)
    if fmt != "LBD":
        raise LBDError(f"{path.name} is not an LBD file (missing lbd_format='LBD')")
    ver = _attr_str(f, "lbd_version", "", path)
    _check_version(ver, path)
    d = Dataset(title=_attr_str(f, "title", "", path), description=_attr_str(f, "description", "", path))
    d.created = _attr_str(f, "created", "", path) or None
    d.writer = _attr_str(f, "writer", "", path) or None
    for attr in ("id", "parent_id"):
        text = _attr_str(f, attr, "", path)
        if text and not _UUID_RE.match(text):
            _warn(f"{path.name}: its {attr} {text!r} is not a UUID; reading it without one")
            text = ""
        setattr(d, "_" + attr, text.lower() or None)
    d.lbd_version = ver
    d.path = path
    if "meta" in f:
        d.meta = _read_meta(f["meta"], path, "/meta")
    else:
        _warn(f"{path.name} has no /meta group (the format requires one); reading it without metadata")
    if "plot" in f:
        g = f["plot"]
        d.plot = _attr_json(g, "spec", path)
        d.style = _attr_json(g, "style", path)
        d.style_name = _attr_str(g, "style_name", "", path) or None
        d.matplotlib = _attr_str(g, "matplotlib", "", path) or None
    return d


def _check_version(ver: str, path: Path) -> None:
    m = re.match(r"^(\d+)\.(\d+)$", ver)
    if not m:
        raise LBDError(f"{path.name}: invalid lbd_version {ver!r} (expected '<major>.<minor>')")
    major, minor = int(m.group(1)), int(m.group(2))
    if major > _FORMAT_MAJOR:
        raise LBDVersionError(
            f"{path.name} uses LBD format {ver}, but this lbd package ({__version__}) only supports "
            f"formats up to {_FORMAT_MAJOR}.x. Please update lbd."
        )
    if major not in _LATEST_MINOR:
        raise LBDError(f"{path.name}: LBD format {ver} doesn't exist (the first version is 1.0)")
    if minor > _LATEST_MINOR[major]:
        _warn(f"{path.name} uses LBD format {ver}, newer than {major}.{_LATEST_MINOR[major]}; some "
              "content may be ignored. Consider updating lbd.")


def _version_needed(d: "Dataset") -> str:
    """The lowest format version that holds `d`'s content (spec §6): 1.2 without an axis group."""
    return _GRID_VERSION


def _read_axis(name: str, ds: Any, path: Path) -> Axis:
    if not isinstance(ds, h5py.Dataset):
        raise LBDError(f"{path.name}: /axes/{name} is not a dataset")
    _check_loaded_name(name, path)
    data = np.asarray(ds[()])
    if data.ndim != 1 or data.dtype.kind not in "iuf":
        raise LBDError(f"{path.name}: axis '{name}' must be 1-D real numbers, got {data.dtype} {data.shape}")
    axis = Axis(name, data, unit=_attr_str(ds, "unit", "", path), label=_attr_str(ds, "label", name, path))
    if "elements" in ds.attrs:
        raw = _attr_to_python(ds.attrs["elements"], path)
        if isinstance(raw, str):                       # one text, written as a single string
            raw = [raw]
        if isinstance(raw, list) and len(raw) == data.size and all(isinstance(e, str) for e in raw):
            axis.elements = raw
        else:
            _warn(f"{path.name}: axis '{name}' has elements that aren't one text per position "
                  f"({len(raw) if isinstance(raw, list) else type(raw).__name__} for {data.size} positions); "
                  "they are ignored")
    if "role" in ds.attrs:
        role = _attr_str(ds, "role", "", path)
        if role == "point":
            axis.role = role
        else:
            _warn(f"{path.name}: axis '{name}' has an unknown role {role!r}; it is read as a sweep axis")
    return axis


def _describe_value(name: str, ds: Any, path: Path) -> Value:
    if not isinstance(ds, h5py.Dataset):
        raise LBDError(f"{path.name}: /values/{name} is not a dataset")
    _check_loaded_name(name, path)
    is_bool = _bool_flag(ds, name, path)
    dtype = "bool" if is_bool else str(ds.dtype)
    if not is_bool and dtype not in _ALLOWED_DTYPES:
        raise LBDError(f"{path.name}: value '{name}' has unsupported type {ds.dtype}")
    if is_bool and ds.dtype != np.uint8:
        raise LBDError(f"{path.name}: boolean value '{name}' must be stored as uint8, not {ds.dtype}")
    return Value(
        name,
        None,
        _axes_list(_attr_str(ds, "axes", "", path)),
        unit=_attr_str(ds, "unit", "", path),
        label=_attr_str(ds, "label", name, path),
        shape=tuple(ds.shape),
        dtype=dtype,
    )


def _bool_flag(ds: h5py.Dataset, name: str, path: Path) -> bool:
    if "lbd_bool" not in ds.attrs:
        return False
    raw = _attr_to_python(ds.attrs["lbd_bool"], path)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw not in (0, 1):
        raise LBDError(f"{path.name}: value '{name}' has an invalid lbd_bool flag {raw!r} (must be 0 or 1)")
    return raw == 1


def _same_lengths(axes: Dict[str, Axis], values: Dict[str, Value]) -> None:
    """In a file being written, cut each axis and the values on it to the length all of them
    have reached (the writer extends them one after the other)."""
    for a, axis in axes.items():
        n = min([len(axis)] + [v.shape[i] for v in values.values() for i, x in enumerate(v.axes)
                               if x == a and i < len(v.shape)])
        if n < len(axis):
            axis.data = axis.data[:n]
        for v in values.values():
            v.shape = tuple(min(k, n) if i < len(v.axes) and v.axes[i] == a else k for i, k in enumerate(v.shape))


def _read_value_data(ds: h5py.Dataset, v: Value, path: Path, part: tuple = ()) -> np.ndarray:
    arr = np.asarray(ds[part] if part else ds[()])
    if v.dtype == "bool":
        if arr.size and arr.max() > 1:
            _warn(f"{path.name}: boolean value '{v.name}' contains numbers other than 0 and 1; "
                  "they are read as True")
        arr = arr.astype(bool)
    return arr


def _validate_loaded(d: Dataset, path: Path) -> None:
    for v in d.values.values():
        if v.name in d.axes:
            raise LBDError(f"{path.name}: '{v.name}' is used by an axis and a value")
        if len(v.axes) != len(v.shape):
            raise LBDError(f"{path.name}: value '{v.name}' has {len(v.shape)} dimension(s) but axes={v.axes}")
        for i, ax in enumerate(v.axes):
            if ax not in d.axes:
                raise LBDError(f"{path.name}: value '{v.name}' refers to missing axis '{ax}'")
            if len(d.axes[ax]) != v.shape[i]:
                raise LBDError(
                    f"{path.name}: value '{v.name}': dimension {i} has size {v.shape[i]} but axis '{ax}' "
                    f"has length {len(d.axes[ax])}"
                )
        # a data point's axes are the last ones with role "point"
        k = len(v.axes)
        while k > 0 and d.axes[v.axes[k - 1]].role == "point":
            k -= 1
        v.point_axes = v.axes[k:]
        v.elements = [d.axes[a].elements for a in v.point_axes]


# ---- helpers ---------------------------------------------------------------


def _check_name(name: Any) -> str:
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise LBDError(
            f"invalid name {name!r}: must start with a letter and contain only letters, digits and '_' (max 63)"
        )
    return name


def _check_elements(elements: Any, n: Optional[int], where: str) -> List[str]:
    """A list of texts, one per position (n of them, if given)."""
    if isinstance(elements, str) or not isinstance(elements, (list, tuple, np.ndarray)):
        raise TypeError(f"{where}: elements must be a list of texts, one per position, not {type(elements).__name__}")
    items = list(elements)
    bad = [e for e in items if not isinstance(e, str)]
    if bad:
        raise TypeError(f"{where}: elements must be texts; {bad[0]!r} is a {type(bad[0]).__name__}")
    if not items:
        raise LBDError(f"{where}: elements is empty; give one text per position")
    if n is not None and len(items) != n:
        raise LBDError(f"{where}: {len(items)} elements for {n} positions; give one text per position")
    return items


def _check_fits(arr: np.ndarray, dtype: str, name: str) -> np.ndarray:
    """Data for a value of type `dtype`: complex refused for real values, integers and booleans
    only when exactly representable."""
    if np.iscomplexobj(arr) and not dtype.startswith("complex"):
        raise LBDError(f"write: '{name}' is real ({dtype}); refusing to drop an imaginary part")
    if dtype == "bool":
        if arr.dtype != np.bool_ and not np.all(np.isin(arr, (0, 1))):
            raise LBDError(f"write: '{name}' is boolean; give True/False (or 0/1)")
    elif dtype.startswith(("int", "uint")):
        if arr.dtype.kind == "f" and not np.all(np.isfinite(arr) & (arr == np.round(arr))):
            raise LBDError(f"write: '{name}' holds whole numbers ({dtype}); got {arr.ravel()[:3]}")
        info = np.iinfo(dtype)
        if arr.size and (np.min(arr) < info.min or np.max(arr) > info.max):
            raise LBDError(f"write: '{name}' ({dtype}) can't hold {np.min(arr)} … {np.max(arr)}")
    return arr


def _check_shape(shape: Any, name: str) -> tuple:
    """A data point's shape: a tuple of positive ints (`()` for one number)."""
    if shape is None:
        return ()
    if isinstance(shape, (int, np.integer)) and not isinstance(shape, bool):
        shape = (shape,)
    if not isinstance(shape, (tuple, list)) or not all(
            isinstance(n, (int, np.integer)) and not isinstance(n, bool) for n in shape):
        raise TypeError(f"value '{name}': shape must be a tuple of whole numbers such as (3,) or (2, 2), not {shape!r}")
    if any(n < 1 for n in shape):
        raise LBDError(f"value '{name}': shape {tuple(shape)} has an empty dimension")
    return tuple(int(n) for n in shape)


def _value_elements(elements: Any, point: tuple, name: str) -> List[Optional[List[str]]]:
    """The elements of each dimension of a data point (None: numbered)."""
    where = f"value '{name}'"
    if elements is None:
        return [None] * len(point)
    if not point:
        raise LBDError(f"{where}: elements name the positions in a data point; give shape= too "
                       "(each data point here is one number)")
    items = list(elements) if isinstance(elements, (list, tuple)) else None
    if items is None:
        raise TypeError(f"{where}: elements must be a list of texts, or one list per dimension of a data point")
    if len(point) == 1 and all(isinstance(e, str) for e in items):
        return [_check_elements(items, point[0], where)]
    if len(items) != len(point):
        raise LBDError(f"{where}: give one list of elements per dimension of a data point "
                       f"({len(point)} for shape={point}), or None for a dimension left numbered")
    return [None if e is None else _check_elements(e, n, f"{where}, dimension {k + 1} of a data point")
            for k, (e, n) in enumerate(zip(items, point))]


def _check_loaded_name(name: str, path: Path) -> None:
    if not _NAME_RE.match(name):
        raise LBDError(f"{path.name}: invalid axis/value name {name!r}")


_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def new_uuid7() -> str:
    """A new UUID version 7 (RFC 9562): the Unix time in milliseconds (48 bits) and 74 random
    bits from the operating system's secure source (`os.urandom`), never from a seeded
    generator, so `random.seed` / `numpy.random.seed` never repeat an id, and processes saving
    at the same moment (also forked ones) get different ids."""
    if hasattr(_uuid, "uuid7"):                       # Python 3.14+
        return str(_uuid.uuid7())
    ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")      # 80 bits; 74 used
    value = (ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76                                # version 7
    value |= ((rand >> 62) & 0xFFF) << 64             # rand_a: 12 bits
    value |= 0b10 << 62                               # variant 10
    value |= rand & ((1 << 62) - 1)                   # rand_b: 62 bits
    return str(_uuid.UUID(int=value))


def _same_target(a: Path, b: Path) -> bool:
    """Whether two paths name the same file (also before the second exists)."""
    ra, rb = Path(a).expanduser().resolve(), Path(b).expanduser().resolve()
    return os.path.normcase(str(ra)) == os.path.normcase(str(rb))


def _created_text(value: Any) -> str:
    """`created` as stored: ISO-8601 text with a UTC offset. A `datetime`, or a text in that form
    (kept as written); a time without an offset gets this computer's offset."""
    if isinstance(value, _dt.datetime):
        when = value if value.tzinfo is not None else value.astimezone()
        return when.isoformat(timespec="seconds" if not when.microsecond else "microseconds")
    if isinstance(value, str):
        text = value.strip()
        try:
            # Python before 3.11 doesn't read "Z" for UTC
            when = _dt.datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text)
        except ValueError:
            when = None
        if when is not None and len(text) > 10:          # a time, not only a date
            return text if when.tzinfo is not None else when.astimezone().isoformat(timespec="seconds")
    raise LBDError(f"created must be a date and time: a datetime, or ISO-8601 text such as "
                   f"'2026-10-13T16:09:00+08:00', not {value!r}")


def _check_text(value: Any, what: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{what} must be a string, not {type(value).__name__} ({value!r})")
    return value


def _check_style_name(name: Any) -> str:
    if not isinstance(name, str):
        raise TypeError(f"style_name must be a string or None, not {type(name).__name__}")
    if not name.strip():
        raise LBDError("style_name must not be empty; use None to remove it")
    return name


def _json_text(obj: Any, what: str) -> str:
    try:
        return json.dumps(obj, allow_nan=False, ensure_ascii=False)
    except ValueError:
        raise LBDError(f"{what} contains NaN or inf, which JSON can't store") from None
    except TypeError as e:
        raise LBDError(f"{what} can't be stored as JSON: {e}") from None


def _plot_json(spec: Any, what: str) -> str:
    if not isinstance(spec, Mapping):
        raise LBDError(f"{what} must be a dict of plot settings, not {type(spec).__name__}")
    unknown = sorted(str(k) for k in spec if k not in PLOT_SPEC_KEYS)
    if unknown:
        raise LBDError(f"{what}: unknown plot setting(s) {unknown}; allowed: {sorted(PLOT_SPEC_KEYS)}")
    ann = spec.get("annotations")
    if ann is not None and not (isinstance(ann, list) and all(isinstance(a, Mapping) for a in ann)):
        raise LBDError(f"{what}: annotations must be a list of objects such as "
                       '{"method": "axvline", "args": [1.0]}')
    return _json_text(dict(spec), what)


def _style_json(style: Any, what: str) -> str:
    if not isinstance(style, Mapping):
        raise LBDError(f"{what} must be a dict of style settings, not {type(style).__name__}")
    return _json_text(dict(style), what)


def _as_array(data: Any, what: str) -> np.ndarray:
    if isinstance(data, np.ma.MaskedArray):
        raise LBDError(f"{what}: masked arrays are not supported; fill the masked entries "
                       "(e.g. data.filled(np.nan)) first")
    try:
        return np.asarray(data)
    except ValueError as e:  # ragged nested lists
        raise LBDError(f"{what}: can't make an array of this data: {e}") from None


def _axes_argument(axes: Any) -> List[str]:
    if axes is None:
        return []
    if isinstance(axes, Mapping):
        raise TypeError("axes must be a name, a comma-separated string or a list of names, not a dict")
    if isinstance(axes, str):
        return _axes_list(axes)
    if isinstance(axes, np.ndarray):
        axes = axes.tolist()
    try:
        out = list(axes)
    except TypeError:
        raise TypeError(f"axes must be a name or a list of names, not {type(axes).__name__}") from None
    bad = [a for a in out if not isinstance(a, str)]
    if bad:
        raise TypeError(f"axis names must be strings, got {bad!r}")
    return out


def _axes_list(axes: str) -> List[str]:
    if axes.strip() == "":
        return []
    return [a.strip() for a in axes.split(",")]


def _normalize_dtype(arr: np.ndarray, what: str, quiet: bool = False) -> np.ndarray:
    """Map types other languages can't read (float16, long double, ...) to safe ones."""
    kind, size = arr.dtype.kind, arr.dtype.itemsize
    if kind == "f" and size < 4:
        arr = arr.astype(np.float32)  # float16: exact in float32 (documented)
    elif kind == "f" and size > 8:
        if not quiet:
            _warn(f"{what}: long double ({arr.dtype}) is stored as float64; extra precision is lost")
        arr = arr.astype(np.float64)
    elif kind == "c" and size > 16:
        if not quiet:
            _warn(f"{what}: {arr.dtype} is stored as complex128; extra precision is lost")
        arr = arr.astype(np.complex128)
    # Make byte order native (HDF5 stores the type, so this changes nothing in the file).
    if arr.dtype.byteorder not in ("=", "|"):
        arr = arr.astype(arr.dtype.newbyteorder("="))
    return _contiguous(arr)


def _coerce_value(data: Any, dtype: str, name: str) -> np.ndarray:
    arr = _as_array(data, f"value '{name}'")
    if arr.dtype.kind not in "biufc":
        raise LBDError(f"value '{name}' must be numeric or boolean, got dtype {arr.dtype}")
    if dtype == "auto":
        return _normalize_dtype(arr, f"value '{name}'")
    if dtype not in _ALLOWED_DTYPES:
        raise LBDError(f"value '{name}': unsupported dtype {dtype!r}; allowed: {list(_ALLOWED_DTYPES)} or 'auto'")
    target = np.dtype(dtype)
    src = arr.dtype.kind
    if src == "c" and target.kind != "c":
        raise LBDError(f"value '{name}' is complex; refusing to drop the imaginary part (dtype={dtype!r})")
    if target.kind == "b":
        if src != "b" and not np.all((arr == 0) | (arr == 1)):
            raise LBDError(f"value '{name}': dtype='bool' needs data that is only 0 and 1")
    elif target.kind in "iu":
        if src == "f":
            if not np.all(np.isfinite(arr)) or not np.all(arr == np.round(arr)):
                raise LBDError(f"value '{name}': dtype={dtype!r} needs whole, finite numbers; "
                               "round the data yourself if that is intended")
        if src in "iuf" and arr.size:
            lo, hi = np.iinfo(target).min, np.iinfo(target).max
            if src == "f":
                out_of_range = arr.min() < lo or arr.max() > hi
            else:
                out_of_range = int(arr.min()) < lo or int(arr.max()) > hi
            if out_of_range:
                raise LBDError(f"value '{name}': the data doesn't fit in {dtype} (range {lo}…{hi})")
    elif target.kind in "fc" and src in "fc" and arr.size:
        with np.errstate(over="ignore"):
            converted = arr.astype(target)
        if np.any(np.isfinite(arr) & ~np.isfinite(converted)):
            raise LBDError(f"value '{name}': some numbers are too large for {dtype} and would become inf")
    with np.errstate(over="ignore", invalid="ignore"):
        return _contiguous(arr.astype(target))


def _create_dataset(group: h5py.Group, name: str, data: np.ndarray, compression: Optional[str]) -> h5py.Dataset:
    if compression and data.ndim > 0 and data.size >= _COMPRESS_MIN_SIZE:
        return group.create_dataset(name, data=data, compression=compression, compression_opts=4, chunks=True)
    return group.create_dataset(name, data=data)


def _write_meta(group: h5py.Group, meta: Mapping[str, Any], where: str) -> None:
    for key, val in meta.items():
        if not isinstance(key, str) or not key or "/" in key or key == ".":
            raise LBDError(f"{where}: invalid meta key {key!r} (must be non-empty text without '/')")
        if isinstance(val, Mapping):
            _write_meta(group.create_group(key), val, f"{where}/{key}")
        else:
            group.attrs[key] = _meta_to_attr(val, f"{where}/{key}")


def _meta_to_attr(val: Any, where: str) -> Any:
    if val is None:
        raise LBDError(f"{where}: None can't be stored; omit the key instead")
    if isinstance(val, (bool, np.bool_)):
        return np.int64(int(val))
    if isinstance(val, str):
        return val
    if isinstance(val, int):
        if not _INT64.min <= val <= _INT64.max:
            raise LBDError(f"{where}: the integer {val} doesn't fit in int64; store it as a float or a string")
        return np.int64(val)
    if isinstance(val, float):
        return np.float64(val)
    if isinstance(val, complex):
        return np.complex128(val)
    if isinstance(val, np.generic):
        return _meta_array(np.asarray(val), where)[()]
    if isinstance(val, np.ma.MaskedArray):
        raise LBDError(f"{where}: masked arrays can't be stored in meta")
    if isinstance(val, (list, tuple, np.ndarray)):
        if isinstance(val, (list, tuple)):
            n_str = sum(isinstance(x, str) for x in val)
            if n_str and n_str != len(val):
                raise LBDError(f"{where}: a list in meta must hold only text or only numbers, not both")
            if n_str:
                return np.array(val, dtype=_STR_DTYPE)
            if any(isinstance(x, (Mapping, type(None))) for x in val):
                raise LBDError(f"{where}: lists in meta can't contain dicts or None")
        try:
            arr = np.asarray(val)
        except ValueError as e:
            raise LBDError(f"{where}: can't store this list in meta ({e})") from None
        return _meta_array(arr, where)
    raise LBDError(f"{where}: can't store a value of type {type(val).__name__} in meta")


def _meta_array(arr: np.ndarray, where: str) -> np.ndarray:
    kind = arr.dtype.kind
    if kind in "US":
        if arr.ndim != 1:
            raise LBDError(f"{where}: string arrays in meta must be 1-D")
        return np.array([str(x) for x in arr], dtype=_STR_DTYPE)
    if kind == "b":
        return arr.astype(np.int64)
    if kind not in "iufc":
        raise LBDError(f"{where}: can't store an array of dtype {arr.dtype} in meta (mixed or ragged list?)")
    return _normalize_dtype(arr, where)


def _read_meta(group: h5py.Group, path: Path, where: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, val in group.attrs.items():
        out[key] = _attr_to_python(val, path)
    for key, sub in group.items():
        if isinstance(sub, h5py.Group):
            if key in out:
                _warn(f"{path.name}: {where} has an attribute and a group both named '{key}'; the group is used")
            out[key] = _read_meta(sub, path, f"{where}/{key}")
        else:
            _warn(f"{path.name}: {where}/{key} is a dataset; LBD metadata are attributes, so it is skipped")
    return out


def _decode(b: bytes, path: Optional[Path]) -> str:
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        _warn(f"{path.name if path else 'file'}: some text is not valid UTF-8; unreadable characters are "
              "shown as �")
        return b.decode("utf-8", errors="replace")


def _attr_to_python(val: Any, path: Optional[Path] = None) -> Any:
    if isinstance(val, bytes):
        return _decode(val, path)
    if isinstance(val, np.generic):
        if isinstance(val, np.bytes_):
            return _decode(bytes(val), path)
        return val.item()
    if isinstance(val, np.ndarray):
        if val.dtype.kind == "O" or val.dtype.kind in "SU":
            return [_decode(x, path) if isinstance(x, bytes) else str(x) for x in val.ravel()]
        if val.ndim == 0:
            return val.item()
        return val
    return val


def _attr_str(obj: Union[h5py.Group, h5py.Dataset], key: str, default: str = "",
              path: Optional[Path] = None) -> str:
    if key not in obj.attrs:
        return default
    val = _attr_to_python(obj.attrs[key], path)
    if isinstance(val, list):
        if len(val) != 1:
            _warn(f"{path.name if path else 'file'}: attribute '{key}' of {obj.name} holds {len(val)} texts; "
                  "they are joined")
            return " ".join(val)
        val = val[0]
    if not isinstance(val, str):
        _warn(f"{path.name if path else 'file'}: attribute '{key}' of {obj.name} should be text but is "
              f"{type(val).__name__}; it is converted")
    return str(val)


def _attr_json(obj: h5py.Group, key: str, path: Path) -> Optional[Dict[str, Any]]:
    text = _attr_str(obj, key, "", path)
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        _warn(f"{path.name}: /plot/{key} is not valid JSON; ignored")
        return None
    if not isinstance(data, dict):
        _warn(f"{path.name}: /plot/{key} must be a JSON object, not {type(data).__name__}; ignored")
        return None
    if key == "spec":
        unknown = sorted(k for k in data if k not in PLOT_SPEC_KEYS)
        if unknown:
            _warn(f"{path.name}: the saved view has unknown setting(s) {unknown}; they are ignored")
            data = {k: v for k, v in data.items() if k in PLOT_SPEC_KEYS}
    return data


def _contiguous(arr: np.ndarray) -> np.ndarray:
    # np.ascontiguousarray would turn 0-D arrays into 1-D ones.
    return np.require(arr, requirements="C")

