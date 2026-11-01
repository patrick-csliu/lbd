"""Read and write LBD (.lbd) files. See spec/LBD-v1.md.

Invalid input raises `LBDError` (or `TypeError` for arguments of the wrong type); input that is
stored but changed or partly ignored (e.g. long double stored as float64) gives an `LBDWarning`.
Nothing is dropped or altered without one of the two.
"""

from __future__ import annotations

import contextlib
import copy
import dataclasses
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
        `None` for every axis in `Dataset.axes` (a sweep axis). `"point"` marks an axis of a
        dimension inside a value's data point, as the file stores it (format 1.2); such axes
        aren't in `Dataset.axes`: a value describes its data point (`point_shape`,
        `elements`).
    grows : bool
        An axis of unknown length (`add_axis(..., grows=True)`): [`write`][lbd.Dataset.write]
        adds its points. Not stored in the file (a saved file has the points written).
    group : str or None
        The axis group it belongs to (format 2.0), `None` for a fixed axis. An axis in a group
        holds one entry per point of its level: `data` is each point's coordinate.
    parent : numpy.ndarray or None
        For an axis in a group below its first: for each point, the index (from 0) of the
        point it belongs to in the level above. `None` for a fixed axis and a group's first.
    """

    name: str
    data: np.ndarray
    unit: str = ""
    label: str = ""
    elements: Optional[List[str]] = None
    role: Optional[str] = None
    grows: bool = False
    group: Optional[str] = None
    parent: Optional[np.ndarray] = None

    def __len__(self) -> int:
        return len(self.data)


@dataclass
class Group:
    """An axis group (format 2.0): axes whose points are listed together, outer to inner, for a
    sweep whose inner points depend on the outer ones (B chosen per A). Only measured points
    are stored, level by level: see [`Axis`][lbd.Axis] `group` and `parent`.

    Attributes
    ----------
    name : str
        Group name, e.g. `"scan"`.
    order : list of str
        Its axes, outer to inner (the order they were added in).
    """

    name: str
    order: List[str] = field(default_factory=list)


@dataclass
class Value:
    """An N-D value of a dataset: a result measured over the sweep axes.

    Created by [`Dataset.add_value`][lbd.Dataset.add_value] or read from a file. Its array
    splits the same way every time: the sweep first (one dimension per entry of `dims`), then
    one data point (`point_shape`), so `data.shape == lengths of dims + point_shape`.

    Attributes
    ----------
    name : str
        Value name, e.g. `"S21"`.
    data : numpy.ndarray or None
        The array: 0-D for a scalar, `bool` for boolean values. `None` if the file was read
        without this value's data (see [`load`][lbd.load] with `values=`).
    axes : list of str
        What was swept: the sweep axes the value depends on, outer to inner (`d.axes[name]`
        holds each). Never the data point's dimensions.
    unit : str
        Unit, `""` for dimensionless.
    label : str
        Display text, e.g. `"|S21|"`.
    shape : tuple
        Array shape, available even when `data` is `None`.
    dtype : str
        LBD type name, e.g. `"complex128"` or `"bool"`.
    dims : list of tuple of str
        How the sweep part is stored: one tuple of axis names per sweep dimension of `data`,
        `[("power",), ("freq",)]` for a grid.
    point_shape : tuple
        The shape of one data point: `()` for one number, `(3,)` for a vector of 3, `(2, 2)`
        for a matrix (format 1.2).
    elements : list
        For each dimension of a data point, the text of each position, or `None` when it is
        known by number (format 1.2); `[]` when each data point is one number.
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
    dims: List[tuple] = field(default_factory=list)
    point_shape: tuple = ()
    elements: List[Optional[List[str]]] = field(default_factory=list)
    measured: Optional[np.ndarray] = None
    # how the file names and labels the data point's dimensions (axes with role "point")
    _point: List[Axis] = field(default_factory=list, repr=False, compare=False)
    # the dataset it belongs to (for coords, rows, to_dense)
    _owner: Optional["Dataset"] = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.dims:
            self.dims = [(a,) for a in self.axes]

    def coords(self) -> Dict[str, np.ndarray]:
        """Each point's coordinates: one array per axis, along its dimension of `data`.

        For a fixed axis, its coordinates (`d.axes[name].data`); for the points of an axis
        group, every point's coordinate on each axis down to it (following `parent`). A copy.

        Examples
        --------
        >>> f.coords()      # f on a group A → B: {"A": [1, 2, 2, 3, 3, 3], "B": [10, 10, 20, 15, 25, 35]}
        >>> plt.scatter(c["A"], c["B"], c=f.data)
        """
        from . import groups

        return groups.coords(self._dataset(), self)

    def rows(self, by: str) -> Iterator[tuple]:
        """The value row by row: one row per point of `by`'s level (per position of a fixed
        axis `by`), as `(key, row)`. The key is the coordinate, or the coordinates down to `by`
        as a tuple; the row is an `lbd.Dataset` with what lies inside it (a copy).

        Examples
        --------
        >>> for a, row in f.rows(by="A"):
        ...     plt.plot(row.axes["B"].data, row.values["f"].data, label=f"A = {a}")
        """
        from . import groups

        return groups.rows(self._dataset(), self, by)

    def to_dense(self, round: Optional[int] = None, rtol: Optional[float] = None,
                 atol: Optional[float] = None, limit: Optional[int] = 10 ** 8) -> "Dataset":
        """The value as a full rectangle: an `lbd.Dataset` with fixed axes only.

        A group stores only the measured points ("sparse"); this places them in the full
        rectangle ("dense"), like scipy's `toarray()` or pandas / xarray `unstack`. Each axis's
        ticks are the sorted distinct coordinates of this value's points; cells not measured
        hold `NaN` (for integers and booleans 0 / False, with `measured` marking the measured
        cells). It doesn't interpolate, and it is always a copy. For fixed axes only, it is a
        copy of the value with its axes.

        Parameters
        ----------
        round : int, optional
            Round coordinates to this many decimals (as `np.round`) before making the ticks:
            merges coordinates that differ only by rounding (`0.1 + 0.2` and `0.3`).
        rtol, atol : float, optional
            Merge coordinates as `np.isclose` would (`|a − b| <= atol + rtol·|b|`): sorted, a
            coordinate close to the first of the current tick joins it; the tick is their mean.
            Only what is given is used (`rtol=1e-9` alone has `atol=0`). Not with `round`.
        limit : int or None, optional
            Refuse a rectangle of more cells (default 10**8); `None`: no limit.

        Raises
        ------
        LBDError
            Too many cells; two points in one cell after merging (a result would be lost);
            `round` together with `rtol` / `atol`.

        Warns
        -----
        LBDWarning
            Coordinates that differ only by rounding became separate ticks (no option given).
        """
        from . import groups

        return groups.to_dense(self._dataset(), self, round=round, rtol=rtol, atol=atol, limit=limit)

    def _dataset(self) -> "Dataset":
        d = self._owner
        if d is None or d.values.get(self.name) is not self:
            raise LBDError(f"value '{self.name}' isn't part of a dataset (any more); use the dataset's form, "
                           f"e.g. d.to_dense('{self.name}')")
        return d

    def _read(self, selection: Any = ()) -> np.ndarray:
        """Part of the data, the one way LBD reads a value's data (a file opened with lbd.open
        reads only this part)."""
        if self.data is None:
            raise LBDError(f"value '{self.name}' was not loaded; load the file without `values=`")
        if isinstance(self.data, np.ndarray):
            return self.data[selection]
        if hasattr(self.data, "_source"):                # lazy.OnDisk
            return self.data[selection]
        return np.asarray(self.data)[selection]


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
        Sweep axes by name (fixed axes, and the axes of axis groups). Add with `add_axis`.
    groups : dict of str to Group
        Axis groups by name (format 2.0): sweeps whose inner points depend on the outer ones.
        Add with `add_group`.
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
        self.groups: Dict[str, Group] = {}
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
        self._room: Dict[Any, np.ndarray] = {}     # buffers with room for arrays that grow (groups.grown)
        self._lookups: Dict[str, Any] = {}         # each group level's points by coordinate (groups.lookup)
        self._source: Any = None                    # lbd.open: the file its values are read from (lazy._Source)

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

    def add_group(self, name: str) -> Group:
        """Add an axis group (format 2.0): a sweep whose inner points depend on the outer ones,
        e.g. B chosen per A, a different number of B for each A, adaptive points.

        Add its axes next, outer to inner, with `add_axis(name, group=...)`; their points come
        with [`write`][lbd.Dataset.write] (only measured points are stored). A file with a
        group is format 2.0, which LBD older than 1.3 can't read; use fixed axes when every
        combination of the axes is planned.

        Raises
        ------
        LBDError
            Invalid or already used name.

        Examples
        --------
        >>> d.add_group("scan")
        >>> d.add_axis("power", group="scan", unit="dBm")
        >>> d.add_axis("freq", group="scan", unit="Hz")     # frequencies chosen per power
        >>> d.add_value("S21", axes=["power", "freq"], dtype="complex128")
        """
        self._check_new_name(name)
        group = Group(name)
        self.groups[name] = group
        return group

    def add_axis(self, name: str, data: Any = None, unit: str = "", label: Optional[str] = None,
                 elements: Optional[Sequence[str]] = None, grows: bool = False,
                 group: Optional[str] = None) -> Axis:
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
        group : str, optional
            Make it an axis of this axis group (`add_group`), after the group's axes added so
            far (outer to inner). Give no `data`: [`write`][lbd.Dataset.write] adds its points,
            by coordinate.

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
        if group is not None:
            if group not in self.groups:
                raise LBDError(f"axis '{name}': there is no group '{group}'; add it first with add_group('{group}')")
            if data is not None or elements is not None or grows:
                raise LBDError(f"axis '{name}' is in group '{group}': give no data, elements or grows; write adds "
                               "its points by coordinate")
            g = self.groups[group]
            axis = Axis(name, np.empty(0, dtype=np.int64), unit=unit, label=label, group=group,
                        parent=None if not g.order else np.empty(0, dtype=np.int64))
            g.order.append(name)
            self.axes[name] = axis
            return axis
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
            The axes the value depends on, outer to inner: a list (`["power", "freq"]`), one
            name (`"freq"`), a comma-separated string (`"power,freq"`), or `None` for a scalar.
            A fixed axis is one dimension of `data`. Axes of an axis group are one dimension
            together, the points of their level: the group's first axes in its order
            (`["A", "B"]` of a group A → B → C: one entry per (A, B) point), or the group's
            name for all of them. Each dimension's size must equal its axis length (its
            level's number of points).
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
            The value describes its data point (`point_shape`, `elements`); the file stores
            each of its dimensions as an axis named `<name>_dim1`, `<name>_dim2` …
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
        from . import groups

        dims = groups.dimensions(self, _axes_argument(axes), f"value '{name}'")
        axes_list = [a for dim in dims for a in dim]
        point = _check_shape(shape, name)
        measured = None
        placeholder = None
        if data is None:                      # filled later by write: "not measured yet"
            kind = "float64" if dtype == "auto" else dtype
            if kind not in _ALLOWED_DTYPES:
                raise LBDError(f"value '{name}': unknown dtype {dtype!r}; use one of {', '.join(_ALLOWED_DTYPES)}")
            full = tuple(groups.dim_length(self, dim) for dim in dims) + point
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
        nd = len(dims)
        shown = [",".join(dim) if len(dim) > 1 else dim[0] for dim in dims]
        if nd + len(point) != arr.ndim:
            if nd < arr.ndim and not point:
                raise LBDError(
                    f"value '{name}' has {arr.ndim} dimension(s) but {nd} were given: {shown}; if each data "
                    f"point holds several numbers, say so with shape={tuple(arr.shape[nd:])}")
            raise LBDError(
                f"value '{name}' has {arr.ndim} dimension(s) {tuple(arr.shape)}, but its axes {shown} "
                f"and shape={point} make {nd + len(point)}")
        growing = [dim[0] for dim in dims if self.axes[dim[0]].grows]
        if growing and dims[0][0] != growing[0] or len(growing) > 1:
            raise LBDError(f"value '{name}': a growing axis must be its first axis, and only one "
                           f"(here {axes_list}, growing {growing})")
        for i, dim in enumerate(dims):
            n = groups.dim_length(self, dim)
            if n != arr.shape[i]:
                hint = (f"; the value's axes come first, then the data point (e.g. use `.T`)"
                        if point and arr.shape[-len(point):] != point else "")
                if groups.is_group_dim(self, dim):
                    what = f"the level {shown[i]} of group '{self.axes[dim[0]].group}' has {n} points"
                else:
                    what = f"axis '{dim[0]}' has length {n}"
                raise LBDError(f"value '{name}': dimension {i} has size {arr.shape[i]} but {what}{hint}")
        if point and tuple(arr.shape[nd:]) != point:
            raise LBDError(f"value '{name}': its data points have shape {tuple(arr.shape[nd:])}, "
                           f"not shape={point}")
        named = _value_elements(elements, point, name)
        value = Value(name, arr, axes_list, unit=unit, label=label, shape=arr.shape, dtype=str(arr.dtype),
                      dims=dims, point_shape=point, elements=named, measured=measured)
        value._owner = self
        value._point = _point_axes(value)
        for p in value._point:
            if p.name in self.axes or p.name in self.values or p.name in self._point_names():
                raise LBDError(f"value '{name}' needs the name '{p.name}' for a dimension of its data points in the "
                               "file, but it is already used; rename that axis or value")
        self.values[name] = value
        if placeholder is not None:
            self._placeholders.add(name)
        return value

    def write(self, names: Optional[Mapping[str, Any]] = None, *, parent: Any = None, **more: Any) -> Any:
        """Put measured data into values made by `add_value`: a point, a trace, a whole map, or
        several values at once, at the place the axes say.

        Each name is an axis or a value (as keywords, or in the dict `names` for a name that
        can't be a keyword, e.g. `d.write({"if": 3}, S21=z)`):

        - a **fixed axis**: an index (`power=3`), or one of its elements (`state="excited"`);
        - a **growing axis** (`add_axis(..., grows=True)`): its coordinate (`time=12.5`), or an
          array of them, adding as many points;
        - an **axis of a group** (`add_axis(..., group=...)`): its coordinate, or an array of
          them for several points. The group's axes are given outer first (`A=3, B=25`); the
          same coordinates are the same point (found, or added). Coordinates are compared
          exactly; a new point that differs from one already there only by rounding gives a
          warning;
        - a **value**: its data, shaped as the value's dimensions that weren't given (and its
          data point, always whole), in order: a point is one number, a trace at `power=3` of
          `S21[power, freq]` is one number per frequency; n points of a group, n entries.

        Writing again to the same place replaces the data there.

        Parameters
        ----------
        parent : int or array of int, optional
            Instead of the outer coordinates: the index of the outer point, as an earlier
            `write` returned it (`i = d.write(A=3)`, then `d.write(parent=i, B=25, f=x)`). No
            lookup, and exact even when coordinates are computed with rounding.

        Returns
        -------
        int, numpy.ndarray, dict or None
            When axes of a group are given: the index of the point at the deepest level given
            (an array for several points), for `parent=`. With several groups, a dict by
            group name. `None` when no group is involved.

        Raises
        ------
        LBDError
            An unknown name; no value (and no group point) given; a position out of range or an
            unknown element; a position for an axis a value doesn't lie on; a growing axis
            without its coordinate; an inner axis of a group without its outer ones (or
            `parent=`); NaN or inf as a coordinate; data of another shape than the place needs
            (the message says which); complex data for a real value, or numbers an integer or
            boolean value can't hold exactly.

        Warns
        -----
        LBDWarning
            A new point's coordinate differs from one already there (under the same outer
            point) only by rounding, e.g. 0.30000000000000004 next to 0.3.

        Examples
        --------
        >>> d.write(power=i, S21=trace)                    # a trace
        >>> d.write(power=i, freq=j, S21=z, T=t)           # a point, and T at power i
        >>> d.write(time=12.5, T=4.2)                      # a row of a growing axis
        >>> d.write(A=3, B=[15, 25, 35], f=[x1, x2, x3])   # 3 points of a group A → B
        >>> i = d.write(A=3)                               # an outer point, then under it:
        >>> d.write(parent=i, B=25, f=x)
        """
        if self._source is not None:
            from . import lazy

            lazy.check_change(self, "write")
        plan = self._plan_write(names, more, parent)
        if self._source is not None and (plan["grow"] is not None or plan["levels"]):
            raise LBDError(f"{self._source.path.name} is opened with lbd.open: write puts data at points that exist; "
                           "to add points (a growing axis, a group's new points) use lbd.load, or lbd.Writer")
        self._apply_write(plan)
        return plan["result"]

    def _plan_write(self, names: Optional[Mapping[str, Any]], more: Mapping[str, Any],
                    parent: Any = None) -> Dict[str, Any]:
        """Check a write against the dataset's shapes; returns what to put where (data not
        needed: `lbd.Writer` uses the same plan). Nothing is changed."""
        from . import groups

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
        positions = {k: v for k, v in given.items() if k in self.axes}
        in_groups = {a: x for a, x in positions.items() if self.axes[a].group is not None}
        if not values and not in_groups:
            raise LBDError("write: give at least one value with its data, e.g. write(power=3, S21=trace)")
        if parent is not None and not in_groups:
            raise LBDError("write: parent= names an outer point of a group; give the next axes of that group with it, "
                           "e.g. write(parent=i, B=25, f=x)")
        points = groups.plan_points(self, in_groups, parent) if in_groups else {}
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
            if self.axes[a].grows or a in in_groups:
                continue
            index_of[a] = self._position(a, x)
        puts = []
        for name, data in values.items():
            v = self.values[name]
            for a in positions:
                if a not in v.axes:
                    raise LBDError(f"write: '{name}' doesn't lie on '{a}' (its axes: {v.axes})")
            index, shape = [], []
            for dim in v.dims:
                a = dim[0]
                ax = self.axes[a]
                if groups.is_group_dim(self, dim):
                    p = points.get(ax.group)
                    if p is None:                          # every point of the level
                        index.append(slice(None))
                        shape.append(groups.dim_length(self, dim))
                        continue
                    if p["depth"] != dim[-1]:
                        missing = list(dim[dim.index(p["depth"]) + 1:])
                        raise LBDError(f"write: '{name}' lies on the points of {', '.join(dim)}: give {missing} too")
                    index.append(p["index"])
                    if p["n"] is not None:
                        shape.append(p["n"])
                elif ax.grows:
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
            index += [slice(None)] * len(v.point_shape)       # a data point is always given whole
            shape += list(v.point_shape)
            arr = np.asarray(data)
            if arr.shape != tuple(shape) and not (arr.size == 1 and shape == []):
                given_axes = [a for a in v.axes if a in positions]
                left = [",".join(dim) for dim in v.dims if not any(a in positions for a in dim)
                        or (groups.is_group_dim(self, dim) and points.get(self.axes[dim[0]].group, {}).get("n"))]
                left += [f"a data point of shape {v.point_shape}"] if v.point_shape else []
                raise LBDError(f"write: '{name}' at {given_axes or 'every place'} needs data of shape {tuple(shape)} "
                               f"({', '.join(left) or 'one number'}), not {arr.shape}")
            puts.append((name, tuple(index), _check_fits(arr.reshape(shape) if arr.size == 1 and shape == [] else arr,
                                                         v.dtype, name)))
        levels = [(a, np.asarray(cs), None if self.axes[a].parent is None else np.asarray(ps, dtype=np.int64))
                  for p in points.values() for a, cs, ps in p["new"]]
        result = None
        if len(points) == 1:
            result = next(iter(points.values()))["index"]
        elif points:
            result = {g: p["index"] for g, p in points.items()}
        return {"grow": grow, "levels": levels, "puts": puts, "result": result}

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
        from . import groups

        if plan["grow"] is not None:
            g, coords = plan["grow"]
            k = max(coords.size, 1)
            ax = self.axes[g]
            ax.data = groups.grown(self, ("axis", g), np.asarray(ax.data), 0, k, np.atleast_1d(coords), coords.dtype)
            self._extend_values(g, k)
        self._grow_levels(plan)
        for a, coords, _ in plan.get("levels", ()):
            self._extend_values(a, len(coords))
        for name, index, arr in plan["puts"]:
            v = self.values[name]
            if v.data is None:
                raise LBDError(f"write: value '{name}' was not loaded; load the file without `values=`")
            v.data[index] = arr
            if v.measured is not None:
                v.measured[index] = True

    def _grow_levels(self, plan: Dict[str, Any]) -> None:
        """Add a write's new group points to their levels (coordinates, parents, lookups);
        warn about a new point that differs from one already there only by rounding."""
        from . import groups

        near = []
        for a, coords, parents in plan.get("levels", ()):
            ax = self.axes[a]
            start, k = len(ax.data), len(coords)
            lk = self._lookups.get(a)
            ax.data = groups.grown(self, ("axis", a), np.asarray(ax.data), 0, k, coords, coords.dtype)
            if parents is not None:
                ax.parent = groups.grown(self, ("parent", a), np.asarray(ax.parent), 0, k, parents)
            if lk is not None and lk.n == start:
                for i, (c, p) in enumerate(zip(coords.tolist(), [-1] * k if parents is None else parents.tolist())):
                    other = lk.add(p, float(c), start + i)
                    if other is not None and coords.dtype.kind == "f":
                        near.append((a, c, other))
        if near:
            shown = "; ".join(f"{a} = {c!r} is a new point next to {o!r}" for a, c, o in near[:3])
            _warn(f"write: {shown}{' …' if len(near) > 3 else ''}. Coordinates are compared exactly: round the "
                  "coordinate, or write with parent= (the index write returned)")

    def _extend_values(self, axis: str, k: int) -> None:
        """`k` points were added to `axis` (a growing axis, or a group's level): every value on
        it grows along that dimension, the new points not measured (NaN, or a `measured` mask)."""
        from . import groups

        for v in self.values.values():
            for pos, dim in enumerate(v.dims):
                if dim[-1] != axis:
                    continue
                if v.data is None:
                    raise LBDError(f"write: value '{v.name}' was not loaded")
                if not v.dtype.startswith(("float", "complex")) and v.measured is None:
                    v.measured = np.ones(np.shape(v.data), dtype=bool)
                v.data = groups.grown(self, ("value", v.name), np.asarray(v.data), pos, k, groups.fill_for(v.dtype))
                if v.measured is not None:
                    v.measured = groups.grown(self, ("measured", v.name), np.asarray(v.measured), pos, k, False)
                v.shape = v.data.shape

    def _check_new_name(self, name: str) -> None:
        _check_name(name)
        if name in self.axes or name in self.values or name in self.groups:
            raise LBDError(f"name '{name}' is already used by an axis, group or value")
        if name in self._point_names():
            raise LBDError(f"name '{name}' is used in the file for a dimension of a value's data points")

    def _point_names(self) -> set:
        """The names the file gives the dimensions of the values' data points."""
        return {p.name for v in self.values.values() for p in v._point}

    # ---- reading values on groups -----------------------------------------

    def coords(self, value: str) -> Dict[str, np.ndarray]:
        """Each point's coordinates of a value: as [`Value.coords`][lbd.Value.coords]."""
        return self._value(value).coords()

    def rows(self, value: str, by: str) -> Iterator[tuple]:
        """A value row by row: as [`Value.rows`][lbd.Value.rows]."""
        return self._value(value).rows(by)

    def to_dense(self, value: str, round: Optional[int] = None, rtol: Optional[float] = None,
                 atol: Optional[float] = None, limit: Optional[int] = 10 ** 8) -> "Dataset":
        """A value as a full rectangle: as [`Value.to_dense`][lbd.Value.to_dense]."""
        return self._value(value).to_dense(round=round, rtol=rtol, atol=atol, limit=limit)

    def _value(self, name: str) -> Value:
        if name not in self.values:
            raise KeyError(f"no value named {name!r}; values: {list(self.values)}")
        v = self.values[name]
        v._owner = self
        return v

    # ---- access ---------------------------------------------------------

    def close(self) -> None:
        """Close the file of a dataset opened with [`lbd.open`][lbd.open]: what was read stays
        usable; reading more is refused. Nothing to do for a loaded dataset."""
        if self._source is not None:
            self._source.close()

    def __enter__(self) -> "Dataset":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

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
        for g in self.groups.values():
            lines.append(f"  group {g.name}: {' → '.join(g.order)}")
        for a in self.axes.values():
            where = f" (group {a.group})" if a.group else ""
            lines.append(f"  axis  {a.name}[{len(a)}]{where} {a.unit}".rstrip())
        for v in self.values.values():
            dims = ",".join(v.axes)
            point = f" point {v.point_shape}" if v.point_shape else ""
            lines.append(f"  value {v.name}({dims}){point} {v.dtype} {v.unit}".rstrip())
        return "\n".join(lines)

    # ---- saving ---------------------------------------------------------

    def save(self, path: Optional[PathLike] = None, compression: Optional[str] = None) -> Path:
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
        if self._source is not None:               # opened with lbd.open
            from . import lazy

            if lazy.check_change(self, "save", path):
                return lazy.save_in_place(self)
        if path is None:
            raise LBDError("save needs a path, e.g. d.save('sweep.lbd')")
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
        if self._source is not None:               # a copy of an opened file: this one stays as it is
            return path
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
            if a.group is not None:
                self._check_group_axis(key, a, arr)
                continue
            if arr.ndim != 1 or arr.size == 0 or arr.dtype.kind not in "iuf":
                raise LBDError(f"axis '{key}' must hold 1-D, non-empty real numbers; got {arr.dtype} {arr.shape}")
            if arr.dtype.kind == "f" and not np.all(np.isfinite(arr)):
                raise LBDError(f"axis '{key}' contains NaN or inf")
            if a.elements is not None:
                _check_elements(a.elements, arr.size, f"axis '{key}'")
            if a.role is not None:
                raise LBDError(f"axis '{key}' has role {a.role!r}; the axes of a dataset are sweep axes (None): "
                               "a value describes its data points with shape= (point_shape)")
        for key, g in self.groups.items():
            if not isinstance(g, Group) or g.name != key:
                raise LBDError(f"groups['{key}'] must be an lbd.Group named '{key}'")
            _check_name(key)
            if key in self.axes or key in self.values:
                raise LBDError(f"'{key}' is used by a group and an axis or value")
            for a in g.order:
                if a not in self.axes or self.axes[a].group != key:
                    raise LBDError(f"group '{key}' lists '{a}', which isn't an axis of that group")
        from . import groups

        shared: Dict[str, Axis] = {}          # data-point dimensions by their name in the file
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
            arr = v.data if hasattr(v.data, "_source") else np.asarray(v.data)    # lazy.OnDisk: not read
            if arr.dtype.kind not in "biufc" or                     str(_normalize_dtype(np.empty(0, arr.dtype), key, quiet=True).dtype) not in _ALLOWED_DTYPES:
                raise LBDError(f"value '{key}' has unsupported dtype {arr.dtype}")
            point = tuple(v.point_shape)
            dims = groups.dimensions(self, list(v.axes), f"value '{key}'")
            if [tuple(dim) for dim in v.dims] != dims:
                raise LBDError(f"value '{key}': dims={v.dims} doesn't match its axes {v.axes} (they make {dims})")
            if len(dims) + len(point) != arr.ndim:
                raise LBDError(f"value '{key}' has {arr.ndim} dimension(s) but its axes make {len(dims)}"
                               + (f" and point_shape={point} {len(point)} more" if point else ""))
            for i, dim in enumerate(dims):
                n = groups.dim_length(self, dim)
                if n != arr.shape[i]:
                    raise LBDError(f"value '{key}': dimension {i} has size {arr.shape[i]} "
                                   f"but {'the level ' + ','.join(dim) if len(dim) > 1 or self.axes[dim[0]].group else 'axis ' + dim[0]} "
                                   f"has {n} points")
            if point and tuple(arr.shape[len(dims):]) != point:
                raise LBDError(f"value '{key}': its data points have shape {tuple(arr.shape[len(dims):])}, "
                               f"but point_shape={point}")
            if len(v.elements) != len(point):
                raise LBDError(f"value '{key}': elements must have one entry per dimension of a data point "
                               f"({len(point)}), not {len(v.elements)}")
            for k, (el, n) in enumerate(zip(v.elements, point)):
                if el is not None:
                    _check_elements(el, n, f"value '{key}', dimension {k + 1} of a data point")
            for p in _point_axes(v):
                if p.name in self.axes or p.name in self.values:
                    raise LBDError(f"value '{key}': the name '{p.name}' of a dimension of its data points is "
                                   "also used by an axis or value")
                other = shared.setdefault(p.name, p)
                if len(other) != len(p) or other.elements != p.elements:
                    raise LBDError(f"two values give the dimension '{p.name}' of their data points different "
                                   "sizes or elements")
            if v.measured is not None and np.shape(v.measured) != arr.shape:
                raise LBDError(f"value '{key}': its measured mask has shape {np.shape(v.measured)}, not {arr.shape}")
        if not isinstance(self.meta, Mapping):
            raise LBDError(f"meta must be a dict, not {type(self.meta).__name__}")

    def _check_group_axis(self, key: str, a: Axis, arr: np.ndarray) -> None:
        """An axis of a group: in its group's order, one coordinate per point (finite real
        numbers, none yet allowed), and below the first level, a valid parent for each."""
        g = self.groups.get(a.group)
        if g is None or key not in g.order:
            raise LBDError(f"axis '{key}' says it is in group '{a.group}', which doesn't list it")
        if arr.ndim != 1 or arr.dtype.kind not in "iuf":
            raise LBDError(f"axis '{key}' must hold 1-D real numbers; got {arr.dtype} {arr.shape}")
        if arr.dtype.kind == "f" and not np.all(np.isfinite(arr)):
            raise LBDError(f"axis '{key}' contains NaN or inf")
        if a.elements is not None or a.grows:
            raise LBDError(f"axis '{key}' is in group '{a.group}': it has no elements and doesn't grow")
        k = g.order.index(key)
        if k == 0:
            if a.parent is not None:
                raise LBDError(f"axis '{key}' is the first of group '{a.group}': its parent must be None")
            return
        par = np.asarray(a.parent) if a.parent is not None else None
        above = len(self.axes[g.order[k - 1]].data)
        if par is None or par.shape != arr.shape or par.dtype.kind not in "iu":
            raise LBDError(f"axis '{key}' needs one parent index (an integer) per point; got "
                           f"{None if par is None else (par.dtype, par.shape)} for {arr.size} points")
        if par.size and (par.min() < 0 or par.max() >= above):
            raise LBDError(f"axis '{key}': a parent index is outside '{g.order[k - 1]}' (0 … {above - 1})")

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
        for a in _file_axes(self):
            ds = _create_dataset(g_axes, a.name, _normalize_dtype(np.asarray(a.data), a.name), compression)
            ds.attrs["unit"] = a.unit
            ds.attrs["label"] = a.label
            if a.elements is not None:
                ds.attrs.create("elements", np.array(a.elements, dtype=object), dtype=_STR_DTYPE)
            if a.role is not None:
                ds.attrs["role"] = a.role
        for g in self.groups.values():                # axis groups (spec §1.8), level by level
            gg = g_axes.create_group(g.name)
            gg.attrs["order"] = ",".join(g.order)
            for k, name in enumerate(g.order):
                a = self.axes[name]
                ds = _create_dataset(gg, name, _normalize_dtype(np.asarray(a.data), name), compression)
                ds.attrs["unit"] = a.unit
                ds.attrs["label"] = a.label
                if k:
                    _create_dataset(gg, name + "._parent", np.asarray(a.parent, dtype=np.int64), compression)

        g_values = f.create_group("values")
        for v in self.values.values():
            if hasattr(v.data, "_source"):          # opened with lbd.open: copied inside HDF5, never read whole
                ds = v.data._copy_to(g_values, v.name)
                is_bool = v.dtype == "bool"
            else:
                data = _normalize_dtype(np.asarray(v.data), v.name)
                is_bool = data.dtype == np.bool_
                if is_bool:
                    data = data.astype(np.uint8)
                ds = _create_dataset(g_values, v.name, data, compression, whole=len(v.point_shape))
            ds.attrs["unit"] = v.unit
            ds.attrs["label"] = v.label
            ds.attrs["axes"] = ",".join(_dim_names(v))
            if is_bool:
                ds.attrs["lbd_bool"] = np.int64(1)

        masks = {v.name: v.measured for v in self.values.values()
                 if v.measured is not None and not np.all(v.measured)}
        if masks:                             # integer / boolean points never measured (stopped early)
            g_measured = f.create_group("measured")
            for name, m in masks.items():
                if hasattr(m, "_source"):
                    m._copy_to(g_measured, name)
                    continue
                _create_dataset(g_measured, name, np.asarray(m, dtype=np.uint8), compression,
                                whole=len(self.values[name].point_shape))

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
    for attempt in range(WRITING_READ_ATTEMPTS if writing else 1):
        try:
            d = _load_once(path, writing, wanted)
            break
        except (OSError, RuntimeError, LBDError) as e:
            # a file being written can be caught while its writer finishes it (the description
            # and metadata are rewritten then, outside SWMR): read it again in a moment
            if not writing or isinstance(e, FileNotFoundError) or attempt == WRITING_READ_ATTEMPTS - 1:
                raise
            if not path.exists():
                raise FileNotFoundError(f"{path.name} was finished while it was read: open "
                                        f"{path.name[:-len(WRITING_SUFFIX)]}") from None
            time.sleep(WRITING_READ_PAUSE)
    _validate_loaded(d, path)
    return d


