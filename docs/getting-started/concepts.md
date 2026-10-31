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

A value with no axes is a single number (a *scalar*), for example a fitted quality factor. It
is not plotted: the viewer lists it with its value, e.g. *Q = 12346*.

Several values can share axes. A sweep can store `S21`, `S11` and a fitted `f0(power)` in one
file, all using the same `power` axis.

**Elements** (format 1.2): an axis's positions can have names, e.g. a qubit prepared in
`ground` or `excited`, devices `Q1`, `Q2`, `Q3`. The axis still holds numbers (0, 1, 2 …); plots,
cursors and sliders show the names.

**Data points with a shape** (format 1.2): each data point of a value is one number, unless you
say otherwise. A Bloch vector per drive amplitude is a value whose data points have shape `(3,)`
(elements `x`, `y`, `z`); an I/Q covariance is a `(2, 2)` matrix per point. The value's array is
then *its axes first, then the data point*: 21 amplitudes × 3 → shape 21 × 3. The value's axes
are only what was swept (`amp`); the data point is described by the value itself (its shape and
elements). In the file LBD stores one small axis for each dimension of a data point
(`bloch_dim1`), so every program reads the file.

## Variable sweeps (axis groups)

The axes above make a **grid**: every combination of their points is a place in each value
(11 powers × 401 frequencies). Some measurements aren't a grid: the frequencies are chosen
around a resonance that moves with power, each row has a different number of points, points
are placed adaptively, or there are several such levels. For these, axes go in an **axis
group** (format 2.0): the group lists only the measured points, level by level.

For example, B chosen per A: A=1 → B=10; A=2 → B=10, 20; A=3 → B=15, 25, 35. The group stores
each level once:

| Level | Holds | Here |
|---|---|---|
| `A` | each A once | `[1, 2, 3]` |
| `B` | each (A, B) point's B | `[10, 10, 20, 15, 25, 35]` |
| `B`'s parent | the A it belongs to (an index into `A`) | `[0, 1, 1, 2, 2, 2]` |

A value measured once per (A, B) point has 6 entries; one measured once per A has 3. A value
can also lie on a group's points and on fixed axes together (a spectrum over a fixed frequency
axis at each (A, B) point: 6 × 401).

Three words keep this clear, in every language:

- **Sweep axes** (`axes`): what was swept, fixed axes or the axes of a group. A value's `axes`
  lists the ones it depends on, e.g. `A, B`.
- **Dimensions** (`dims`): how the sweep part is stored, one per array dimension: `A` for a fixed
  axis, `(A, B)` for the points of a group's level.
- **Data point** (`point_shape`): one measured result: one number, or a vector or matrix.

A value's array is always its dimensions' lengths, then its data point: `(6, 2, 2)` for a 2 × 2
matrix per (A, B) point. To get a rectangle back, `to_dense` places the points in the full A × B
grid (gaps are `NaN`); `rows` gives the value row by row; `coords` gives each point's
coordinates. See the [Python](../python/files.md#variable-sweeps-axis-groups),
[MATLAB](../matlab.md#variable-sweeps-addgroup) and [Julia](../julia.md#variable-sweeps-add_group)
pages.

### Grid or group?

**Use fixed axes (a grid)** when every combination of the axes is planned, even if the
measurement may stop early (the points not measured stay `NaN`) or a few points are skipped.
**Use a group** when the inner points depend on the outer one.

| | Grid (fixed axes) | Group |
|---|---|---|
| Storage | the full rectangle: wasteful when most of it is never measured | only the measured points |
| Inner points | the same for every outer point | chosen per outer point, any number (0 too) |
| Reading | `data[i, j]` is A index i, B index j: plain array indexing | `data[k]` is the k-th point: by axis needs `rows`, `coords` or `to_dense` |
| A rectangle for plots and arrays | it already is one | `to_dense`: a copy, gaps `NaN`; can be large |
| Writing | an index per axis | coordinates (looked up) or `parent=`; float coordinates that differ only by rounding make two points (with a warning) |
| File format | 1.2: read by every LBD since 1.2 | **2.0: LBD older than 1.3 can't open it** |
| Other HDF5 tools (h5py, HDFView, `h5read`) | the arrays are the data, as they look | flat arrays plus `._parent` indices: readable, but you follow the parents yourself |
| LBD Viewer | every plot, Explore, cursors | drawn against the point number for now; drawing against the coordinates comes later |
| Speed | direct | `write` looks coordinates up (in memory, fast); `to_dense` and `coords` copy |

**A grid if you can; a group when a grid would be mostly empty or can't describe the sweep.**
A triangle (A = 1 … 50, B = 1 … A) leaves half of a 50 × 50 grid empty; 50 rows of 0 to 1 million
points each are 12 MB as a group and 400 MB as a grid.

## Dimension order is the same in every language

Some languages store arrays row by row (Python/NumPy, C), others column by column (MATLAB,
Julia, Fortran, R). LBD hides this difference: **the same file gives the same array shape and
the same indexing in every language**.

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

These rules make every name a valid identifier in common programming languages, for example
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
