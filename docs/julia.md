# Julia API reference — `LBD`

```julia
using LBD
```

Exported names are `Dataset`, `Axis`, `Value`, `add_axis!`, `add_value!`, `write!`,
`LBDError` and `LBDVersionError`, and for writing while measuring `Writer`, `lbd_writer`,
`writing_status` and `recover` (see
[Writing while measuring](getting-started/writing-while-measuring.md)). The file functions are called with the module prefix (`LBD.save`,
`LBD.load`, `LBD.info`, `LBD.version`), so they don't clash with other packages.

Requires Julia 1.9 or newer; it installs HDF5.jl, JSON3.jl and OrderedCollections.jl. To
install, see [Install → Julia](getting-started/install.md#julia).

## Quick example

```julia
using LBD

f = collect(range(4e9, 8e9, 401))
p = collect(-40.0:4:0)
s21 = exp.(1im .* (p * f') .* 1e-10)               # size (11, 401) = (power, freq)

d = LBD.Dataset("Resonator power sweep")
add_axis!(d, "power", p; unit="dBm", label="Power")
add_axis!(d, "freq", f; unit="Hz", label="Frequency")
add_value!(d, "S21", s21, ["power", "freq"])
d.meta["T_mK"] = 12
d.meta["vna"] = Dict("ifbw_Hz" => 1000.0, "averages" => 4)
LBD.save("sweep.lbd", d)

d = LBD.load("sweep.lbd")
size(d["S21"].data)     # (11, 401)
d["S21"].axes           # ["power", "freq"]
```

---

## `Dataset`

```julia
Dataset(title::AbstractString=""; description::AbstractString="", created=nothing)
```

A mutable struct with these fields:

| Field | Type | Meaning |
|---|---|---|
| `title` | `String` | Short title. Editable. |
| `description` | `String` | Free text. Editable. |
| `axes` | `OrderedDict{String,Axis}` | Axes by name. |
| `values` | `OrderedDict{String,Value}` | Values by name. |
| `meta` | `OrderedDict{String,Any}` | Free metadata. Nested dicts become groups. See [meta types](#meta-values). |
| `plot` | `Dict{String,Any}` or `nothing` | Default plot for the viewer: a [plot spec](styles/plot-settings.md). |
| `style` | `Dict{String,Any}` or `nothing` | Per-file [style](styles/index.md) changes. |
| `style_name` | `String` or `nothing` | Viewer style preset for this file. |
| `matplotlib` | `String` or `nothing` | matplotlib version that last wrote the saved view (set by Python and the viewer). Julia keeps it when saving. |
| `id` | `String` or `nothing` | The measurement's identity (a UUID, made at the first save; see `LBD.save`). Don't set it by hand; `new_id!(d)` makes a new one. |
| `parent_id` | `String` or `nothing` | The `id` of the file this one was made from. |
| `created` | `String`, `DateTime` or `nothing` | When the data was created, ISO-8601 with a UTC offset (`"2026-10-13T16:09:00+08:00"`). Editable: give it as such a text or a `DateTime` (taken in this computer's time zone); a text without an offset gets this computer's offset. `nothing`: `save` fills in the time of the first save. A loaded file keeps its `created`, and saving again keeps it. |
| `writer` | `String` or `nothing` | Program that wrote the file, e.g. `"julia LBD 1.0.0"`. |
| `lbd_version` | `String` | Format version of the file. |
| `path` | `String` or `nothing` | Last loaded or saved path. |

Indexing:

```julia
d["S21"]           # the Value named S21, or else the Axis with that name (KeyError if neither)
haskey(d, "S21")   # true if an axis or value has that name
```

## `add_axis!`

```julia
add_axis!(d, name, data=nothing; unit="", label=name, elements=nothing) -> Axis
```

Adds a 1-D axis.

| Argument | Meaning |
|---|---|
| `name` | Axis name ([naming rules](getting-started/concepts.md#names)). |
| `data` | A 1-D collection of real numbers. Ranges work and are `collect`ed. `Bool` is not allowed. |
| `unit` | Unit string. Prefer plain SI units. |
| `label` | Display text. |
| `elements` | A text for each position (format 1.2), e.g. `["ground", "excited"]`; `data` may then be left out (positions 0, 1, 2 …). |

**Throws** `LBDError` if the name is invalid or used, `data` isn't 1-D, `data` isn't real, or
`elements` don't fit the positions.

## `add_value!`

```julia
add_value!(d, name, data, axes=String[]; unit="", label=name, dtype=:auto, shape=(), elements=nothing) -> Value
```

Adds an N-D value.

| Argument | Meaning |
|---|---|
| `name` | Value name. |
| `data` | A numeric or `Bool` array, or a single number for a scalar value. |
| `axes` | One axis name per dimension: a vector (`["power", "freq"]`), a single name (`"freq"`), or a comma-separated string. Omit it for scalars. The axes must already exist. |
| `unit` | Unit string. |
| `label` | Display text. |
| `dtype` | `:auto` keeps the element type, or pass a type to force it: `Float32`, `Float64`, `Int8`…`Int64`, `UInt8`…`UInt64`, `ComplexF32`, `ComplexF64`, `Bool`. |
| `shape` | The shape of one data point (format 1.2): `(3,)` for a vector, `(2, 2)` for a matrix; `()`: one number. `data`'s dimensions are the value's axes first, then the data point's. |
| `elements` | A data point's position texts: one vector for a vector (`["x", "y", "z"]`), one per dimension for a matrix (`[["I", "Q"], nothing]`). |

`size(data)` must equal the axis lengths in order.

**Throws** `LBDError` if:
- the name is invalid or used,
- the number of axes or a size doesn't match,
- an axis doesn't exist,
- the element type is unsupported,
- the dtype would drop the imaginary part of complex data.

```julia
add_value!(d, "S21", s21, ["power", "freq"])
add_value!(d, "trace", v, "t"; unit="V")
add_value!(d, "mask", v .> 0.5, "t")            # Bool
add_value!(d, "raw", counts, "t"; dtype=Float32)
add_value!(d, "fit_Q", 12345.6)                 # scalar
add_axis!(d, "state"; elements=["ground", "excited"])                      # positions 0, 1
add_value!(d, "bloch", zeros(length(v), 3), "t"; shape=(3,), elements=["x", "y", "z"])
```

LBD makes one axis per dimension of a data point (`bloch_dim1`, `role == "point"`);
`v.point_axes`, `v.elements` and `LBD.point_shape(v)` describe it.

## `write!`

Fills a value made with `add_value!(d, name; axes=..., dtype=...)` (every point `NaN`, or 0 with
`measured` false for integers and `Bool`): a point, a trace, a map, or several values at once.
Indices count from 1; a position can also be one of an axis's elements.

```julia
using LBD

d = LBD.Dataset("Power sweep")
add_axis!(d, "power", collect(range(-60.0, 0, 7)); unit="dBm")
add_axis!(d, "freq", collect(range(6.99e9, 7.01e9, 201)); unit="Hz")
add_value!(d, "S21"; axes=["power", "freq"], dtype=ComplexF64)
add_value!(d, "n"; axes="power", dtype=Int32)
for i in 1:3
    write!(d; power=i, S21=ones(201), n=10i)          # a trace, and n at power i
end
println(d["n"].measured)                              # Bool[1, 1, 1, 0, 0, 0, 0]
LBD.save("sweep.lbd", d)
```

`add_axis!(d, "time"; grows=true)` makes an axis whose points `write!` adds
(`write!(d; time=t, T=x)`). Names that can't be keywords go in a `Dict`:
`write!(d, Dict("if" => 3); S21=z)`.

## `LBD.save`

```julia
LBD.save(path, d; compression=false) -> path
```

Writes the dataset. It also sets `d.writer` and `d.path`, and `d.created` if it was `nothing`
(the time of this first save); a `created` that is set is written unchanged.

It also sets the file's **id**: the measurement's identity, which LBD Viewer's Library uses to recognise
the same measurement in two places (a copy, a backup, a synced folder). It is made at the first
save (a UUID, from the time and random bits of the operating system: no setup, nothing to
coordinate between computers) and is read-only. Saving again to the same file keeps it;
saving to **another file** gives that file a new id, and the old one becomes its **parent
id** (a new measurement made from this one). A file copied by the file system keeps its id. `new_id!(d)` makes a loaded dataset a new
measurement on purpose.

- `compression=true` gzip-compresses arrays of 1024 elements or more. This is lossless.
- A path not ending in `.lbd` logs a warning.
- An existing file is replaced. The file is written under a temporary name and renamed, so a
  failed save leaves an existing file untouched.

**Throws** `LBDError` if:
- meta contains something that can't be stored,
- a value was loaded without its data.

## `LBD.load`

```julia
LBD.load(path; values=nothing) -> Dataset
```

Reads a file.

- `values`: a collection of value names whose data to read. The default `nothing` reads all.
- Values that aren't read keep `data == nothing`, but their `shape`, `dtype` and `axes` are
  filled in.

**Throws**:
- `LBDError` if the file isn't LBD or breaks the rules.
- `LBDVersionError` if the major format version is newer.
- `KeyError` if `values` names a missing value.

It logs a warning (`@warn`) if the minor format version is newer or the stored plot JSON is
invalid.

## `LBD.info`

```julia
LBD.info(path) -> Dataset
```

Reads everything except value data. It is the same as `LBD.load(path; values=String[])`.

## `LBD.version`

```julia
LBD.version()    # (package = "1.0.0", lbd_version = "1.0")
```

## `Axis` and `Value`

```julia
mutable struct Axis
    name::String; data::Vector; unit::String; label::String
end                                   # length(axis) = number of points

mutable struct Value
    name::String
    data::Any            # Array; a Number for scalars; `nothing` if not loaded
    axes::Vector{String}
    unit::String
    label::String
    shape::Tuple         # logical shape, also when not loaded
    dtype::String        # LBD type name, e.g. "complex128"
end
```

## Errors

| Exception | When |
|---|---|
| `LBDError` | Invalid names, shapes or types; not an LBD file; data that can't be stored. |
| `LBDVersionError` | The file's major format version is newer than supported. |

## Type conversion

### Values

| Julia | Stored as | Read back as |
|---|---|---|
| `Float64`, `Float32` | same | same |
| `Int8`…`Int64`, `UInt8`…`UInt64` | same | same |
| `ComplexF64`, `ComplexF32` | complex compound | same |
| `Bool` | bool | `Bool` |
| `Float16` | float32 | `Float32` |
| a single number (no axes) | scalar | the number itself (not a 0-d array) |

Arrays keep their shape across languages (see
[dimension order](getting-started/concepts.md#dimension-order-is-the-same-in-every-language)). You never need
to `permutedims` yourself.

### Meta values

| You put in `meta` | Stored as | Read back as |
|---|---|---|
| `String`, `Symbol` | UTF-8 text | `String` |
| `Int`, `Float64`, other reals | same type | same type |
| `Complex` | complex | `Complex` |
| `Bool` | Int64 0/1 | `Int64` |
| arrays of numbers (any dimensions) | array | `Array` of the same size |
| `Vector{String}` | text array | `Vector{String}` |
| `Tuple` | array | `Vector` |
| `AbstractDict`, `NamedTuple` | sub-group | `OrderedDict{String,Any}` |
| `nothing`, `missing` | refused at `save` | — |

## Recipes

### Add metadata to an existing file

```julia
d = LBD.load("sweep.lbd")
d.meta["note"] = "checked 2026-10-14"
LBD.save("sweep.lbd", d)
```

### Save the default plot and style

```julia
d.plot = Dict{String,Any}("kind" => "curve", "values" => ["trace"], "y_label" => "Signal")
d.style = Dict{String,Any}("figure" => Dict{String,Any}("width_mm" => 120, "height_mm" => 70))
d.style_name = "thesis"
LBD.save("run.lbd", d)
```

### Loop over measurements

```julia
for (k, T) in enumerate(temperatures)
    d = LBD.Dataset("Sweep at $T mK")
    add_axis!(d, "freq", f; unit="Hz", label="Frequency")
    add_value!(d, "S21", measure(T), "freq")
    d.meta["T_mK"] = T
    LBD.save(joinpath(out, "sweep_$(lpad(k, 3, '0')).lbd"), d; compression=true)
end
```