WRITING_READ_ATTEMPTS = 20     # tries to read a file being written that changes under the reader
WRITING_READ_PAUSE = 0.05      # seconds between them


def _load_once(path: Path, writing: bool, wanted: Optional[set]) -> Dataset:
    """One reading of the file (see load)."""
    with _reading(path, writing) as f:
        d, described = _read_structure(f, path, writing)
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


def _read_structure(f: h5py.File, path: Path, writing: bool) -> tuple:
    """Everything but the values' data: the header, every axis and group whole (axes are small
    next to the data), and each value described (shape, type, dimensions). `load` and `info`
    read files through it; the values' data is read afterwards."""
    d = _read_header(f, path)
    for group in ("axes", "values"):
        if not isinstance(f.get(group), h5py.Group):
            raise LBDError(f"{path.name} has no /{group} group; it breaks the LBD format")
    for name, obj in f["axes"].items():
        if isinstance(obj, h5py.Group):
            _read_group(d, name, obj, path)
        else:
            d.axes[name] = _read_axis(name, obj, path)
    described = {name: _describe_value(name, ds, path) for name, ds in f["values"].items()}
    for v in described.values():
        v._owner = d
    _resolve_dims(d, described, path)
    if writing:                     # a growing axis, a group's levels and their values may be caught mid-write
        _same_lengths(d, described)
    return d, described


