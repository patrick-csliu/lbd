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

[`d.save(path)`][lbd.Dataset.save] writes the file and sets `d.created`, `d.writer` and
`d.path`. An existing file is replaced.

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
