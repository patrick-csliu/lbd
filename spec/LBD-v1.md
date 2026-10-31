# LBD file format — version 2.0

LBD ("Lab Data", extension `.lbd`) is a file format for measurement and simulation data that can be written and read identically from any programming language, and viewed with the LBD viewer. Any language with HDF5 support can implement it; this repository provides implementations for Python, MATLAB and Julia.

An `.lbd` file **is a plain HDF5 file**. Every HDF5 tool (HDFView, `h5dump`, h5py, MATLAB `h5info`, HDF5.jl) can open it. LBD only adds a fixed layout and a few conventions on top.

Keywords **must**, **should** and **may** follow RFC 2119.

For a plain-language introduction, see [Concepts](../docs/getting-started/concepts.md). For the APIs
that implement this spec, see [Python](../docs/python/files.md), [MATLAB](../docs/matlab.md) and
[Julia](../docs/julia.md).

---

<!-- The documentation site includes this file from here on (docs/format.md). -->
<!-- --8<-- [start:body] -->
## 1. Layout

```
/                       (root group)
├── attrs               lbd_format, lbd_version, title, description, created, writer [, id, parent_id]
├── axes/               (group)  one 1-D dataset per fixed axis, one group per axis group
│   ├── <axis name>     attrs: unit, label [, elements, role]
│   └── <group name>/   (group, since 2.0)  attrs: order
│       ├── <axis name>           attrs: unit, label
│       └── <axis name>._parent   (for every axis of the group but the first)
├── values/             (group)  one N-D dataset per value
│   └── <value name>    attrs: unit, label, axes [, lbd_bool]
├── meta/               (group)  free key/value metadata, stored as attributes; may contain sub-groups
├── measured/           (group, optional)  one uint8 mask per integer / boolean value not fully measured
├── plot/               (group, optional)  attrs: spec, style, style_name [, matplotlib]
└── extra/              (group, optional)  anything; ignored by LBD readers
```

### 1.1 Root attributes

| Attribute | Type | Required | Meaning |
|---|---|---|---|
| `lbd_format` | string, `"LBD"` | must | Identifies the file as LBD. |
| `lbd_version` | string, `"<major>.<minor>"` | must | Format version: `"2.0"` for a file with an axis group (§1.8), `"1.2"` for every other file written by this spec (`"1.0"` and `"1.1"` files are valid 1.2 files without the content added since). See §6. |
| `title` | string | must (may be `""`) | Short human-readable title. |
| `description` | string | must (may be `""`) | Free text. |
| `created` | string, ISO-8601 with UTC offset | must | When the data was created (measured), e.g. `2026-10-13T16:09:00+08:00`. Given by the user when known; otherwise writers fill in the time of the first save. A writer saving a dataset that already has a `created` (set by the user, or read from a file) writes it unchanged. |
| `writer` | string | must | Writer and its version, e.g. `"python lbd 1.0.0"`, `"matlab lbd 1.0.0"`, `"julia LBD 1.0.0"`. |
| `id` | string, a UUID version 7 (RFC 9562), lower case, e.g. `0192d4e2-7b3a-7c1e-9f2a-1c2b3d4e5f60` | should (since 1.1) | The measurement's identity: lets programs recognise the same measurement in two places (a copy, a backup, a synced folder). Rules below. |
| `parent_id` | string, a UUID | may (since 1.1) | The `id` of the file this one was made from. |

**`id` rules for writers.** The id is made from the current time in milliseconds and random
bits from the operating system's secure source (never from a seeded generator), so writers on
any computer make ids that don't collide, without coordination.

| What the writer does | `id` | `parent_id` |
|---|---|---|
| saves a new dataset for the first time | a new id | — |
| saves a dataset again to the file it was read from (or last saved to) | kept | kept |
| saves a dataset to another file | a new id | the old `id` |
| makes it a new measurement on request (e.g. `new_id()`) | a new id | the old `id` |
| (a file copied by the file system keeps both, byte for byte) | | |

A file without `id` (written by format 1.0 or by another program) gets one the next time an LBD
writer saves it. Readers must accept files without `id`; a value that is not a UUID is ignored
with a warning.