def _read_group(d: Dataset, name: str, grp: h5py.Group, path: Path) -> None:
    """An axis group (spec §1.8): its axes, level by level, with each point's parent."""
    _check_loaded_name(name, path)
    if name in d.axes:
        raise LBDError(f"{path.name}: '{name}' is used by an axis and a group")
    if "order" not in grp.attrs:
        raise LBDError(f"{path.name}: the axis group '{name}' has no 'order' attribute; it breaks the LBD format")
    order = _axes_list(_attr_str(grp, "order", "", path))
    if not order or len(set(order)) != len(order):
        raise LBDError(f"{path.name}: the axis group '{name}' has an invalid order {order}")
    for k, a in enumerate(order):
        if a in d.axes or a in d.groups:
            raise LBDError(f"{path.name}: '{a}' (in group '{name}') is used twice")
        ax = _read_axis(a, grp.get(a), path, f"/axes/{name}/{a}", in_group=True)
        ax.group = name
        if k:
            raw = grp.get(a + "._parent")
            if not isinstance(raw, h5py.Dataset):
                raise LBDError(f"{path.name}: axis '{a}' of group '{name}' has no '{a}._parent'; it breaks the LBD format")
            par = np.asarray(raw[()])
            if par.ndim != 1 or par.dtype.kind not in "iu":
                raise LBDError(f"{path.name}: '{a}._parent' must be 1-D integers, got {par.dtype} {par.shape}")
            ax.parent = par.astype(np.int64)
        d.axes[a] = ax
    d.groups[name] = Group(name, order)


