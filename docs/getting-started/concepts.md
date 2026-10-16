# Concepts

This page explains what is inside an `.lbd` file and the rules every language follows.
The formal definition is the [format specification](../format.md); this page is the
plain-language version.

## What a file contains

An `.lbd` file holds one **dataset**:

| Part | What it is | Example |
|---|---|---|
| **Title, description** | Short text describing the dataset. | `"Resonator power sweep"` |
| **Axes** | 1-D arrays of coordinates, each with a unit and a label. | `freq` (401 points, Hz), `power` (11 points, dBm) |
| **Values** | N-D arrays of measured or computed data. Each dimension is tied to one axis. | `S21` with axes `(power, freq)` → shape 11 × 401 |
| **Meta** | Free key/value information about how the data was taken, which can be nested. | `T_mK = 12`, `vna.ifbw_Hz = 1000` |
| **Plot** (optional) | How the viewer should plot this file by default, and per-file style changes. | heat map of `S21` in dB, 120 mm wide |
| **Created, writer** | Written automatically: when, and by which program and version. | `2026-10-13T16:09:00+08:00`, `python lbd 1.0.0` |

A value with no axes is a single number (a *scalar*), for example a fitted quality factor.

Several values can share axes. A sweep can store `S21`, `S11` and a fitted `f0(power)` in one
file, all using the same `power` axis.

## Dimension order is the same in every language

Python stores arrays row by row, while MATLAB and Julia store them column by column. LBD hides
this difference: **the same file gives the same array shape and the same indexing in all three
languages**.

For a value saved with `axes = ["power", "freq"]`, 11 powers and 401 frequencies:

| | Shape | Element for power *i*, frequency *j* |
|---|---|---|
| Python | `S21.shape == (11, 401)` | `S21[i, j]` (0-based) |
| MATLAB | `size(S21) == [11 401]` | `S21(i, j)` (1-based) |
| Julia | `size(S21) == (11, 401)` | `S21[i, j]` (1-based) |

The order of `axes` is the order of the array's dimensions. You never transpose anything
yourself. The same rule applies to matrices stored in meta.

## Data types

Values keep their numeric type. These types are allowed:

| LBD type | Python (NumPy) | MATLAB | Julia |
|---|---|---|---|
| `float64` | `float64` | `double` | `Float64` |
| `float32` | `float32` | `single` | `Float32` |
| `int8` … `int64` | `int8` … `int64` | `int8` … `int64` | `Int8` … `Int64` |
| `uint8` … `uint64` | `uint8` … `uint64` | `uint8` … `uint64` | `UInt8` … `UInt64` |
| `complex128` | `complex128` | complex `double` | `ComplexF64` |
| `complex64` | `complex64` | complex `single` | `ComplexF32` |
| `bool` | `bool` | `logical` | `Bool` |

- **Complex data** is stored the way h5py and HDF5.jl store it natively (an HDF5 compound with
  members `r` and `i`). You don't have to split it into two arrays.
- **Booleans** (masks, flags) are stored as 0/1 bytes and come back as booleans.
- **Missing values** are `NaN`, which works for floating-point types only.
- **Axes** must be real numbers (integer or floating point).
- Types other languages can't read are converted automatically: `float16` becomes `float32`,
  and extended precision becomes `float64`.

By default every writer keeps the type of the data you pass in. You can force a type, for
example to store `float32` and halve the file size.

### Metadata types

Meta values can be text, numbers (integer, floating point or complex), numeric arrays, lists of
text, or nested groups. True/false values are stored as the integers 1/0. Empty or missing
values (`None`, `nothing`, `[]`) are refused; leave the key out instead.

Integers written by Python and Julia are 64-bit, so MATLAB reads them as `int64`. MATLAB itself
writes numbers as `double` unless you pass an integer type.

## Names

Axis and value names must:

- start with a letter,
- contain only letters, digits and `_`,
- be at most 63 characters long.

These rules make every name a valid identifier in Python, MATLAB and Julia, for example
`d.Values.S21` in MATLAB. Names are case-sensitive, and an axis and a value cannot share a name.

The display text belongs in the **label** (`"Frequency"`, `"|S21|"`, `"P(1), amp 0.2"`), which
can contain any characters.

## Order of axes and values

HDF5 lists the members of a group alphabetically. When a file is read, the axes and values come
back in alphabetical order, not in the order they were added. This never affects the data: the
dimension order of each value is stored explicitly in its `axes` list. The viewer shows axes in
the order the values use them.

## Units

Every axis and value has a unit string, which is `""` for dimensionless data. Use plain SI units
without prefixes where you can (`Hz`, `s`, `V`, `K`). The viewer then picks a readable prefix
on each plot, such as GHz or µs, so the same quantity from different files can be compared. See
[unit prefixes](../styles/scales-and-units.md#unit-prefixes).

## Versions and compatibility

Each file records the format version it was written with (currently `1.0`).

- A **newer minor version** (for example a `1.3` file read by a reader for `1.0`) can be read.
  The reader warns that some new content may be ignored.
- A **newer major version** (`2.0`) is refused with a clear message asking you to update.

The modules and the viewer of one release always share one version number, and the
[Language modules](../viewer/language-modules.md) page of the viewer shows which one.

Readers ignore anything they don't know. Tools may add extra data under `/extra` in the file
without breaking LBD readers.

## Consistent figures in your own code

LBD's goal is figures that look the same, whichever program made the data. The viewer covers
curves, scatter plots and heat maps; for anything else you draw the figure yourself. To keep
those figures consistent too, the viewer's styles are available in Python through
[`lbd.plot`](../python/plotting.md):

- `with lbd.plot.use("thesis"): ...` makes any matplotlib figure use the style's size,
  resolution, fonts, frame, ticks, colours and line widths.
- `lbd.plot.plot(dataset, ...)` draws the viewer's plot types from Python, even for data that
  was never saved to a file.
- Styles can be saved as files (`*.lbd.json`) next to the data of a paper, and exported as
  matplotlib `.mplstyle` files for people who don't use LBD.

## Where an .lbd file can be opened

Because an `.lbd` file is plain HDF5 inside, you can also inspect it with HDFView, `h5dump`,
h5py, MATLAB's `h5info`/`h5read`, or HDF5.jl. Write files with the LBD modules, though, so the
conventions above are followed.