### 1.2 Axes — `/axes/<name>`

A dataset in `/axes` is a **fixed axis**: one dimension of a grid, the same points for every
point of the other axes. (A group in `/axes` is an axis group, §1.8.)

- 1-D numeric dataset (real; integer or floating point).
- Attributes:
  - `unit`: string, must; `""` for dimensionless.
  - `label`: string, must; a human-readable name used on plot axes, e.g. `"Frequency"`. Defaults to the axis name.
  - `elements`: 1-D array of strings, may (since 1.2); a text for each position of the axis, in order, e.g. `["ground", "excited"]` for an axis swept over named states. Readers show them instead of the numbers (tick labels, legends, read-outs). Any text; repeats allowed. Variable-length UTF-8 when written; readers must also accept fixed-length strings.
  - `role`: string, may (since 1.2); `"point"` for an axis of a dimension inside a value's data point (§1.3). Absent: a sweep axis (every axis written before 1.2).
- Axis values should be monotonic, but this is not enforced.
- A reader that finds `elements` with another count than the axis's length, or not strings, or a `role` other than `"point"`, ignores it with a warning.

### 1.3 Values — `/values/<name>`

- N-D numeric dataset with N ≥ 0. A 0-D (scalar) value has no axes.
- Attributes:
  - `unit`: string, must.
  - `label`: string, must; defaults to the value name.
  - `axes`: string, must. The names of the axes along each dimension, **comma-separated, in logical order** (see §2), e.g. `"power,freq"`. It is `""` for a 0-D value.
  - `lbd_bool`: integer `1`, only for boolean data (see §3).
- For every dimension *i*: the axis named in position *i* must exist in `/axes`, and its length must equal the size of dimension *i*.
- **Dimensions on an axis group** (since 2.0). A dimension can be one level of an axis group
  (§1.8): its points are the dimension's entries, so its size is the level's number of points.
  In `axes` it is written as the group's first *k* axes, consecutive and in the group's order
  (`"A,B"` = level 2 of a group whose `order` begins `A,B`), or as the group's name (its
  innermost level: all its axes). Writers write the axis names. Only an outer part of a group's
  order may be named (`"A"` or `"A,B"`, never `"B"` alone or `"A,C"`): an inner coordinate means
  something only under its outer ones. A group appears at most once in a value's `axes`.
  Consecutive names from one group form one dimension, so `axes="A,B,C"` with A, B in a group
  and C a fixed axis has two dimensions: the (A, B) points, then C. Fixed axes and other groups
  combine with it as a grid.
- **Data points with a shape** (since 1.2). Each data point of a value is one number, unless its
  last dimensions lie on axes with `role="point"`: then one data point is the array over those
  dimensions (a vector, a matrix). Writers make one such axis per dimension of the data point,
  named `<value>_dim<k>` (k = 1, 2 … within the data point), holding `0 … n−1` (and `elements` if
  the positions have names); e.g. a Bloch vector per drive amplitude: `axes="amp,bloch_dim1"`,
  with `/axes/bloch_dim1` = `[0, 1, 2]`, `role="point"`, `elements=["x", "y", "z"]`. These are
  ordinary axes, so readers of earlier versions read such values (with every dimension as an
  axis).

### 1.4 Meta — `/meta`

Free metadata stored as **attributes** of the `/meta` group. Nested structures (e.g. instrument settings) are stored as sub-groups of `/meta`, whose attributes are again key/value pairs, to any depth.

Allowed attribute values:
- string (UTF-8),
- integer or floating-point scalar,
- complex scalar (see §3),
- numeric array (any number of dimensions; logical order per §2),
- 1-D array of strings.

Booleans are stored as integers `0`/`1`. There is no null/missing; writers must reject it or the user must omit the key.

### 1.5 Plot — `/plot` (optional)