def _resolve_dims(d: Dataset, values: Dict[str, Value], path: Path) -> None:
    """Each value's axes as the file lists them → its dimensions: the last ones with role
    "point" are its data point's (they move from `d.axes` to the value), the others are sweep
    dimensions (a fixed axis, or a group's level)."""
    from . import groups

    trailing: Dict[str, int] = {}
    for v in values.values():
        names = list(v.axes)
        k = len(names)
        while k > 0 and names[k - 1] in d.axes and d.axes[names[k - 1]].role == "point":
            k -= 1
        for a in names[k:]:
            trailing[a] = trailing.get(a, 0) + 1
        try:
            dims = groups.dimensions(d, names[:k], f"value '{v.name}'")
        except LBDError as e:
            raise LBDError(f"{path.name}: {e}") from None
        if len(dims) + len(names) - k != len(v.shape):
            raise LBDError(f"{path.name}: value '{v.name}' has {len(v.shape)} dimension(s) but axes={names}")
        v._point = [copy.copy(d.axes[a]) for a in names[k:]]
        v.axes = [a for dim in dims for a in dim]
        v.dims = dims
        v.point_shape = tuple(v.shape[len(dims):])
        v.elements = [p.elements for p in v._point]
    for name, a in list(d.axes.items()):
        if a.role != "point":
            continue
        swept = [v.name for v in values.values() if name in v.axes]
        if trailing.get(name) and swept:
            raise LBDError(f"{path.name}: axis '{name}' is a dimension of a data point of some values and a "
                           f"sweep axis of {swept}; it can't be both")
        if trailing.get(name):
            del d.axes[name]
        else:
            a.role = None
            _warn(f"{path.name}: axis '{name}' is marked as a dimension of a data point (role 'point') "
                  "but no value's data point uses it; it is read as a sweep axis")


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
    return FORMAT_VERSION if d.groups else _GRID_VERSION


