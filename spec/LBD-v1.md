# LBD file format — version 1.0

LBD ("Lab Data", extension `.lbd`) is a file format for measurement and simulation data that can be written and read identically from Python, MATLAB and Julia, and viewed with the LBD viewer.

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
├── attrs               lbd_format, lbd_version, title, description, created, writer
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
| `lbd_version` | string, `"<major>.<minor>"` | must | Format version, `"1.0"` for this spec. |
| `title` | string | must (may be `""`) | Short human-readable title. |
| `description` | string | must (may be `""`) | Free text. |
| `created` | string, ISO-8601 with UTC offset | must | Time the file was written, e.g. `2026-10-13T16:09:00+08:00`. |
| `writer` | string | must | Writer and its version, e.g. `"python lbd 1.0.0"`, `"matlab lbd 1.0.0"`, `"julia LBD 1.0.0"`. |

### 1.2 Axes — `/axes/<name>`

- 1-D numeric dataset (real; integer or floating point).
- Attributes:
  - `unit`: string, must; `""` for dimensionless.
  - `label`: string, must; a human-readable name used on plot axes, e.g. `"Frequency"`. Defaults to the axis name.
- Axis values should be monotonic, but this is not enforced.

### 1.3 Values — `/values/<name>`

- N-D numeric dataset with N ≥ 0. A 0-D (scalar) value has no axes.
- Attributes:
  - `unit`: string, must.
  - `label`: string, must; defaults to the value name.
  - `axes`: string, must. The names of the axes along each dimension, **comma-separated, in logical order** (see §2), e.g. `"power,freq"`. It is `""` for a 0-D value.
  - `lbd_bool`: integer `1`, only for boolean data (see §3).
- For every dimension *i*: the axis named in position *i* must exist in `/axes`, and its length must equal the size of dimension *i*.

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

HDF5 stores N-D arrays in row-major (C) order. Python/NumPy is row-major, MATLAB and Julia are column-major. To make the same logical array look the same in all three languages:

- The **logical order** of dimensions is the order in which they appear in the HDF5 dataspace (= NumPy `shape`).
- The `axes` attribute lists axes in logical order.
- **Python** writes and reads arrays as-is.
- **MATLAB and Julia** writers reverse the dimension order (`permutedims(A, ndims:-1:1)`) before writing, and their readers reverse it back after reading.

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

- Axis and value names must match `^[A-Za-z][A-Za-z0-9_]{0,62}$`, so they are valid identifiers in all three languages.
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

---

## 7. Minimal example (as seen by `h5dump`-style listing)

```
/                         lbd_format="LBD" lbd_version="1.0" title="Resonator power sweep"
                          description="" created="2026-10-13T16:09:00+08:00" writer="python lbd 1.0.0"
/axes/power   float64[11]       unit="dBm" label="Power"
/axes/freq    float64[401]      unit="Hz"  label="Frequency"
/values/S21   {r,i}float64[11,401]  unit="" label="S21" axes="power,freq"
/meta                     T_mK=12  sample="R7"
/meta/vna                 ifbw_Hz=1000.0 averages=4
/plot                     spec='{"kind":"heatmap","values":["S21"],"complex":"db"}'
```

<!-- --8<-- [end:body] -->
