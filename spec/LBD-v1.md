# LBD file format — version 1.2

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
├── axes/               (group)  one 1-D dataset per axis
│   └── <axis name>     attrs: unit, label
├── values/             (group)  one N-D dataset per value
│   └── <value name>    attrs: unit, label, axes [, lbd_bool]
├── meta/               (group)  free key/value metadata, stored as attributes; may contain sub-groups
├── plot/               (group, optional)  attrs: spec, style, style_name [, matplotlib]
└── extra/              (group, optional)  anything; ignored by LBD readers
```

### 1.1 Root attributes

| Attribute | Type | Required | Meaning |
|---|---|---|---|
| `lbd_format` | string, `"LBD"` | must | Identifies the file as LBD. |
| `lbd_version` | string, `"<major>.<minor>"` | must | Format version, `"1.2"` for this spec (`"1.0"` and `"1.1"` files are valid 1.2 files without the content added since). |
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

---

## 2. Dimension order

HDF5 stores N-D arrays in row-major (C) order. Some languages are row-major (Python/NumPy, C), others column-major (MATLAB, Julia, Fortran, R). To make the same logical array look the same in every language:

- The **logical order** of dimensions is the order in which they appear in the HDF5 dataspace (= NumPy `shape`).
- The `axes` attribute lists axes in logical order.
- **Row-major** implementations (e.g. Python) write and read arrays as-is.
- **Column-major** implementations (e.g. MATLAB, Julia) reverse the dimension order (`permutedims(A, ndims:-1:1)`) before writing, and reverse it back after reading.

Result: a 2-D value with `axes = "power,freq"`, 11 powers and 401 frequencies, is `(11, 401)` in Python, `11×401` in MATLAB and `11×401` in Julia, with `A[i, j]` / `A(i, j)` meaning power *i*, frequency *j* everywhere.

The same rule applies to numeric arrays stored in `/meta`.

---

## 3. Data types

| Logical type | HDF5 storage |
|---|---|
| float32 / float64 | IEEE little-endian float |
| int8 … int64, uint8 … uint64 | little-endian integers |
| complex64 / complex128 | compound `{ r: float32, i: float32 }` / `{ r: float64, i: float64 }`, members in that order. This is the native convention of h5py and HDF5.jl. |
| bool | `uint8` with values 0/1, and attribute `lbd_bool = 1` on the dataset. Readers convert back to boolean. |
| string | variable-length UTF-8. Readers must also accept fixed-length or ASCII strings. |

- Missing numeric values are `NaN` (floating point only).
- Values and axes must not be string datasets.

Writers choose the type automatically from the input ("auto"): the input's numeric type is kept, complex input becomes the complex compound type, and boolean input becomes `uint8` + `lbd_bool`. The user may force a specific type.

---

## 4. Names

- Axis and value names must match `^[A-Za-z][A-Za-z0-9_]{0,62}$`, so they are valid identifiers in common programming languages.
- Names are case-sensitive.
- The order of axes and values inside `/axes` and `/values` has no meaning. Most HDF5 libraries list them alphabetically. The dimension order of a value is defined only by its `axes` attribute.
- An axis and a value must not share a name.
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
- Version history: **1.1** added the root `id` and `parent_id`; **1.2** added an axis's
  `elements` and `role`, and data points with a shape (§1.2, §1.3).

---

## 7. Minimal example (as seen by `h5dump`-style listing)

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

<!-- --8<-- [end:body] -->