def _read_axis(name: str, ds: Any, path: Path, where: Optional[str] = None, in_group: bool = False) -> Axis:
    where = where or f"/axes/{name}"
    if not isinstance(ds, h5py.Dataset):
        raise LBDError(f"{path.name}: {where} is not a dataset" if ds is not None else f"{path.name}: {where} is missing")
    _check_loaded_name(name, path)
    data = np.asarray(ds[()])
    if data.ndim != 1 or data.dtype.kind not in "iuf":
        raise LBDError(f"{path.name}: axis '{name}' must be 1-D real numbers, got {data.dtype} {data.shape}")
    axis = Axis(name, data, unit=_attr_str(ds, "unit", "", path), label=_attr_str(ds, "label", name, path))
    if in_group:
        if "elements" in ds.attrs or "role" in ds.attrs:
            _warn(f"{path.name}: axis '{name}' is in a group, where elements and role aren't used; they are ignored")
        return axis
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


def _same_lengths(d: Dataset, values: Dict[str, Value]) -> None:
    """In a file being written, keep what is complete: each group level's points up to the
    shortest of its coordinates and parents and up to the first point whose parent isn't
    there yet, and each axis (or level) and the values along it cut to the length all of them
    have reached (the writer extends them one after the other)."""
    changed = True
    while changed:
        changed = False
        for g in d.groups.values():
            above = None
            for name in g.order:
                ax = d.axes[name]
                n = len(ax.data) if ax.parent is None else min(len(ax.data), len(ax.parent))
                if ax.parent is not None:
                    late = np.flatnonzero(np.asarray(ax.parent[:n]) >= above)
                    n = int(late[0]) if late.size else n
                if n < len(ax.data) or (ax.parent is not None and n < len(ax.parent)):
                    ax.data = ax.data[:n]
                    ax.parent = None if ax.parent is None else ax.parent[:n]
                    changed = True
                above = n
        for a, axis in d.axes.items():
            along = [v.shape[i] for v in values.values() for i, dim in enumerate(v.dims)
                     if dim[-1] == a and i < len(v.shape)]
            n = min([len(axis)] + along)
            if n < len(axis):
                axis.data = axis.data[:n]
                if axis.parent is not None:
                    axis.parent = axis.parent[:n]
                changed = True
            for v in values.values():
                v.shape = tuple(min(k, n) if i < len(v.dims) and v.dims[i][-1] == a else k
                                for i, k in enumerate(v.shape))