| Attribute | Type | Meaning |
|---|---|---|
| `spec` | JSON string | Default plot for this file, e.g. `{"kind": "heatmap", "values": ["S21"], "complex": "db"}`. |
| `style` | JSON string | Per-file style override, deep-merged on top of the selected style preset. |
| `style_name` | string | Name of a viewer style preset to use for this file. |
| `matplotlib` | string, optional | The matplotlib version that last wrote the saved view, e.g. `"3.11.2"`. Informational: the view may contain matplotlib calls (annotations), and this says which matplotlib they were written for. Writers that don't use matplotlib (MATLAB, Julia) keep the value they read. |

The meaning of the JSON keys is defined by the viewer, not by this spec. Readers must preserve them as opaque JSON.

### 1.6 Extra — `/extra` (optional)

Any additional HDF5 content. LBD readers ignore it. Use it for data that does not fit the axes/values model.

### 1.7 Measured — `/measured/<value name>` (optional)

Which points of an integer or boolean value were measured, for a value that was filled piece by
piece and not completely (a measurement stopped early). Floating-point and complex values use
`NaN` for "not measured" instead and have no mask.

- A `uint8` dataset with the same shape as `/values/<value name>`: `1` where the point was
  measured, `0` where it was not (the value holds `0` there, which means nothing).
- Writers omit the mask when every point was measured.
- Readers that don't know masks read the value as usual; LBD readers should hide the points
  whose mask is `0`.

### 1.8 Axis groups — `/axes/<group name>/` (since 2.0)

A sweep whose inner points depend on the outer ones (B chosen per A, a different number of B per
A, adaptive or re-centred sweeps, several such levels) is stored as an **axis group**: its axes'
measured points listed together, level by level. Only measured points are stored.

- A group in `/axes`, with attribute `order` (string, must): its axes, outer to inner,
  comma-separated (one or more).
