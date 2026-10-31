# Reading and writing files

```python
import lbd
```

The `lbd` package writes and reads `.lbd` files. It needs Python 3.9 or newer with `numpy` and
`h5py`; see [Install → Python](../getting-started/install.md#python). This page shows how to
use it. Every function and argument is listed in the [API reference](../reference/python/lbd.md).

For figures in the viewer's styles from Python, see [Plotting with lbd.plot](plotting.md). A
complete script that saves a measurement with its settings and reads it back is the
[curves example](../examples/curves_resonator.md).

## Quick example

```python
import numpy as np
import lbd

f = np.linspace(4e9, 8e9, 401)
p = np.arange(-40, 1, 4.0)
s21 = np.exp(1j * np.outer(p, f) * 1e-10)          # shape (11, 401) = (power, freq)

d = lbd.Dataset(title="Resonator power sweep")
d.add_axis("power", p, unit="dBm", label="Power")
d.add_axis("freq", f, unit="Hz", label="Frequency")
d.add_value("S21", s21, axes=["power", "freq"])
d.meta["T_mK"] = 12
d.meta["vna"] = {"ifbw_Hz": 1000.0, "averages": 4}
d.save("sweep.lbd")

d = lbd.load("sweep.lbd")
d["S21"].data.shape        # (11, 401)
d["S21"].axes              # ['power', 'freq']
d.meta["vna"]["averages"]  # 4
```

## Building a dataset

A [`Dataset`][lbd.Dataset] is the in-memory content of one file. Add the **axes** first, then
the **values** measured on them.

```python
import numpy as np
import lbd

t = np.linspace(0, 1e-6, 201)
v = np.sin(2e7 * t)

d = lbd.Dataset(title="Rabi", description="Drive amplitude 0.3")
d.add_axis("t", t, unit="s", label="Time")
d.add_value("trace", v, axes="t", unit="V")
d.add_value("mask", v > 0.5, axes="t")                       # stored as bool
d.add_value("raw", np.arange(201), axes="t", dtype="float32")  # force a type
d.add_value("fit_Q", 12345.6)                                # scalar, no axes
print(d)                                                     # one line per axis and value
```

- **Axes** ([`add_axis`][lbd.Dataset.add_axis]) are 1-D and real. Give the unit in plain SI
  (`"Hz"`, not `"GHz"`): the viewer and `lbd.plot` add prefixes when they plot.
- **Values** ([`add_value`][lbd.Dataset.add_value]) name one axis per dimension, in the order
  of the array's dimensions. `axes` takes a list, one name, or `"power,freq"`. Each dimension's
  size must match its axis.
- **Names** follow the [naming rules](../getting-started/concepts.md#names), and an axis and a
  value can't share a name.
- `d["S21"]` returns the value (or else the axis) with that name; `"S21" in d` tests for one.

### Elements and data points

An axis can name its positions (**elements**), and a value's data point can be a vector or a
matrix (its **shape**, as in numpy). Format 1.2.

```python
import numpy as np
import lbd

amp = np.linspace(0, 0.5, 21)
d = lbd.Dataset(title="Tomography")
d.add_axis("state", elements=["ground", "excited"])            # numbered 0, 1 by itself
d.add_axis("amp", amp, unit="V", label="Drive amplitude")
d.add_value("P1", np.zeros((2, 21)), axes=["state", "amp"])

bloch = np.stack([np.sin(amp), np.zeros(21), np.cos(amp)], axis=1)   # (21, 3): amp first
d.add_value("bloch", bloch, axes="amp", shape=(3,), elements=["x", "y", "z"])
cov = np.zeros((21, 2, 2))
d.add_value("cov", cov, axes="amp", shape=(2, 2), elements=[["I", "Q"], ["I", "Q"]])

print(d.axes["state"].elements)          # ['ground', 'excited']
print(d.values["bloch"].axes)            # ['amp']: what was swept
print(d.values["bloch"].point_shape)     # (3,): one data point
print(d.values["bloch"].data.shape)      # (21, 3): the sweep, then the data point
print(d.values["cov"].data[4])           # the 2 × 2 matrix at the 5th amplitude
```

- **`elements`** on an axis: one text per position, in order (repeats allowed). Give the
  coordinates too if they mean something (`add_axis("device", [1, 2, 5], elements=[...])`).
- **`shape`**: the shape of one data point. The data's dimensions are the value's axes **first**,
  then the data point's; `np.array([u, v, w])` (3 × N) needs `.T`, and LBD says so. Data with
  more dimensions than axes needs `shape=`: LBD doesn't guess.
- **`elements`** on a value names a data point's positions: one list for a vector, one list per
  dimension for a matrix (`None` leaves a dimension numbered).
- A value's `axes` are what was swept; its data point is described by `point_shape` and
  `elements`. The array always splits the same way: `data.shape` is the axes' lengths, then
  `point_shape` (a single number has `point_shape == ()`: no dimensions, as in numpy).
- `write` takes a whole data point: `d.write(amp=4, cov=[[1, 0.1], [0.1, 2]])`.
- In the file, each dimension of a data point is a small axis of its own (`bloch_dim1`,
  `cov_dim1`, `cov_dim2`, `role="point"`), so readers of every version read the file; the viewer
  draws the vector as one curve per element against `amp`.

### Filling values piece by piece

A value can be made before its data is measured, and filled point by point, trace by trace:

```python
import numpy as np
import lbd

d = lbd.Dataset(title="Power sweep")
d.add_axis("power", np.linspace(-60, 0, 7), unit="dBm")
d.add_axis("freq", np.linspace(6.99e9, 7.01e9, 201), unit="Hz")
d.add_value("S21", axes=["power", "freq"], dtype="complex128")   # every point NaN: not measured yet
d.add_value("n", axes="power", dtype="int32")                    # integers: a `measured` mask
for i in range(3):
    d.write(power=i, S21=np.ones(201), n=10 * i)                 # a trace, and n at power i
print(d.values["n"].measured)            # [ True  True  True False False False False]
d.save("sweep.lbd")                      # /measured/n records the points never measured
```

`write` takes a fixed axis's index (or one of its elements), and the data for the axes not
given; `add_axis("time", grows=True)` makes an axis whose points `write` adds. To write the file
**while** measuring, so it can be looked at and survives a crash, use `lbd.Writer` with the same
calls: see [Writing while measuring](../getting-started/writing-while-measuring.md).

### Variable sweeps (axis groups)

A grid (fixed axes) has the same inner points for every outer point. When the inner points
depend on the outer one (frequencies chosen around a resonance that moves with power, a
different number of points per row, adaptive sampling), put the axes in an **axis group**: only
the measured points are stored, level by level. Read [Grid or group?](../getting-started/concepts.md#grid-or-group)
first: a grid is simpler whenever it fits.

```python
import numpy as np
import lbd

d = lbd.Dataset(title="Variable sweep")
d.add_group("AB")                          # a group; its axes follow, outer to inner
d.add_axis("A", group="AB", unit="V")
d.add_axis("B", group="AB", unit="Hz")
d.add_axis("C", [0.1, 0.2, 0.3])           # a fixed axis, as always
d.add_value("f", axes=["A", "B"])          # one entry per (A, B) point
d.add_value("q", axes="A")                 # one per A
d.add_value("h", axes=["A", "B", "C"])     # per (A, B) point × C
d.add_value("cov", axes=["A", "B"], shape=(2, 2))   # a 2 × 2 matrix per (A, B) point

for a, bs in [(1, [10]), (2, [10, 20]), (3, [15, 25, 35])]:   # B chosen per A
    for b in bs:
        d.write(A=a, B=b, f=100 * a + b, h=[a, b, a + b], cov=[[a, b], [b, -a]])
    d.write(A=a, q=1.5 * a)

print(d.axes["B"].data)          # [10 10 20 15 25 35]: each (A, B) point's B
print(d.axes["B"].parent)        # [0 1 1 2 2 2]: the A it belongs to (an index into A)
print(d.values["f"].axes)        # ['A', 'B']: what was swept
print(d.values["f"].dims)        # [('A', 'B')]: stored as the (A, B) points
print(d.values["h"].dims)        # [('A', 'B'), ('C',)]: the points × C
print(d.values["cov"].shape)     # (6, 2, 2): the points, then one data point
d.save("variable.lbd")           # format 2.0
```

- **Writing:** a group's axis takes a **coordinate** (not an index), outer axes first; the same
  coordinates are the same point, found or added. An array writes several points:
  `d.write(A=3, B=[15, 25, 35], f=[x1, x2, x3])`. A fixed axis still takes an index.
- **`parent=`:** `write` returns the index of the point it wrote; give it as `parent=` to write
  under that point without a lookup (exact, even when coordinates are computed):

    ```python
    import numpy as np
    import lbd

    d = lbd.Dataset()
    d.add_group("ABC")
    for name in "ABC":
        d.add_axis(name, group="ABC")
    d.add_value("f", axes=["A", "B"])        # per (A, B) point
    d.add_value("g", axes=["ABC"])           # per (A, B, C) point (the group's name: all its axes)
    for a in [1, 2, 3]:
        i = d.write(A=a)                     # an A point
        for b in range(a):
            k = d.write(parent=i, B=b, f=10 * a + b)
            c = np.arange(b)                 # maybe no C at all
            d.write(parent=k, C=c, g=100 * a + 10 * b + c)
    print(d.axes["C"].data, d.axes["C"].parent)    # [0 0 0 1] [2 4 5 5]
    ```

- A value lies on an outer part of a group: `["A"]`, `["A", "B"]` or the whole group, never
  `["B"]` alone (a B means something only under its A).

**Reading.** Three ways, on the value or on the dataset (`d.to_dense("f")`, `d.rows("f",
by="A")`, `d.coords("f")`):

```python
import numpy as np
import lbd

d = lbd.Dataset()
d.add_group("AB")
d.add_axis("A", group="AB")
d.add_axis("B", group="AB")
d.add_value("f", axes=["A", "B"])
for a, bs in [(1, [10]), (2, [10, 20]), (3, [15, 25, 35])]:
    d.write(A=a, B=bs, f=[100 * a + b for b in bs])
f = d.values["f"]

m = f.to_dense()                       # the full rectangle: an lbd.Dataset with fixed axes
print(m.axes["B"].data)                # [10 15 20 25 35]: the distinct B
print(m.values["f"].data)              # 3 × 5, NaN where nothing was measured

for a, row in f.rows(by="A"):          # row by row: each row an lbd.Dataset
    print(a, row.axes["B"].data, row.values["f"].data)

c = f.coords()                         # each point's coordinates
print(c["A"], c["B"])                  # [1 2 2 3 3 3] [10 10 20 15 25 35]
```

- **`to_dense()`** places the measured points in a rectangle ("dense", as scipy's `toarray()`
  or pandas' `unstack`): each axis's ticks are the sorted distinct coordinates, gaps are `NaN`
  (0 / `False` with `measured` for integers and booleans). It doesn't interpolate, and it is a
  copy, refused above `limit=10**8` cells (`limit=None`: no limit). `m.save(...)` writes an
  ordinary 1.2 file.
- **`rows(by=...)`** gives one row per point of `by`'s level, the key being the coordinate (or
  the coordinates down to `by`). Rows of a group of three keep the rest as a group.
- **`coords()`** gives one array per axis, along its dimension: what `scatter`, a table or a fit
  needs. Underneath it follows `parent`: `A.data[B.parent]` is each (A, B) point's A.

<!-- no-check -->
```python
c = f.coords()
plt.tripcolor(c["A"], c["B"], f.data)            # a map filled between the measured points
plt.scatter(c["A"], c["B"], c=f.data)            # or the points themselves
f.data[(c["A"] >= 2) & (c["B"] < 30)]            # the points where …
pd.DataFrame({**c, "f": f.data})                 # a table: groupby, sort, CSV
```

**Near-equal coordinates.** Coordinates are compared exactly, so `A=0.1 + 0.2` and `A=0.3` are
two points. `write` warns when a new point differs from one already there only by rounding;
round the coordinate (`np.round(a, 9)`) or write with `parent=`. For a file that has such
points, `to_dense(round=9)` or `to_dense(rtol=1e-9)` (as `np.isclose`) merges them; merging two
measured points into one cell is refused, so no result is ever dropped.

### Metadata

`d.meta` is a plain dict for everything else about the measurement: temperatures, instrument
settings, notes. Nested dicts become groups.

```python
d.meta["T_mK"] = 12
d.meta["vna"] = {"ifbw_Hz": 1000.0, "averages": 4}
d.meta["note"] = "after re-cooling"
```

See [meta values](#meta-values) for what can be stored.

### Default plot and style

A file can carry its own [plot settings](../styles/plot-settings.md) and
[style changes](../styles/index.md), so it opens the same way everywhere:

```python
import numpy as np
import lbd

t = np.linspace(0, 1e-6, 201)
d = lbd.Dataset(title="Rabi")
d.add_axis("t", t, unit="s", label="Time")
d.add_value("trace", np.sin(2e7 * t), axes="t", unit="V")
d.plot = {"kind": "curve", "values": ["trace"], "y_label": "Signal"}
d.style = {"figure": {"width_mm": 120, "height_mm": 70}}
d.style_name = "thesis"        # a preset from the viewer's Styles page
d.save("run.lbd")
```

When a saved view or style is written, the file also records the installed matplotlib version
(`d.matplotlib` after loading, e.g. `"3.11.2"`), because a view's
[annotations](../styles/plot-settings.md#annotations) are matplotlib calls.

## Saving

[`d.save(path)`][lbd.Dataset.save] writes the file and sets `d.writer` and `d.path`. An
existing file is replaced.

- **`d.created`** is when the data was created (the date LBD Viewer's Library sorts and
  filters by). Give it when you know it, as a `datetime` or ISO-8601 text:
  `lbd.Dataset(title="Rabi", created="2026-10-13T16:09:00+08:00")` or `d.created = ...` (a time
  without an offset is taken in this computer's time zone). Not given: the first save fills in
  the time of that save. A loaded file keeps its `created`, and saving it again keeps it: only
  a new value changes it.
- **`d.id`** is the file's **id**: the measurement's identity, which LBD Viewer's Library uses to recognise
  the same measurement in two places (a copy, a backup, a synced folder). It is made at the first
  save (a UUID, from the time and random bits of the operating system: no setup, nothing to
  coordinate between computers) and is read-only. Saving again to the same file keeps it;
  saving to **another file** gives that file a new id, and the old one becomes its **parent
  id** (a new measurement made from this one). A file copied by the file system keeps its id. `d.parent_id` gives it; `d.new_id()` makes a loaded
  dataset a new measurement on purpose (to save it over the same file as something new).

- The file is written under a temporary name and renamed at the end, so the viewer or another
  program never sees a half-written file, and a failed save leaves the old file untouched.
- `compression="gzip"` compresses arrays of 1024 elements or more. It is lossless, and every
  language reads it transparently.

## Reading

```python
d = lbd.load("sweep.lbd")                    # everything
d = lbd.load("big.lbd", values=["S21"])      # only S21's data
i = lbd.info("sweep.lbd")                    # everything except value data: fast
```

- [`lbd.load`][lbd.load] reads a file. With `values=[...]` only those values' data is read;
  the others are still described (`shape`, `dtype`, `axes`, `unit`), with `data` set to `None`.
  Such a dataset can't be saved again until it is loaded fully.
- [`lbd.info`][lbd.info] reads no value data at all. Use it to list or check many files.

```python
from pathlib import Path
import lbd

for p in Path("data").rglob("*.lbd"):
    i = lbd.info(p)
    print(p.name, i.title, {n: v.shape for n, v in i.values.items()})
```

## Changing a file's saved view

[`lbd.set_plot`][lbd.set_plot] changes only the plot settings stored in a file; the data isn't
rewritten. It is what the viewer's **Save this view to the file** button uses.

```python
lbd.set_plot("sweep.lbd", spec={"kind": "heatmap", "values": ["S21"], "complex": "db"})
lbd.set_plot("sweep.lbd", style={"quantities": {"S21.db": {"vmin": -30, "vmax": 0}}})
lbd.set_plot("sweep.lbd", spec=None, style=None, style_name=None)   # remove everything
```

## Errors and versions

Everything LBD refuses raises [`LBDError`][lbd.LBDError]: invalid names, shapes or types, a file
that isn't LBD, data that can't be stored. A file written by a newer, incompatible LBD raises
its subclass [`LBDVersionError`][lbd.LBDVersionError]. File-system problems raise the usual
`OSError`.

[`lbd.version()`][lbd.version] tells you the package version and the format version it writes.
See [Versions and compatibility](../getting-started/concepts.md#versions-and-compatibility).

## Type conversion

### Values

| You pass | Stored as | Read back as |
|---|---|---|
| float64 / float32 arrays | same | same |
| integer arrays | same width and signedness | same |
| complex128 / complex64 | complex compound | complex128 / complex64 |
| bool arrays | uint8 0/1 + bool flag | bool |
| float16 | float32 | float32 |
| a Python number | 0-D array | 0-D array (`float(d["x"].data)` gives the number) |
| strings, objects | refused | — |

### Meta values

| You put in `meta` | Stored as | Read back as |
|---|---|---|
| `str` | UTF-8 text | `str` |
| `int` | int64 | `int` |
| `float` | float64 | `float` |
| `complex` | complex | `complex` |
| `bool` | int64 0/1 | `int` |
| NumPy scalar | its type | Python number |
| list/tuple/array of numbers | array (any number of dimensions) | `numpy.ndarray` |
| list of `str` | text array | `list[str]` |
| `dict` | sub-group | `dict` |
| `None` | refused at `save` | — |

Meta keys can be any text except an empty string, `"."`, or text containing `/`. For use in
MATLAB, stick to valid identifiers (letters, digits, `_`); other keys get renamed there.

## Recipes

### Add metadata to an existing file

```python
d = lbd.load("sweep.lbd")
d.meta["note"] = "checked 2026-10-14"
d.save("sweep.lbd")
```

### Write many files in a loop

```python
from pathlib import Path
import numpy as np
import lbd

f = np.linspace(4e9, 8e9, 401)
out = Path("out")
out.mkdir(exist_ok=True)

for k, T in enumerate([10, 20, 50]):
    d = lbd.Dataset(title=f"Sweep at {T} mK")
    d.add_axis("freq", f, unit="Hz", label="Frequency")
    d.add_value("S21", np.ones(401), axes="freq")      # your measurement here
    d.meta["T_mK"] = T
    d.save(out / f"sweep_{k:03d}.lbd", compression="gzip")
```