def _read_value_data(ds: h5py.Dataset, v: Value, path: Path, part: tuple = ()) -> np.ndarray:
    arr = np.asarray(ds[part] if part else ds[()])
    if v.dtype == "bool":
        if arr.size and arr.max() > 1:
            _warn(f"{path.name}: boolean value '{v.name}' contains numbers other than 0 and 1; "
                  "they are read as True")
        arr = arr.astype(bool)
    return arr


def _validate_loaded(d: Dataset, path: Path) -> None:
    from . import groups

    for g in d.groups.values():
        above = None
        for k, name in enumerate(g.order):
            ax = d.axes[name]
            if ax.data.dtype.kind == "f" and not np.all(np.isfinite(ax.data)):
                raise LBDError(f"{path.name}: axis '{name}' of group '{g.name}' contains NaN or inf")
            if k:
                par = ax.parent
                if len(par) != len(ax.data):
                    raise LBDError(f"{path.name}: '{name}._parent' has {len(par)} entries for {len(ax.data)} points")
                if par.size and (par.min() < 0 or par.max() >= above):
                    raise LBDError(f"{path.name}: '{name}._parent' points outside '{g.order[k - 1]}' "
                                   f"(0 … {above - 1})")
            keys = np.stack([np.zeros(len(ax.data)) if ax.parent is None else ax.parent.astype(float),
                             ax.data.astype(float)], axis=1) if len(ax.data) else np.zeros((0, 2))
            if len(np.unique(keys, axis=0)) != len(keys):
                _warn(f"{path.name}: group '{g.name}' has the same point twice on level '{name}' "
                      "(same coordinate under the same outer point); both are kept")
            above = len(ax.data)
    for v in d.values.values():
        if v.name in d.axes or v.name in d.groups:
            raise LBDError(f"{path.name}: '{v.name}' is used by an {'axis' if v.name in d.axes else 'group'} and a value")
        for i, dim in enumerate(v.dims):
            n = groups.dim_length(d, dim)
            if n != v.shape[i]:
                what = f"the level {','.join(dim)} has {n} points" if groups.is_group_dim(d, dim) \
                    else f"axis '{dim[0]}' has length {n}"
                raise LBDError(f"{path.name}: value '{v.name}': dimension {i} has size {v.shape[i]} but {what}")