- For each axis X in `order`, a dataset `X`: 1-D numeric, with `unit` and `label` as in §1.2
  (`elements` and `role` are not used on a group's axes; readers ignore them with a warning).
  It holds the coordinates of **level X**'s points:
  - level 1 (the first axis): each distinct coordinate once;
  - every further level: one entry per point of that level, and a dataset `X._parent` (1-D
    integer, same length): for each point, the index (from 0) of the point it belongs to in the
    level above.
- At each level, no two points have the same coordinate and the same parent (readers warn and
  keep both). Points are stored in the order they were first written: readers must not assume
  sorted coordinates or the points of one parent next to each other. A point may have no points
  below it (an (A, B) point with no C).
- Coordinates must not be `NaN` or infinite. A `_parent` index outside the level above, or a
  `_parent` whose length differs from its level's, is an error for readers.
- A value on level *k* (§1.3) has one entry per point of level *k*, in the level's order.

Reading a point: for point *j* of level C, its coordinate is `C[j]`; its (A, B) point is
`p = C._parent[j]`, with B = `B[p]`; its A is `A[B._parent[p]]`.

---

## 2. Dimension order

HDF5 stores N-D arrays in row-major (C) order. Some languages are row-major (Python/NumPy, C), others column-major (MATLAB, Julia, Fortran, R). To make the same logical array look the same in every language:

- The **logical order** of dimensions is the order in which they appear in the HDF5 dataspace (= NumPy `shape`).
- The `axes` attribute lists axes in logical order.
- **Row-major** implementations (e.g. Python) write and read arrays as-is.
- **Column-major** implementations (e.g. MATLAB, Julia) reverse the dimension order (`permutedims(A, ndims:-1:1)`) before writing, and reverse it back after reading.

Result: a 2-D value with `axes = "power,freq"`, 11 powers and 401 frequencies, is `(11, 401)` in Python, `11×401` in MATLAB and `11×401` in Julia, with `A[i, j]` / `A(i, j)` meaning power *i*, frequency *j* everywhere.

The same rule applies to numeric arrays stored in `/meta`. A level of an axis group (§1.3, §1.8)
is one dimension, like an axis; its `_parent` indices count from 0 in every language's file, and
implementations that count from 1 convert them when reading and writing.

---

## 3. Data types

| Logical type | HDF5 storage |
|---|---|
| float32 / float64 | IEEE little-endian float |
| int8 … int64, uint8 … uint64 | little-endian integers |
| complex64 / complex128 | compound `{ r: float32, i: float32 }` / `{ r: float64, i: float64 }`, members in that order. This is the native convention of h5py and HDF5.jl. |
| bool | `uint8` with values 0/1, and attribute `lbd_bool = 1` on the dataset. Readers convert back to boolean. |
| string | variable-length UTF-8. Readers must also accept fixed-length or ASCII strings. |

- Missing numeric values are `NaN` (floating point and complex); for integers and booleans, the
  `/measured` mask says which points are missing (§1.7).
- Values and axes must not be string datasets.

Writers choose the type automatically from the input ("auto"): the input's numeric type is kept, complex input becomes the complex compound type, and boolean input becomes `uint8` + `lbd_bool`. The user may force a specific type.

---

## 4. Names

- Axis and value names must match `^[A-Za-z][A-Za-z0-9_]{0,62}$`, so they are valid identifiers in common programming languages.
- Names are case-sensitive.
- The order of axes and values inside `/axes` and `/values` has no meaning. Most HDF5 libraries list them alphabetically. The dimension order of a value is defined only by its `axes` attribute.
- An axis and a value must not share a name. Since 2.0 the same holds for groups: fixed axes,
  groups, the axes in groups and values all have different names, and a group's name follows
  the same rule. The datasets `X._parent` contain a `.`, which no name may, so they can't clash.
- Meta keys should follow the same rule. Readers must accept any HDF5 attribute name in `/meta`.

---

## 5. Compression

Writers may store datasets chunked and gzip-compressed. Readers must handle this transparently, which all HDF5 libraries do.

---

## 6. Versioning and compatibility

- `lbd_version` is `"<major>.<minor>"`.
- A **minor** bump only adds optional content. A reader for `1.x` must read any `1.y` file, ignoring what it does not understand, and should warn when `y > x`.
- A **major** bump may break compatibility. A reader must refuse a file whose major version is newer than it supports, with an error telling the user to update.
- Readers must ignore unknown attributes, groups and datasets anywhere in the file.
- **Writers write the lowest version their content needs**: `"2.0"` only for a file with an axis
  group, `"1.2"` otherwise, so readers of 1.x keep reading every file without a group.
- A reader that supports 2.x reads every 1.x file. It warns for a minor version newer than it
  knows within that major (1.3 or later, 2.1 or later).
- Version history: **1.1** added the root `id` and `parent_id`; **1.2** added an axis's
  `elements` and `role`, data points with a shape (§1.2, §1.3), the `/measured` masks (§1.7)
  and files being written (§7); **2.0** added axis groups (§1.8, and dimensions on them in
  §1.3). Readers of 1.x refuse 2.0 files with "please update".

---

## 7. Files being written

A program may write a file while it measures, so that the data so far can be read at any time
and a crash loses at most the last moments. Such a file is not yet an LBD file; it becomes one
when complete.

- It is named `<name>.lbd.writing` and is written in HDF5's single-writer / multiple-reader
  (SWMR) mode, which needs the HDF5 1.10 file format. Writers use exactly that format (HDF5's
  library version bounds 1.10 to 1.10), not the newest their HDF5 knows, so every HDF5 since
  1.10 can read the file. When complete, the writer closes it and renames it to `<name>.lbd`;
  the content is not copied.
- While written: values may hold `NaN` (or a `0` mask, §1.7) where nothing was measured yet, and
  an axis whose length isn't known in advance (a log, "until stopped") may be shorter than it
  will be, together with the values on it. Every value on such an axis has it as its first axis.
- The levels of an axis group (§1.8) grow as points are measured, and every value on a level
  grows with it, along that dimension (wherever it is in the value's `axes`). Readers take each
  level as the points that are complete: up to the shortest of `X` and `X._parent`, and only up
  to the first point whose parent isn't there yet; each value is cut to its levels' lengths.
- **The guard.** For the whole time it writes, the writer holds an exclusive operating-system
  lock on one byte at offset 2^40 of the file (length 1; beyond any data, so no read is blocked).
  The lock disappears with the writing process, so it tells the two cases apart:
  held → **measuring**; not held → **stopped** (the writer crashed or was stopped before
  finishing). A stopped file holds everything written before the last flush and is made into
  an LBD file by copying its content into `<name>.lbd`.
- Readers open a `.lbd.writing` file in SWMR read mode with HDF5 file locking turned off, read
  what they need and close it again; they must not keep it open or write to it. When the writer
  finishes, it rewrites the description and metadata outside SWMR, just before the rename: a
  reader that fails to read the file then should read it again a moment later (or find it
  finished, renamed to `<name>.lbd`). Other programs
  opening it in the ordinary way are refused by HDF5 while it is written; this does not
  disturb the writer.

---

## 8. Minimal example (as seen by `h5dump`-style listing)

```
/                         lbd_format="LBD" lbd_version="1.2" title="Resonator power sweep"
                          description="" created="2026-10-13T16:09:00+08:00" writer="python lbd 1.3.0"
                          id="0199dc2a-4b7e-7f30-8a41-5c6d7e8f9a0b"
/axes/power   float64[11]       unit="dBm" label="Power"
/axes/freq    float64[401]      unit="Hz"  label="Frequency"
/values/S21   {r,i}float64[11,401]  unit="" label="S21" axes="power,freq"
/meta                     T_mK=12  sample="R7"
/meta/vna                 ifbw_Hz=1000.0 averages=4
/plot                     spec='{"kind":"heatmap","values":["S21"],"complex":"db"}'
```

A file with named positions and a vector per data point (format 1.2):

```
/axes/state         int64[2]     unit="" label="Prepared state" elements=["ground","excited"]
/axes/amp           float64[21]  unit="V" label="Drive"
/axes/bloch_dim1    int64[3]     unit="" label="bloch" role="point" elements=["x","y","z"]
/values/P1          float64[2,21]    unit="" label="P1" axes="state,amp"
/values/bloch       float64[21,3]    unit="" label="bloch" axes="amp,bloch_dim1"
```

A variable sweep (format 2.0): A from [1, 2, 3]; for each A, B in `0 … A−1`; for each (A, B), C in
`0 … B−1`; f measured once per (A, B) point, g once per (A, B, C) point:

```
/                   lbd_version="2.0" …
/axes/ABC/          order="A,B,C"
/axes/ABC/A         int64[3]   = [1, 2, 3]              ← level 1: each A once
/axes/ABC/B         int64[6]   = [0, 0, 1, 0, 1, 2]     ← level 2: each (A, B) point
/axes/ABC/B._parent int64[6]   = [0, 1, 1, 2, 2, 2]     ←   its A (index into level 1)
/axes/ABC/C         int64[4]   = [0, 0, 0, 1]           ← level 3: each (A, B, C) point
/axes/ABC/C._parent int64[4]   = [2, 4, 5, 5]           ←   its (A, B) point (index into level 2)
/values/f           float64[6]   axes="A,B"             ← level 2 (also the points with no C)
/values/g           float64[4]   axes="A,B,C"           ← level 3
```

`g[3]`: `C[3]` = 1, `C._parent[3]` = 5 → B = `B[5]` = 2, `B._parent[5]` = 2 → A = `A[2]` = 3: the
point (3, 2, 1); its f is `f[5]`.

A group together with a fixed axis and a data point of shape (2, 2) (format 2.0): B chosen per A,
a spectrum over a fixed `freq` at each (A, B) point, and a 2 × 2 matrix per point:

```
/axes/AB/           order="A,B"
/axes/AB/A          float64[3]   = [1, 2, 3]
/axes/AB/B          float64[6]   = [10, 10, 20, 15, 25, 35]
/axes/AB/B._parent  int64[6]     = [0, 1, 1, 2, 2, 2]
/axes/freq          float64[401]                        ← a fixed axis
/axes/cov_dim1      int64[2]     role="point" elements=["I","Q"]
/axes/cov_dim2      int64[2]     role="point" elements=["I","Q"]
/values/S           float64[6,401]   axes="A,B,freq"            ← (A, B) points × freq
/values/cov         float64[6,2,2]   axes="A,B,cov_dim1,cov_dim2"
```

<!-- --8<-- [end:body] -->