def _point_axes(v: Value) -> List[Axis]:
    """The axes the file stores for the dimensions of `v`'s data points (format 1.2: role
    "point", holding 0 … n−1): their names and labels as known (`v._point`), else as writers
    make them (`<value>_dim<k>`)."""
    out = []
    for k, n in enumerate(v.point_shape):
        known = v._point[k] if k < len(v._point) else None
        name = known.name if known is not None else f"{v.name}_dim{k + 1}"
        label = known.label if known is not None else \
            (f"{v.label} (dim{k + 1})" if len(v.point_shape) > 1 else v.label)
        out.append(Axis(name, np.arange(n), unit=known.unit if known is not None else "", label=label,
                        elements=v.elements[k] if k < len(v.elements) else None, role="point"))
    return out


def _dim_names(v: Value) -> List[str]:
    """One axis name per dimension of `v.data`, as the file's `axes` attribute lists them."""
    return list(v.axes) + [p.name for p in _point_axes(v)]


def _file_axes(d: Dataset) -> List[Axis]:
    """Every axis the file stores: the sweep axes, then each value's data-point axes (once
    each: values read from another program's file may share one)."""
    out = {a.name: a for a in d.axes.values() if a.group is None}
    for v in d.values.values():
        for p in _point_axes(v):
            out.setdefault(p.name, p)
    return list(out.values())


def _flat_view(d: Dataset) -> Dataset:
    """`d` with one axis per dimension of every value, as the file lays it out (format 1.2):
    a data point's dimensions are axes with role "point", listed last in the value's `axes`.
    A level of an axis group is one dimension: its axis (the level's last) is drawn against
    the point number, 0 … n−1, for now (it keeps `group`, so drawing code can say so).

    For drawing code (`lbd.plot`, LBD Viewer), which handles every dimension as an axis. It
    shares the arrays with `d`; a flat view of a flat view is itself."""
    if getattr(d, "_flat", False):
        return d
    flat = copy.copy(d)
    flat.axes = dict(d.axes)
    for name, a in d.axes.items():
        if a.group is not None:
            flat.axes[name] = Axis(name, np.arange(len(a.data)), label=f"{a.label} (point number)", group=a.group)
    flat.values = {}
    for name, v in d.values.items():
        pts = _point_axes(v)
        for p in pts:
            flat.axes.setdefault(p.name, p)
        names = [dim[-1] for dim in v.dims] + [p.name for p in pts]
        flat.values[name] = dataclasses.replace(v, axes=names, dims=[(a,) for a in names], _point=[])
    flat._flat = True
    return flat


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


def _create_dataset(group: h5py.Group, name: str, data: np.ndarray, compression: Optional[str],
                    whole: int = 0) -> h5py.Dataset:
    """Uncompressed data is stored in one piece (any part of it can be read directly);
    compressed data in chunks by `_chunk_shape` (`whole`: last dimensions kept whole)."""
    if compression and data.ndim > 0 and data.size >= _COMPRESS_MIN_SIZE:
        return group.create_dataset(name, data=data, compression=compression, compression_opts=4,
                                    chunks=_chunk_shape(data.shape, data.dtype.itemsize, whole))
    return group.create_dataset(name, data=data)


CHUNK_BYTES = 1 << 20          # a chunk of a saved file: about 1 MB


def _chunk_shape(shape: Sequence[int], itemsize: int, whole: int = 0, size: int = CHUNK_BYTES,
                 grows: Sequence[int] = ()) -> tuple:
    """Chunks that make reading a part cheap: the inner dimensions whole (a trace, a data point)
    as far as `size` bytes allow, then as many outer rows as fit; the last `whole` dimensions
    (a data point) always whole. `grows`: the dimensions that are unlimited (a growing axis, a
    group's level), whose current length doesn't limit the chunk."""
    shape = [max(int(n), 1) for n in shape]
    chunk = [1] * len(shape)
    budget = max(size // max(itemsize, 1), 1)
    for i in range(len(shape) - 1, -1, -1):
        n = budget if i in grows else shape[i]
        if i >= len(shape) - whole:
            chunk[i] = n
            budget = max(budget // n, 1)
        else:
            chunk[i] = max(1, min(n, budget))
            budget = max(budget // chunk[i], 1) if chunk[i] == n else 1
    return tuple(chunk)


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

