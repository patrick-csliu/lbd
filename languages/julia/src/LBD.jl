"""
    LBD

Read and write LBD (Lab Data, `.lbd`) files. See `spec/LBD-v1.md`.

```julia
using LBD
d = LBD.Dataset("Resonator power sweep")
add_axis!(d, "power", -40.0:4:0; unit="dBm", label="Power")
add_axis!(d, "freq", range(4e9, 8e9, 401); unit="Hz", label="Frequency")
add_value!(d, "S21", s21, ["power", "freq"])      # size(s21) == (11, 401)
add_value!(d, "S21b"; axes=["power", "freq"], dtype=ComplexF64)   # filled by write!
write!(d; power=3, S21b=trace)                    # a trace: power 3, every frequency
add_group!(d, "scan")                              # a variable sweep (format 2.0): B chosen per A
add_axis!(d, "A"; group="scan"); add_axis!(d, "B"; group="scan")
add_value!(d, "f"; axes=["A", "B"])               # one entry per (A, B) point
i = write!(d; A=3); write!(d; parent=i, B=[15, 25], f=[1.0, 2.0])
m = to_dense(d, "f")                              # the full rectangle, gaps NaN
d.meta["T_mK"] = 12
LBD.save("sweep.lbd", d)
d = LBD.load("sweep.lbd")
d["S21"].data
```
"""
module LBD

using Dates
using HDF5
using JSON3
using OrderedCollections: OrderedDict
using Random: RandomDevice

export Dataset, Axis, Value, Group, add_axis!, add_value!, add_group!, write!, new_id!, LBDError, LBDVersionError
export coords, rows, to_dense
export Writer, lbd_writer, writing_status, recover

const PACKAGE_VERSION = "1.3.0-dev"
const FORMAT_VERSION = "2.0"            # the newest format this module reads and writes
const GRID_VERSION = "1.2"              # what a file without an axis group is written as (spec §6)
const FORMAT_MAJOR = parse(Int, split(FORMAT_VERSION, ".")[1])
const LATEST_MINOR = Dict(1 => 2, 2 => 0)   # the newest minor version known, per major version
const NAME_RE = r"^[A-Za-z][A-Za-z0-9_]{0,62}$"
const COMPRESS_MIN_SIZE = 1024
const REPLACE_WAIT = 3.0   # seconds `save` waits for a file another program has open (Windows)

# Element types allowed in values, with the names used across all LBD implementations.
const DTYPE_NAMES = Dict{DataType,String}(
    Float32 => "float32", Float64 => "float64",
    Int8 => "int8", Int16 => "int16", Int32 => "int32", Int64 => "int64",
    UInt8 => "uint8", UInt16 => "uint16", UInt32 => "uint32", UInt64 => "uint64",
    ComplexF32 => "complex64", ComplexF64 => "complex128",
    Bool => "bool",
)

struct LBDError <: Exception
    msg::String
end
struct LBDVersionError <: Exception
    msg::String
end
Base.showerror(io::IO, e::LBDError) = print(io, "LBDError: ", e.msg)
Base.showerror(io::IO, e::LBDVersionError) = print(io, "LBDVersionError: ", e.msg)

"""Package version and the LBD format version it reads and writes."""
version() = (package=PACKAGE_VERSION, lbd_version=FORMAT_VERSION)

mutable struct Axis
    name::String
    data::Vector
    unit::String
    label::String
    elements::Union{Vector{String},Nothing}   # a text per position (format 1.2), or nothing: numbered
    role::Union{String,Nothing}               # "point" only in a file (a data point's dimension); nothing here
    grows::Bool                               # write! adds its points (add_axis!(...; grows=true)); not stored
    group::Union{String,Nothing}              # the axis group it is in (format 2.0), nothing for a fixed axis
    # for an axis of a group below its first: for each point, the index (from 1) of its point in the
    # level above; nothing otherwise
    parent::Union{Vector{Int},Nothing}
end
Axis(name, data, unit, label) = Axis(name, data, unit, label, nothing, nothing, false, nothing, nothing)
Axis(name, data, unit, label, elements, role) = Axis(name, data, unit, label, elements, role, false, nothing, nothing)
Axis(name, data, unit, label, elements, role, grows) = Axis(name, data, unit, label, elements, role, grows, nothing, nothing)
Base.length(a::Axis) = length(a.data)

"""An axis group (format 2.0): axes whose points are listed together, outer to inner (`order`),
for a sweep whose inner points depend on the outer ones. Only measured points are stored."""
mutable struct Group
    name::String
    order::Vector{String}
end

mutable struct Value
    name::String
    data::Any                 # Array, a Number for 0-D values, or `nothing` if not loaded
    axes::Vector{String}      # what was swept: the sweep axes it depends on, outer to inner
    dims::Vector{Tuple}       # how the sweep part is stored: ("A",) a fixed axis, ("A", "B") a group's level
    unit::String
    label::String
    shape::Tuple              # logical shape (the dims' lengths, then point_shape), kept when data isn't loaded
    dtype::String
    point_shape::Tuple        # the shape of one data point: () one number, (3,) a vector (format 1.2)
    elements::Vector{Any}     # per data-point dimension: its texts (Vector{String}) or nothing
    # For an integer or Bool value filled by write!: true where something was written; nothing
    # for every other value (NaN means "not measured")
    measured::Any
end
Value(name, data, axes, unit, label, shape, dtype) =
    Value(name, data, axes, Tuple[(a,) for a in axes], unit, label, shape, dtype, (), Any[], nothing)

"""The shape of one data point of `v`: `()` for one number, `(3,)` for a vector of 3 …"""
point_shape(v::Value) = v.point_shape

"The file's names for the dimensions of `v`'s data points (axes with role \"point\")."
point_names(v::Value) = ["$(v.name)_dim$k" for k in 1:length(v.point_shape)]

mutable struct Dataset
    title::String
    description::String
    created::Union{String,DateTime,Nothing}   # when the data was created; filled at the first save if nothing
    writer::Union{String,Nothing}
    lbd_version::String
    axes::OrderedDict{String,Axis}
    groups::OrderedDict{String,Group}
    values::OrderedDict{String,Value}
    meta::OrderedDict{String,Any}
    plot::Union{Dict{String,Any},Nothing}
    style::Union{Dict{String,Any},Nothing}
    style_name::Union{String,Nothing}
    matplotlib::Union{String,Nothing}   # matplotlib version that last wrote the saved view (kept as is)
    # The measurement's identity (a UUID version 7) and the one it was made from; set by `save`
    # and `new_id!`, not by hand: see `save`.
    id::Union{String,Nothing}
    parent_id::Union{String,Nothing}
    path::Union{String,Nothing}
    live::Bool                     # LBD.Writer: values without data take no memory
    placeholders::Vector{String}   # ... and these are they (their data is in the file)
    lookups::Dict{String,Any}      # each group level's points by (parent, coordinate)
end

Dataset(title::AbstractString=""; description::AbstractString="", created=nothing) = Dataset(
    String(title), String(description), created === nothing ? nothing : created_text(created), nothing, GRID_VERSION,
    OrderedDict{String,Axis}(), OrderedDict{String,Group}(), OrderedDict{String,Value}(), OrderedDict{String,Any}(),
    nothing, nothing, nothing, nothing, nothing, nothing, nothing, false, String[], Dict{String,Any}(),
)

# ---- the measurement's identity ----------------------------------------------

const UUID_RE = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"

"""
    uuid7() -> String

A new UUID version 7 (RFC 9562), lower case: the Unix time in milliseconds (48 bits), then 74
random bits. The random bits come from the operating system (`RandomDevice`), never from
Julia's default generator, so `Random.seed!` in a simulation can't make two files share an id.
"""
function uuid7()
    ms = UInt64(floor(Int, Dates.datetime2unix(Dates.now(Dates.UTC)) * 1000))
    r = rand(RandomDevice(), UInt8, 10)
    b = Vector{UInt8}(undef, 16)
    for i in 1:6
        b[i] = UInt8((ms >> (8 * (6 - i))) & 0xff)
    end
    b[7] = 0x70 | (r[1] & 0x0f)          # version 7
    b[8] = r[2]
    b[9] = 0x80 | (r[3] & 0x3f)          # variant 10
    b[10:16] = r[4:10]
    h = bytes2hex(b)
    return string(h[1:8], "-", h[9:12], "-", h[13:16], "-", h[17:20], "-", h[21:32])
end

"""
    new_id!(d)

Make `d` a separate measurement: it gets a new id, and its old id becomes `parent_id`. Use it
before saving a loaded file as something new at the same place; saving to another file does
this by itself.
"""
function new_id!(d::Dataset)
    d.id === nothing || (d.parent_id = d.id)
    d.id = uuid7()
    return d
end

# Whether `a` and `b` name the same file (the same place once resolved; case doesn't matter on Windows).
function same_file(a::AbstractString, b::AbstractString)
    norm(p) = (q = abspath(isfile(p) || islink(p) ? realpath(p) : p); Sys.iswindows() ? lowercase(q) : q)
    return norm(a) == norm(b)
end

function Base.getindex(d::Dataset, name::AbstractString)
    haskey(d.values, name) && return d.values[name]
    haskey(d.axes, name) && return d.axes[name]
    throw(KeyError(name))
end
Base.haskey(d::Dataset, name::AbstractString) = haskey(d.values, name) || haskey(d.axes, name)

function Base.show(io::IO, ::MIME"text/plain", d::Dataset)
    println(io, "LBD.Dataset \"", d.title, "\"")
    for g in values(d.groups)
        println(io, "  group ", g.name, ": ", join(g.order, " → "))
    end
    for a in values(d.axes)
        println(io, "  axis  ", a.name, "[", length(a), "] ", a.unit)
    end
    for v in values(d.values)
        println(io, "  value ", v.name, "(", join(v.axes, ","), ") ", v.dtype, " ", v.unit)
    end
end

# ---- building ---------------------------------------------------------------

function check_new_name(d::Dataset, name::AbstractString)
    occursin(NAME_RE, name) || throw(LBDError(
        "invalid name \"$name\": must start with a letter and contain only letters, digits and '_' (max 63)"))
    (haskey(d, name) || haskey(d.groups, name)) && throw(LBDError("name \"$name\" is already used by an axis, group or value"))
    for v in values(d.values)
        name in point_names(v) && throw(LBDError("name \"$name\" is used in the file for a dimension of the data points of \"$(v.name)\""))
    end
end

"""
    add_group!(d, name)

Add an axis group (format 2.0): a sweep whose inner points depend on the outer ones (B chosen
per A, a different number of B per A, adaptive points). Add its axes next, outer to inner, with
`add_axis!(d, name; group=...)`; `write!` adds their points by coordinate, and only measured
points are stored. LBD older than 1.3 can't read such a file: use fixed axes when every
combination is planned.
"""
function add_group!(d::Dataset, name::AbstractString)
    check_new_name(d, name)
    g = Group(String(name), String[])
    d.groups[g.name] = g
    return g
end

"""
    add_axis!(d, name, data=nothing; unit="", label=name, elements=nothing, grows=false)

Add a 1-D real axis. `elements`: a text for each position (e.g. `["ground", "excited"]`);
`data` may then be left out (the positions are numbered 0, 1, 2 …). `grows=true`: an axis of
unknown length (a log, "until I stop it"), given no data; `write!` adds its points. It must be
the first axis of the values on it. `group="scan"`: an axis of that axis group (`add_group!`),
after its axes added so far; given no data, `write!` adds its points by coordinate.
"""
function add_axis!(d::Dataset, name::AbstractString, data=nothing; unit::AbstractString="",
                   label::AbstractString=name, elements=nothing, grows::Bool=false, group=nothing)
    check_new_name(d, name)
    if group !== nothing
        g = String(group)
        haskey(d.groups, g) || throw(LBDError("axis \"$name\": there is no group \"$g\"; add it first with add_group!(d, \"$g\")"))
        (data === nothing && elements === nothing && !grows) || throw(LBDError(
            "axis \"$name\" is in group \"$g\": give no data, elements or grows; write! adds its points by coordinate"))
        a = Axis(String(name), Float64[], String(unit), String(label), nothing, nothing, false, g,
                 isempty(d.groups[g].order) ? nothing : Int[])
        push!(d.groups[g].order, a.name)
        d.axes[a.name] = a
        return a
    end
    if grows
        (data === nothing && elements === nothing) ||
            throw(LBDError("axis \"$name\" grows: give no data or elements; write! adds its points"))
        a = Axis(String(name), Float64[], String(unit), String(label), nothing, nothing, true)
        d.axes[a.name] = a
        return a
    end
    if data === nothing
        elements === nothing && throw(LBDError("axis \"$name\" needs its coordinates (data) or its elements"))
        data = collect(0:length(check_elements(elements, nothing, "axis \"$name\"")) - 1)
    end
    arr = collect(data)
    ndims(arr) == 1 || throw(LBDError("axis \"$name\" must be 1-D, got size $(size(arr))"))
    T = eltype(arr)
    (T <: Real && !(T <: Bool)) || throw(LBDError("axis \"$name\" must be real numeric, got $T"))
    arr = normalize_eltype(arr)
    haskey(DTYPE_NAMES, eltype(arr)) || throw(LBDError("axis \"$name\": unsupported element type $(eltype(arr))"))
    el = elements === nothing ? nothing : check_elements(elements, length(arr), "axis \"$name\"")
    a = Axis(String(name), arr, String(unit), String(label), el, nothing)
    d.axes[a.name] = a
    return a
end

# A vector of texts, one per position (n of them, unless n is nothing).
function check_elements(elements, n, where)
    (elements isa AbstractString || !(elements isa Union{AbstractVector,Tuple})) &&
        throw(LBDError("$where: elements must be a list of texts, one per position"))
    all(e -> e isa AbstractString, elements) || throw(LBDError("$where: elements must be texts"))
    isempty(elements) && throw(LBDError("$where: elements is empty; give one text per position"))
    n === nothing || length(elements) == n ||
        throw(LBDError("$where: $(length(elements)) elements for $n positions; give one text per position"))
    return String[String(e) for e in elements]
end

"""
    add_value!(d, name, data, axes=String[]; unit="", label=name, dtype=:auto, shape=(), elements=nothing)
    add_value!(d, name; axes=String[], dtype=Float64, ...)

Add an N-D value. `axes` lists the axes it depends on, outer to inner (or a single name /
comma-separated string): a fixed axis is one dimension; axes of a group are one dimension
together, the points of their level (`["A", "B"]` of a group A → B → C; the group's name means
all of them). `size(data)` must match the axis (level) lengths. `dtype=:auto` keeps the element type;
pass e.g. `Float32` to force one.

Each data point is one number unless `shape` says otherwise (format 1.2): `shape=(3,)` for a
vector of 3, `(2, 2)` for a matrix; `data`'s dimensions are then the value's axes first, then
the data point's. `elements` names a data point's positions: one list (`["u", "v", "w"]`), or one
per dimension (`[["I", "Q"], nothing]`).

Without data (`nothing`, or the second form) the value is filled later by `write!`: every point
starts as `NaN` (not measured yet), or for integers and `Bool` as 0 with `measured` false.
"""
add_value!(d::Dataset, name::AbstractString; axes=String[], kw...) = add_value!(d, name, nothing, axes; kw...)

function add_value!(d::Dataset, name::AbstractString, data, axes=String[];
                    unit::AbstractString="", label::AbstractString=name, dtype=:auto,
                    shape=(), elements=nothing)
    check_new_name(d, name)
    dims = parse_dims(d, axes_list(axes), "value \"$name\"")
    axl = String[a for dm in dims for a in dm]
    point = check_shape(shape, name)
    measured = nothing
    placeholder = false
    if data === nothing                 # filled later by write!: "not measured yet"
        T = dtype === :auto ? Float64 : dtype
        (T isa DataType && haskey(DTYPE_NAMES, T)) || throw(LBDError(
            "value \"$name\": unsupported dtype $dtype; allowed: $(sort(collect(values(DTYPE_NAMES)))) or :auto"))
        full = (Tuple(dim_length(d, dm) for dm in dims)..., point...)
        if d.live                        # LBD.Writer: the data lives in the file
            arr = Array{T}(undef, ntuple(_ -> 0, length(full)))
            placeholder = true
        else
            arr = isempty(full) ? not_measured(T) : fill(not_measured(T), full)
            T <: AbstractFloat || T <: Complex || (measured = isempty(full) ? false : falses(full))
        end
        data = arr
        dtype = :auto
    end
    arr = coerce_value(data, dtype, name)
    nd = arr isa Number ? 0 : ndims(arr)
    ndim = length(dims)
    if ndim + length(point) != nd
        if ndim < nd && isempty(point)
            throw(LBDError("value \"$name\" has $nd dimension(s) but $ndim were given: $axl; " *
                           "if each data point holds several numbers, say so with shape=$(size(arr)[ndim+1:end])"))
        end
        throw(LBDError("value \"$name\" has $nd dimension(s), but its axes $axl and shape=$point make " *
                       "$(ndim + length(point))"))
    end
    growing = [ax for ax in axl if haskey(d.axes, ax) && d.axes[ax].grows]
    (length(growing) > 1 || (!isempty(growing) && axl[1] != growing[1])) && throw(LBDError(
        "value \"$name\": a growing axis must be its first axis, and only one (here $axl)"))
    for (i, dm) in enumerate(dims)
        n = dim_length(d, dm)
        if !placeholder && n != size(arr, i)
            hint = !isempty(point) && size(arr)[end-length(point)+1:end] != point ?
                "; the value's axes come first, then the data point (e.g. use permutedims)" : ""
            what = is_group_dim(d, dm) ? "the level $(join(dm, ",")) of group \"$(d.axes[dm[1]].group)\" has $n points" :
                "axis \"$(dm[1])\" has length $n"
            throw(LBDError("value \"$name\": dimension $i has size $(size(arr, i)) but $what$hint"))
        end
    end
    if !placeholder && !isempty(point) && size(arr)[ndim+1:end] != point
        throw(LBDError("value \"$name\": its data points have shape $(size(arr)[ndim+1:end]), not shape=$point"))
    end
    named = value_elements(elements, point, name)
    for pn in ["$(name)_dim$k" for k in 1:length(point)]
        (haskey(d, pn) || haskey(d.groups, pn)) && throw(LBDError("value \"$name\" needs the name \"$pn\" for a " *
            "dimension of its data points in the file, but it is already used; rename that axis or value"))
    end
    vshape = placeholder ? (Tuple(dim_length(d, dm) for dm in dims)..., point...) : arr isa Number ? () : size(arr)
    T = arr isa Number ? typeof(arr) : eltype(arr)
    v = Value(String(name), arr, axl, Tuple[Tuple(dm) for dm in dims], String(unit), String(label), vshape,
              DTYPE_NAMES[T], Tuple(point), named, measured)
    d.values[v.name] = v
    placeholder && push!(d.placeholders, v.name)
    return v
end

# "Not measured" for an element type: NaN, or zero for integers and Bool (with a mask).
not_measured(::Type{T}) where {T<:AbstractFloat} = T(NaN)
not_measured(::Type{T}) where {T<:Complex} = T(NaN, NaN)
not_measured(::Type{T}) where {T} = zero(T)

# ---- filling values: write! -----------------------------------------------------

"""
    write!(d; names...)
    write!(d, Dict("if" => 3); names...)

Put measured data into values made by `add_value!` without data: a point, a trace, a whole map,
or several values at once, at the place the axes say.

- a fixed axis: an index (`power=3`, 1 = its first point), or one of its elements (`state="excited"`);
- a growing axis (`add_axis!(...; grows=true)`): its coordinate, or a vector of them, adding as
  many points;
- an axis of a group (`add_axis!(...; group=...)`): its coordinate, or a vector of them for
  several points; the group's axes outer first (`A=3, B=25`). The same coordinates are the same
  point (found, or added); compared exactly, with a warning for a new point that differs from
  one there only by rounding;
- a value: its data, sized as the value's dimensions that weren't given (and its data point,
  always whole), in order.

`parent=`: instead of the outer coordinates, the index of the outer point, as an earlier
`write!` returned it. Names that can't be keywords go in the `Dict` (also a value called
`parent`). Writing again to the same place replaces the data. Returns the index (from 1) of the
group's point at the deepest level given (a vector for several points); a `Dict` by group name
for several groups; `nothing` without a group.

```julia
write!(d; power=3, S21=trace)               # a trace
write!(d; power=3, freq=7, S21=z, T=t)      # a point, and T at power 3
write!(d; time=12.5, T=4.2)                 # a growing axis: adds a point
i = write!(d; A=3)                          # a group's point, then under it:
write!(d; parent=i, B=[15, 25], f=[1.0, 2.0])
```
"""
function write!(d::Dataset, names::AbstractDict=Dict{String,Any}(); parent=nothing, kw...)
    plan = plan_write(d, names, kw, parent)
    apply_write!(d, plan)
    return plan.result
end

function plan_write(d::Dataset, names::AbstractDict, kw, parent=nothing)
    given = OrderedDict{String,Any}(String(k) => v for (k, v) in names)
    for (k, v) in kw
        haskey(given, String(k)) && throw(LBDError("write!: \"$k\" is given twice"))
        given[String(k)] = v
    end
    unknown = [k for k in keys(given) if !haskey(d, k)]
    isempty(unknown) || throw(LBDError("write!: no axis or value named $unknown; axes: $(collect(keys(d.axes))), " *
                                       "values: $(collect(keys(d.values)))"))
    vals = [k for k in keys(given) if haskey(d.values, k)]
    positions = [k for k in keys(given) if haskey(d.axes, k)]
    in_groups = [a for a in positions if d.axes[a].group !== nothing]
    isempty(vals) && isempty(in_groups) &&
        throw(LBDError("write!: give at least one value with its data, e.g. write!(d; power=3, S21=trace)"))
    parent !== nothing && isempty(in_groups) && throw(LBDError(
        "write!: parent= names an outer point of a group; give the next axes of that group with it, e.g. write!(d; parent=i, B=25, f=x)"))
    points = isempty(in_groups) ? Dict{String,Any}() : plan_points(d, in_groups, given, parent)
    grow = nothing
    index = Dict{String,Int}()
    for a in positions
        d.axes[a].group === nothing || continue
        if d.axes[a].grows
            grow === nothing || throw(LBDError("write!: one growing axis at a time, not $(grow.axis) and $a"))
            c = given[a]
            ok = (c isa Real && !(c isa Bool) && isfinite(c)) ||
                 (c isa AbstractVector && eltype(c) <: Real && !(eltype(c) <: Bool) && all(isfinite, c))
            ok || throw(LBDError("write!: \"$a\" takes a coordinate or a vector of them, finite numbers"))
            grow = (axis=a, coords=Float64.(c isa Real ? [c] : collect(c)), scalar=c isa Real)
        else
            index[a] = position(d, a, given[a])
        end
    end
    puts = []
    for name in vals
        v = d.values[name]
        for a in positions
            a in v.axes || throw(LBDError("write!: \"$name\" doesn't lie on \"$a\" (its axes: $(v.axes))"))
        end
        idx = Any[]
        need = Int[]
        free = String[]
        for dm in v.dims
            a = dm[1]
            ax = d.axes[a]
            if is_group_dim(d, dm)
                p = get(points, ax.group, nothing)
                if p === nothing                    # every point of the level
                    push!(idx, Colon())
                    push!(need, dim_length(d, dm)); push!(free, join(dm, ","))
                    continue
                end
                p.depth == dm[end] || throw(LBDError("write!: \"$name\" lies on the points of $(join(dm, ", ")): " *
                    "give $(collect(dm[findfirst(==(p.depth), dm)+1:end])) too"))
                push!(idx, p.index)
                p.n === nothing || (push!(need, p.n); push!(free, join(dm, ",")))
            elseif ax.grows
                (grow !== nothing && grow.axis == a) || throw(LBDError(
                    "write!: \"$name\" lies on the growing axis \"$a\": give its coordinate ($a=…), which adds a point"))
                start = length(ax.data)
                if grow.scalar
                    push!(idx, start + 1)
                else
                    push!(idx, start .+ (1:length(grow.coords)))
                    push!(need, length(grow.coords)); push!(free, a)
                end
            elseif haskey(index, a)
                push!(idx, index[a])
            else
                push!(idx, Colon())
                push!(need, length(ax.data)); push!(free, a)
            end
        end
        for (k, n) in enumerate(v.point_shape)       # a data point is always given whole
            push!(idx, Colon()); push!(need, n); push!(free, "data point dimension $k")
        end
        x = fits_type(given[name], v.dtype, name)
        x = shaped_for(x, need, name, free)
        push!(puts, (name=name, idx=idx, data=x))
    end
    levels = [l for p in values(points) for l in p.new]
    result = length(points) == 1 ? first(values(points)).index :
        isempty(points) ? nothing : Dict(g => p.index for (g, p) in points)
    return (grow=grow, levels=levels, puts=puts, result=result)
end

# ---- axis groups (format 2.0, spec §1.8) ------------------------------------------------

# A value's dimensions from its axis names: a fixed axis is one dimension; consecutive axes of
# one group, from its first, are one (a level); a group's name means all its axes.
function parse_dims(d::Dataset, names, where)
    dims = Vector{Vector{String}}()
    seen = String[]
    i = 1
    while i <= length(names)
        name = names[i]
        if haskey(d.groups, name)
            order = d.groups[name].order
            isempty(order) && throw(LBDError("$where: group \"$name\" has no axes yet; add them with add_axis!(d, name; group=\"$name\")"))
            dm, owner = copy(order), name
            i += 1
        elseif haskey(d.axes, name) && d.axes[name].group !== nothing
            owner = d.axes[name].group
            order = d.groups[owner].order
            if name != order[1]
                k = findfirst(==(name), order)
                throw(LBDError("$where: \"$name\" is an inner axis of group \"$owner\" (order $order); a value lies on " *
                               "an outer part of a group: give $(order[1:k]), not \"$name\" alone"))
            end
            k = 1
            while i + k <= length(names) && k < length(order) && names[i+k] == order[k+1]
                k += 1
            end
            i + k <= length(names) && names[i+k] in order && throw(LBDError(
                "$where: the axes of group \"$owner\" must be given in its order $order, one after the other from \"$(order[1])\""))
            dm = order[1:k]
            i += k
        else
            haskey(d.axes, name) || throw(LBDError("$where: axis \"$name\" does not exist; add it with add_axis! first"))
            dm, owner = [name], name
            i += 1
        end
        owner in seen && throw(LBDError("$where: \"$owner\" appears more than once in $names"))
        push!(seen, owner)
        push!(dims, dm)
    end
    return dims
end

dim_length(d::Dataset, dm) = length(d.axes[dm[end]].data)
is_group_dim(d::Dataset, dm) = d.axes[dm[1]].group !== nothing

# For each point of the level `dm` ends at, its point at every level of `dm` (outer first).
function ancestors(d::Dataset, dm)
    idx = collect(1:dim_length(d, dm))
    out = Vector{Vector{Int}}(undef, length(dm))
    out[end] = idx
    for m in length(dm):-1:2
        idx = d.axes[dm[m]].parent[idx]
        out[m-1] = idx
    end
    return out
end

# Level `a`'s points by (parent, coordinate); rebuilt when the level changed by hand.
function lookup(d::Dataset, a)
    ax = d.axes[a]
    lk = get(d.lookups, a, nothing)
    if lk === nothing || lk.n[] != length(ax.data)
        map = Dict{Tuple{Int,Float64},Int}()
        parents = ax.parent === nothing ? zeros(Int, length(ax.data)) : ax.parent
        for i in length(ax.data):-1:1        # the first of two equal points wins
            map[(parents[i], Float64(ax.data[i]) + 0.0)] = i
        end
        lk = (n=Ref(length(ax.data)), map=map)
        d.lookups[a] = lk
    end
    return lk
end

# The points a write names in each group: found by their coordinates, or new. Nothing is changed.
function plan_points(d::Dataset, names, given, parent)
    by_group = OrderedDict{String,Vector{String}}()
    for a in names
        push!(get!(by_group, d.axes[a].group, String[]), a)
    end
    parent !== nothing && length(by_group) != 1 && throw(LBDError(
        "write!: parent= names a point of one group; give the axes of that group (and only one group) with it"))
    plans = Dict{String,Any}()
    for (g, gnames) in by_group
        order = d.groups[g].order
        ks = sort([findfirst(==(a), order) for a in gnames])
        s, e = ks[1], ks[end]
        ks == collect(s:e) || throw(LBDError("write!: group \"$g\" (order $order) needs its axes one after the other; " *
                                             "$(setdiff(order[s:e], gnames)) missing"))
        parent === nothing && s > 1 && throw(LBDError("write!: \"$(order[s])\" means something only under " *
            "$(order[1:s-1]): give $(join(order[1:s-1], ", ")) too, or the outer point with parent="))
        parent !== nothing && s == 1 && throw(LBDError("write!: parent= names a point of the level above \"$(order[1])\", " *
            "which is the first axis of group \"$g\"; leave parent= out"))
        cols = Any[]
        lens = Int[]
        for m in s:e
            c = given[order[m]]
            ok = (c isa Real && !(c isa Bool)) || (c isa AbstractVector && eltype(c) <: Real && !(eltype(c) <: Bool))
            ok || throw(LBDError("write!: \"$(order[m])\" is an axis of a group: give its coordinate (a number) or a vector of them"))
            all(isfinite, c) || throw(LBDError("write!: \"$(order[m])\" got NaN or Inf; coordinates must be finite numbers"))
            c isa AbstractVector && push!(lens, length(c))
            push!(cols, c)
        end
        pars = nothing
        if parent !== nothing
            n_above = length(d.axes[order[s-1]].data)
            ok = (parent isa Integer && !(parent isa Bool)) || (parent isa AbstractVector && eltype(parent) <: Integer)
            ok || throw(LBDError("write!: parent= takes the index (or a vector of indices) that write! returned"))
            all(p -> 1 <= p <= n_above, parent) || throw(LBDError(
                "write!: parent=$parent is not a point of \"$(order[s-1])\" (it has $n_above: 1 … $n_above)"))
            parent isa AbstractVector && push!(lens, length(parent))
            pars = parent
        end
        length(unique(lens)) > 1 && throw(LBDError("write!: the coordinates given for group \"$g\" have different lengths $(unique(lens))"))
        many = !isempty(lens)
        n = many ? lens[1] : 1
        expand(x) = x isa AbstractVector ? collect(x) : fill(x, n)
        cols = [expand(c) for c in cols]
        pars = pars === nothing ? zeros(Int, n) : expand(pars)
        newc = [Float64[] for _ in cols]
        newp = [Int[] for _ in cols]
        pending = Dict{Tuple{Int,Int,Float64},Int}()
        result = zeros(Int, n)
        for i in 1:n
            p = Int(pars[i])
            for m in eachindex(cols)
                a = order[s+m-1]
                c = Float64(cols[m][i]) + 0.0           # +0.0: -0.0 is the point 0
                idx = get(pending, (m, p, c), nothing)
                idx === nothing && (idx = get(lookup(d, a).map, (p, c), nothing))
                if idx === nothing
                    idx = length(d.axes[a].data) + length(newc[m]) + 1
                    push!(newc[m], c); push!(newp[m], p)
                    pending[(m, p, c)] = idx
                end
                p = idx
            end
            result[i] = p
        end
        new = [(order[s+m-1], newc[m], d.axes[order[s+m-1]].parent === nothing ? nothing : newp[m])
               for m in eachindex(cols) if !isempty(newc[m])]
        plans[g] = (depth=order[e], index=many ? result : result[1], n=many ? n : nothing, new=new)
    end
    count(p -> p.n !== nothing, values(plans)) > 1 &&
        throw(LBDError("write!: give several points of one group at a time (one point of each other group)"))
    return plans
end

# Add a write's new group points to their levels (coordinates, parents, lookups); warn about a
# new point that differs from one there only by rounding.
function grow_levels!(d::Dataset, plan)
    near = String[]
    for (a, c, p) in plan.levels
        ax = d.axes[a]
        start = length(ax.data)
        lk = get(d.lookups, a, nothing)
        valid = lk !== nothing && lk.n[] == start
        all_c = vcat(Float64.(ax.data), c)
        if any(x -> x != round(x), all_c)               # integers are never near-equal
            scale = max(maximum(all_c) - minimum(all_c), abs(minimum(all_c)), abs(maximum(all_c)))
            parents = p === nothing ? zeros(Int, length(c)) : p
            old = ax.parent === nothing ? zeros(Int, start) : ax.parent
            for q in unique(parents)
                u = sort(unique(vcat(Float64.(ax.data[old .== q]), c[parents .== q])))
                k = findfirst(<=(1e-9 * scale), diff(u))
                k === nothing || push!(near, "$a = $(repr(u[k+1])) is a new point next to $(repr(u[k]))")
            end
        end
        ax.data = eltype(ax.data) <: Integer && all(x -> x == round(x), c) ? vcat(ax.data, Int.(c)) : all_c
        p === nothing || (ax.parent = vcat(ax.parent, p))
        if valid
            pp = p === nothing ? zeros(Int, length(c)) : p
            for i in eachindex(c)
                get!(lk.map, (pp[i], c[i]), start + i)
            end
            lk.n[] = start + length(c)
        end
    end
    isempty(near) || @warn "write!: $(join(near[1:min(3, end)], "; ")). Coordinates are compared exactly: round " *
        "the coordinate, or write with parent= (the index write! returned)"
end

# `k` points were added to `axis` (a growing axis, or a group's level): every value on it grows
# along that dimension, the new points not measured.
function extend_values!(d::Dataset, axis, k)
    for v in values(d.values)
        for (pos, dm) in enumerate(v.dims)
            dm[end] == axis || continue
            T = eltype(v.data)
            sz = collect(size(v.data))
            sz[pos] = k
            if !(T <: AbstractFloat || T <: Complex) && v.measured === nothing
                v.measured = trues(size(v.data))
            end
            v.data = cat(v.data, fill(not_measured(T), Tuple(sz)); dims=pos)
            v.measured === nothing || (v.measured = cat(v.measured, falses(Tuple(sz)); dims=pos))
            v.shape = size(v.data)
        end
    end
end

"""
    coords(d, name) -> OrderedDict

Each point's coordinates of value `name`: one vector per axis, along its dimension of the data.
A fixed axis gives its coordinates; the points of a group's level, every point's coordinate on
each axis down to it (following `parent`). A copy.
"""
function coords(d::Dataset, name::AbstractString)
    v = value_named(d, name)
    out = OrderedDict{String,Vector}()
    for dm in v.dims
        if !is_group_dim(d, dm)
            out[dm[1]] = copy(d.axes[dm[1]].data)
            continue
        end
        for (a, ix) in zip(dm, ancestors(d, dm))
            out[a] = d.axes[a].data[ix]
        end
    end
    return out
end

function value_named(d::Dataset, name)
    haskey(d.values, name) || throw(KeyError("no value named \"$name\"; values: $(collect(keys(d.values)))"))
    return d.values[name]
end

"""
    rows(d, name; by) -> Vector{Pair}

Value `name` row by row: one row per point of `by`'s level (per position of a fixed axis `by`),
as `key => row`. The key is the coordinate, or a tuple of the coordinates down to `by`; the row
is a `Dataset` (a copy) with what lies inside it.
"""
function rows(d::Dataset, name::AbstractString; by::AbstractString)
    v = value_named(d, name)
    pos = findfirst(dm -> by in dm, v.dims)
    pos === nothing && throw(LBDError("rows: \"$name\" doesn't lie on \"$by\" (its axes: $(v.axes))"))
    dm = v.dims[pos]
    if !is_group_dim(d, dm)
        return [d.axes[by].data[i] => part(d, v, pos, (:index, i)) for i in 1:length(d.axes[by].data)]
    end
    j = findfirst(==(by), dm)
    outer = dm[1:j]
    chain = ancestors(d, outer)
    keys_of(p) = (k = Tuple(d.axes[outer[m]].data[chain[m][p]] for m in 1:j); j == 1 ? k[1] : k)
    if j == length(dm)
        return [keys_of(p) => part(d, v, pos, (:point, p)) for p in 1:dim_length(d, outer)]
    end
    anc = ancestors(d, dm)[j]
    return [keys_of(p) => part(d, v, pos, (:under, j, p, findall(==(p), anc))) for p in 1:dim_length(d, outer)]
end

# A new dataset with the part of `v` that `sel` picks along dimension `pos`: (:index, i) of a fixed
# axis, (:point, p) of a level, or (:under, j, p, pts): the points under point p of level j.
function part(d::Dataset, v::Value, pos, sel)
    nd = Dataset(d.title)
    idx = Any[]
    dims = Tuple[]
    for (i, dm) in enumerate(v.dims)
        if i != pos
            copy_dim!(d, nd, dm)
            push!(idx, Colon()); push!(dims, dm)
            continue
        end
        if sel[1] in (:index, :point)
            push!(idx, sel[2])
            continue
        end
        _, j, p, pts = sel
        rest = dm[j+1:end]
        if length(rest) == 1
            src = d.axes[rest[1]]
            nd.axes[rest[1]] = Axis(rest[1], src.data[pts], src.unit, src.label)
            push!(idx, pts)
        else
            g = d.axes[dm[1]].group
            nd.groups[g] = Group(g, collect(rest))
            keep_above = nothing
            for m in j+1:length(dm)
                keep = findall(==(p), ancestors(d, dm[1:m])[j])
                src = d.axes[dm[m]]
                parent = keep_above === nothing ? nothing : [searchsortedfirst(keep_above, q) for q in src.parent[keep]]
                nd.axes[dm[m]] = Axis(dm[m], src.data[keep], src.unit, src.label, nothing, nothing, false, g, parent)
                keep_above = keep
            end
            push!(idx, keep_above)
        end
        push!(dims, Tuple(rest))
    end
    append!(idx, fill(Colon(), length(v.point_shape)))
    data = v.data[idx...]
    data isa AbstractArray && (data = copy(data))
    measured = v.measured isa AbstractArray ? copy(v.measured[idx...]) : v.measured
    shape = data isa AbstractArray ? size(data) : ()
    w = Value(v.name, data, String[a for dm in dims for a in dm], dims, v.unit, v.label, shape, v.dtype,
              v.point_shape, copy(v.elements), measured)
    nd.values[v.name] = w
    return nd
end

function copy_dim!(d::Dataset, nd::Dataset, dm)
    if is_group_dim(d, dm)
        g = d.axes[dm[1]].group
        haskey(nd.groups, g) || (nd.groups[g] = Group(g, collect(dm)))
    end
    for a in dm
        src = d.axes[a]
        nd.axes[a] = Axis(a, copy(src.data), src.unit, src.label, src.elements, nothing, false, src.group,
                          src.parent === nothing ? nothing : copy(src.parent))
    end
end

# An axis's ticks (sorted) from its points' coordinates, and each point's tick.
function ticks_of(c, name, round_, rtol, atol)
    c = Float64.(c)
    round_ === nothing || (c = round.(c; digits=round_))
    u = sort(unique(c))
    inv = [searchsortedfirst(u, x) for x in c]
    if rtol !== nothing || atol !== nothing
        r, a = something(rtol, 0.0), something(atol, 0.0)
        cluster = zeros(Int, length(u))
        first_ = NaN
        k = 0
        for (i, x) in enumerate(u)
            if isnan(first_) || abs(x - first_) > a + r * abs(first_)
                first_, k = x, k + 1
            end
            cluster[i] = k
        end
        ticks = [sum(u[cluster .== m]) / count(==(m), cluster) for m in 1:k]
        return ticks, cluster[inv]
    end
    if round_ === nothing && length(u) > 1 && any(x -> x != round(x), u)
        scale = max(u[end] - u[1], abs(u[1]), abs(u[end]))
        k = findfirst(<=(1e-9 * scale), diff(u))
        k === nothing || @warn "to_dense: \"$name\" has coordinates that differ only by rounding ($(repr(u[k])) and " *
            "$(repr(u[k+1]))): they become separate ticks. Merge them with round= or rtol= / atol="
    end
    return u, inv
end

"""
    to_dense(d, name; round=nothing, rtol=nothing, atol=nothing, limit=10^8) -> Dataset

Value `name` as a full rectangle: a `Dataset` with fixed axes only. A group stores only the
measured points ("sparse"); this places them in the full rectangle ("dense"). Each axis's ticks
are the sorted distinct coordinates of the value's points; cells not measured hold `NaN` (0 /
false with `measured` for integers and `Bool`). It doesn't interpolate; always a copy.
`round=n` rounds coordinates to `n` digits first, `rtol` / `atol` merge them as `isapprox`
(`|a - b| <= atol + rtol*|b|`); `limit=nothing`: no size limit.
"""
function to_dense(d::Dataset, name::AbstractString; round=nothing, rtol=nothing, atol=nothing, limit=10^8)
    v = value_named(d, name)
    round !== nothing && (rtol !== nothing || atol !== nothing) &&
        throw(LBDError("to_dense: give round= or rtol= / atol=, not both"))
    ticks = Dict{String,Vector}()
    places = Any[]
    for dm in v.dims
        if !is_group_dim(d, dm)
            ticks[dm[1]] = copy(d.axes[dm[1]].data)
            push!(places, nothing)
            continue
        end
        w = Vector{Vector{Int}}()
        for (a, ix) in zip(dm, ancestors(d, dm))
            t, inv = ticks_of(d.axes[a].data[ix], a, round, rtol, atol)
            ticks[a] = t
            push!(w, inv)
        end
        push!(places, w)
    end
    T = Tuple(length(ticks[a]) for a in v.axes)
    shape = (T..., v.point_shape...)
    cells = prod(shape; init=1)
    if limit !== nothing && cells > limit
        bits = something(tryparse(Int, match(r"\d+", v.dtype) === nothing ? "8" : match(r"\d+", v.dtype).match), 8)
        throw(LBDError("to_dense: \"$name\" as a rectangle $shape has $cells cells " *
                       "($(Base.round(cells * bits / 8 / 1e9; digits=2)) GB), more than limit=$limit. Read it row by row " *
                       "with rows(d, name; by=...), or give limit=nothing"))
    end
    E = JULIA_TYPES[v.dtype]
    out = fill(not_measured(E), shape)
    isint = !(E <: AbstractFloat || E <: Complex)
    mask = isint ? falses(shape) : nothing
    dimlens = Tuple(dim_length(d, dm) for dm in v.dims)
    seen = Set{Any}()
    point = Tuple(Colon() for _ in v.point_shape)
    for I in CartesianIndices(dimlens)
        target = Int[]
        for (k, w) in enumerate(places)
            w === nothing ? push!(target, I[k]) : append!(target, [inv[I[k]] for inv in w])
        end
        t = Tuple(target)
        t in seen && throw(LBDError("to_dense: two points of \"$name\" fall into one cell: merging must not drop a " *
                                    "result. Use a smaller round= / rtol= / atol="))
        push!(seen, t)
        if isempty(v.point_shape)
            out[t...] = v.data isa AbstractArray ? v.data[Tuple(I)...] : v.data
        else
            out[t..., point...] = v.data[Tuple(I)..., point...]
        end
        if isint
            src = v.measured === nothing ? true : v.measured isa AbstractArray ? v.measured[Tuple(I)..., point...] : v.measured
            isempty(v.point_shape) ? (mask[t...] = src) : (mask[t..., point...] .= src)
        end
    end
    m = Dataset(d.title)
    for a in v.axes
        src = d.axes[a]
        m.axes[a] = Axis(a, ticks[a], src.unit, src.label, src.group === nothing ? src.elements : nothing, nothing)
    end
    measured = mask === nothing || all(mask) ? nothing : mask
    m.values[name] = Value(name, out, copy(v.axes), Tuple[(a,) for a in v.axes], v.unit, v.label, shape, v.dtype,
                           v.point_shape, copy(v.elements), measured)
    return m
end

# An index of a fixed axis (1 = its first point), from an index or one of its elements.
function position(d::Dataset, a, x)
    ax = d.axes[a]
    n = length(ax.data)
    if x isa AbstractString || x isa Symbol
        i = ax.elements === nothing ? nothing : findfirst(==(String(x)), ax.elements)
        i === nothing && throw(LBDError("write!: \"$a\" has no element \"$x\"; " *
            (ax.elements === nothing ? "give an index (1 … $n)" : "its elements: $(ax.elements)")))
        return i
    end
    (x isa Integer && !(x isa Bool)) ||
        throw(LBDError("write!: \"$a\" takes one position: an index (1 … $n) or one of its elements, not $(repr(x))"))
    1 <= x <= n || throw(LBDError("write!: index $x is out of range for \"$a\" (it has $n points: 1 … $n)"))
    return Int(x)
end

const JULIA_TYPES = Dict(v => k for (k, v) in DTYPE_NAMES)

# Data for a value of type `dtype`: complex refused for real values, integers and Bool only when
# exactly representable.
function fits_type(x, dtype, name)
    T = JULIA_TYPES[dtype]
    S = x isa Number ? typeof(x) : x isa AbstractArray ? eltype(x) : nothing
    (S !== nothing && S <: Number) || throw(LBDError("write!: \"$name\" takes numbers, not $(typeof(x))"))
    S <: Complex && !(T <: Complex) && throw(LBDError("write!: \"$name\" is real ($dtype); refusing to drop an imaginary part"))
    if !(T <: AbstractFloat || T <: Complex)
        exact(e) = try convert(T, e) == e catch; false end
        all(exact, x isa Number ? (x,) : x) || throw(LBDError("write!: \"$name\" ($dtype) can't hold " *
            "$(x isa Number ? x : extrema(x)) exactly" * (T === Bool ? "; give true/false (or 0/1)" : "; it holds whole numbers")))
    end
    return x isa Number ? convert(T, x) : convert(Array{T}, x)
end

# X arranged as the place it goes: `need`, the sizes of the axes not given.
function shaped_for(x, need, name, free)
    ok = if isempty(need)
        x isa Number || length(x) == 1
    elseif length(need) == 1
        x isa AbstractVector && length(x) == need[1]
    else
        x isa AbstractArray && size(x) == Tuple(need)
    end
    ok || throw(LBDError("write!: \"$name\" needs data of size $(Tuple(need)) " *
                         "($(isempty(free) ? "one number" : join(free, ", "))), not $(x isa Number ? "one number" : size(x))"))
    return isempty(need) && !(x isa Number) ? x[1] : x
end

function apply_write!(d::Dataset, plan)
    if plan.grow !== nothing
        g, c = plan.grow.axis, plan.grow.coords
        ax = d.axes[g]
        ax.data = vcat(Float64.(ax.data), c)
        extend_values!(d, g, length(c))
    end
    grow_levels!(d, plan)
    for (a, c, _) in plan.levels
        extend_values!(d, a, length(c))
    end
    for p in plan.puts
        v = d.values[p.name]
        if isempty(p.idx)
            v.data = p.data
            v.measured === nothing || (v.measured = true)
        else
            v.data[p.idx...] = p.data
            v.measured === nothing || (view(v.measured, p.idx...) .= true)
        end
    end
end

# A data point's shape: a tuple of positive Ints (() for one number).
function check_shape(shape, name)
    shape isa Integer && (shape = (shape,))
    (shape isa Union{Tuple,AbstractVector} && all(n -> n isa Integer && !(n isa Bool), shape)) ||
        throw(LBDError("value \"$name\": shape must be a tuple of whole numbers such as (3,) or (2, 2), not $(repr(shape))"))
    any(n -> n < 1, shape) && throw(LBDError("value \"$name\": shape $(Tuple(shape)) has an empty dimension"))
    return Tuple(Int(n) for n in shape)
end

# The elements of each dimension of a data point (nothing: numbered).
function value_elements(elements, point, name)
    where = "value \"$name\""
    elements === nothing && return Any[nothing for _ in point]
    isempty(point) && throw(LBDError("$where: elements name the positions in a data point; give shape= too " *
                                     "(each data point here is one number)"))
    if length(point) == 1 && elements isa AbstractVector && all(e -> e isa AbstractString, elements)
        return Any[check_elements(elements, point[1], where)]
    end
    (elements isa AbstractVector && length(elements) == length(point)) ||
        throw(LBDError("$where: give one list of elements per dimension of a data point " *
                       "($(length(point)) for shape=$point), or nothing for a dimension left numbered"))
    return Any[e === nothing ? nothing : check_elements(e, n, "$where, dimension $k of a data point")
               for (k, (e, n)) in enumerate(zip(elements, point))]
end

axes_list(::Nothing) = String[]
axes_list(s::AbstractString) = isempty(s) ? String[] : String.(strip.(split(s, ",")))
axes_list(v) = String[String(x) for x in v]

function normalize_eltype(arr)
    T = eltype(arr)
    T === Float16 && return Float32.(arr)
    T === BigFloat && return Float64.(arr)
    T === ComplexF16 && return ComplexF32.(arr)
    T === Int && return arr  # Int is Int64 on 64-bit systems
    return arr
end

function coerce_value(data, dtype, name)
    arr = data isa Number ? data : collect(data)
    T = arr isa Number ? typeof(arr) : eltype(arr)
    if dtype === :auto
        T <: Number || throw(LBDError("value \"$name\" must be numeric or boolean, got $T"))
        arr = arr isa Number ? normalize_eltype([arr])[1] : normalize_eltype(arr)
        T2 = arr isa Number ? typeof(arr) : eltype(arr)
        haskey(DTYPE_NAMES, T2) || throw(LBDError("value \"$name\": unsupported element type $T2"))
        return arr
    end
    dtype isa DataType && haskey(DTYPE_NAMES, dtype) || throw(LBDError(
        "value \"$name\": unsupported dtype $dtype; allowed: $(sort(collect(values(DTYPE_NAMES)))) or :auto"))
    if T <: Complex && !(dtype <: Complex)
        throw(LBDError("value \"$name\" is complex; refusing to drop the imaginary part (dtype=$dtype)"))
    end
    return arr isa Number ? convert(dtype, arr) : convert(Array{dtype}, arr)
end

# ---- dimension order (spec §2) -----------------------------------------------

to_file(a::AbstractArray) = ndims(a) >= 2 ? permutedims(a, ndims(a):-1:1) : a
to_file(x) = x
from_file(a::AbstractArray) = ndims(a) >= 2 ? permutedims(a, ndims(a):-1:1) : a
from_file(x) = x

# ---- saving -----------------------------------------------------------------

"""
    LBD.save(path, d; compression=false)

Write `d` to `path`. With `compression=true`, large arrays are gzip-compressed. The file is
written under a temporary name and then renamed, so a viewer never sees a half-written file.

The file gets the measurement's identity, `d.id` (a UUID version 7): a new one at the first
save; kept when `d` is saved again to the same file (also after `load`); a new one when `d` is
saved to another file, with the old one kept as `d.parent_id` ("made from"). A file copied by
the file system keeps its id, so LBD Viewer recognises the same measurement in two places.
On Windows a file another program keeps open (e.g. LBD Viewer reading it, a sync client) can't
be replaced: `save` waits up to $(REPLACE_WAIT) s for it, then throws an `IOError` naming the file.
"""
function save(path::AbstractString, d::Dataset; compression::Bool=false)
    endswith(lowercase(path), ".writing") &&
        throw(LBDError("$(basename(path)): a \".writing\" file is written only by LBD.Writer; save to the .lbd name"))
    lowercase(splitext(path)[2]) == ".lbd" || @warn "$(basename(path)): LBD files should use the .lbd extension"
    for a in values(d.axes)
        a.grows && isempty(a.data) &&
            throw(LBDError("the growing axis \"$(a.name)\" has no points yet; write some before saving"))
    end
    for v in values(d.values)
        v.data === nothing && throw(LBDError("value \"$(v.name)\" was not loaded; load the file without `values=` to re-save it"))
    end
    before = (d.id, d.parent_id)
    if d.id === nothing
        d.id = uuid7()
    elseif d.path !== nothing && !same_file(d.path, path)
        new_id!(d)                       # saved as another file: a new measurement made from this one
    end
    tmp = "$path.tmp-$(getpid())"
    try
        h5open(tmp, "w") do f
            write_file(f, d, compression)
        end
        replace_file(tmp, path)
    catch
        d.id, d.parent_id = before       # not saved: the dataset stays as it was
        rethrow()
    finally
        isfile(tmp) && rm(tmp)
    end
    d.path = String(path)
    return path
end

# Put the finished temporary file in place of `path`. On Windows this fails while another
# program has `path` open, even for a moment (LBD Viewer reading the new version, a sync client,
# an antivirus scan), so it tries again for up to REPLACE_WAIT seconds.
function replace_file(tmp::AbstractString, path::AbstractString)
    deadline = time() + REPLACE_WAIT
    while true
        try
            mv(tmp, path; force=true)
            return
        catch e
            (e isa Base.IOError && Sys.iswindows()) || rethrow()
            time() > deadline && throw(Base.IOError("can't write $path: another program kept it open " *
                "for $(REPLACE_WAIT) s (e.g. LBD Viewer or a sync client). Close it there and save again", e.code))
            sleep(0.05)
        end
    end
end

function write_file(f, d::Dataset, compression::Bool)
    # when the data was created: kept as set (also as read by `load`); not set: this first save
    d.created = d.created === nothing ? Dates.format(now(), dateformat"yyyy-mm-ddTHH:MM:SS") * utc_offset() :
        created_text(d.created)
    d.writer = "julia LBD $PACKAGE_VERSION"
    write_str_attr(f, "lbd_format", "LBD")
    d.lbd_version = version_needed(d)
    write_str_attr(f, "lbd_version", d.lbd_version)
    write_str_attr(f, "title", d.title)
    write_str_attr(f, "description", d.description)
    write_str_attr(f, "created", d.created)
    write_str_attr(f, "writer", d.writer)
    write_str_attr(f, "id", d.id)
    d.parent_id === nothing || write_str_attr(f, "parent_id", d.parent_id)

    ga = create_group(f, "axes")
    for a in file_axes(d)
        ds = write_array(ga, a.name, a.data, compression)
        write_str_attr(ds, "unit", a.unit)
        write_str_attr(ds, "label", a.label)
        if a.elements !== nothing
            check_elements(a.elements, length(a.data), "axis \"$(a.name)\"")
            write_attribute(ds, "elements", String[e for e in a.elements])
        end
        a.role === nothing || write_str_attr(ds, "role", a.role)
    end
    for g in values(d.groups)                    # axis groups (spec §1.8), level by level
        gg = create_group(ga, g.name)
        write_str_attr(gg, "order", join(g.order, ","))
        for (k, name) in enumerate(g.order)
            a = d.axes[name]
            ds = write_array(gg, name, collect(a.data), compression)
            write_str_attr(ds, "unit", a.unit)
            write_str_attr(ds, "label", a.label)
            k > 1 && write_array(gg, name * "._parent", Int64.(a.parent) .- 1, compression)   # from 0 in the file
        end
    end

    gv = create_group(f, "values")
    for v in values(d.values)
        data = v.data
        isbool = (data isa Bool) || (data isa AbstractArray && eltype(data) === Bool)
        if isbool
            data = data isa Bool ? UInt8(data) : UInt8.(data)
        end
        ds = write_array(gv, v.name, to_file(data), compression)
        write_str_attr(ds, "unit", v.unit)
        write_str_attr(ds, "label", v.label)
        write_str_attr(ds, "axes", join(vcat(v.axes, point_names(v)), ","))
        isbool && write_attribute(ds, "lbd_bool", Int64(1))
    end

    # integer / Bool points never measured (stopped early)
    masks = [v for v in values(d.values) if v.measured !== nothing && !all(v.measured)]
    if !isempty(masks)
        gm = create_group(f, "measured")
        for v in masks
            m = v.measured isa Bool ? UInt8(v.measured) : UInt8.(collect(v.measured))
            write_array(gm, v.name, to_file(m), compression)
        end
    end

    write_meta(create_group(f, "meta"), d.meta, "meta")

    if d.plot !== nothing || d.style !== nothing || d.style_name !== nothing
        gp = create_group(f, "plot")
        d.plot !== nothing && write_str_attr(gp, "spec", JSON3.write(d.plot))
        d.style !== nothing && write_str_attr(gp, "style", JSON3.write(d.style))
        d.style_name !== nothing && write_str_attr(gp, "style_name", d.style_name)
        d.matplotlib !== nothing && !isempty(d.matplotlib) && write_str_attr(gp, "matplotlib", d.matplotlib)
    end
end

# The axes the file stores at its top: the fixed axes, then each value's data point dimensions
# (format 1.2: role "point", holding 0 … n-1).
function file_axes(d::Dataset)
    out = OrderedDict{String,Axis}(a.name => a for a in values(d.axes) if a.group === nothing)
    for v in values(d.values)
        for (k, (pn, n)) in enumerate(zip(point_names(v), v.point_shape))
            haskey(out, pn) && continue
            label = length(v.point_shape) > 1 ? "$(v.label) (dim$k)" : v.label
            out[pn] = Axis(pn, collect(0:n-1), "", label, k <= length(v.elements) ? v.elements[k] : nothing, "point")
        end
    end
    return collect(values(out))
end

const CREATED_RE = r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$"

"""
    created_text(x)

`created` as stored: ISO-8601 text with a UTC offset. A `DateTime` is taken in this computer's
time zone; a text is kept as written, and one without an offset gets this computer's offset.
Anything else throws an `LBDError`.
"""
created_text(x::DateTime) = Dates.format(x, dateformat"yyyy-mm-ddTHH:MM:SS") * utc_offset()
function created_text(x::AbstractString)
    t = strip(x)
    m = match(CREATED_RE, t)
    ok = m !== nothing && try
        DateTime(parse.(Int, m.captures[1:5])..., m.captures[6] === nothing ? 0 : parse(Int, m.captures[6]))
        true
    catch
        false
    end
    ok || throw(LBDError("created must be a date and time: a DateTime, or ISO-8601 text such as " *
                         "\"2026-10-13T16:09:00+08:00\", not $(repr(x))"))
    return m.captures[7] === nothing ? String(t) * utc_offset() : String(t)
end
created_text(x) = throw(LBDError("created must be a date and time: a DateTime, or ISO-8601 text such as " *
                                 "\"2026-10-13T16:09:00+08:00\", not $(repr(x))"))

function utc_offset()
    mins = round(Int, (now() - now(UTC)).value / 60_000)
    sign = mins < 0 ? "-" : "+"
    mins = abs(mins)
    return string(sign, lpad(mins ÷ 60, 2, '0'), ":", lpad(mins % 60, 2, '0'))
end

function write_array(g, name, data, compression::Bool)
    if compression && data isa AbstractArray && length(data) >= COMPRESS_MIN_SIZE
        ds = create_dataset(g, name, datatype(eltype(data)), dataspace(data);
                            chunk=HDF5.heuristic_chunk(data), deflate=4)
        write_dataset(ds, datatype(eltype(data)), data)
        return ds
    end
    write_dataset(g, name, data)
    return g[name]
end

# HDF5.jl writes scalar strings as fixed-length; the spec asks for variable-length UTF-8.
function write_str_attr(obj, name::AbstractString, s::AbstractString)
    str = String(s)
    dt = HDF5.Datatype(HDF5.API.h5t_copy(HDF5.API.H5T_C_S1))
    HDF5.API.h5t_set_size(dt, HDF5.API.H5T_VARIABLE)
    HDF5.API.h5t_set_cset(dt, HDF5.API.H5T_CSET_UTF8)
    space = HDF5.Dataspace(HDF5.API.h5s_create(HDF5.API.H5S_SCALAR))
    attr = create_attribute(obj, name, dt, space)
    try
        GC.@preserve str begin
            HDF5.API.h5a_write(attr, dt, Ref(pointer(str)))
        end
    finally
        close(attr); close(space); close(dt)
    end
end

function write_meta(g, meta::AbstractDict, where::String)
    for (k, val) in meta
        key = String(k)
        (isempty(key) || occursin('/', key)) && throw(LBDError("$where: invalid meta key \"$key\""))
        if val isa AbstractDict
            write_meta(create_group(g, key), val, "$where/$key")
        elseif val isa NamedTuple
            write_meta(create_group(g, key), OrderedDict(pairs(val)), "$where/$key")
        else
            write_meta_attr(g, key, val, "$where/$key")
        end
    end
end

function write_meta_attr(g, key, val, where)
    if val === nothing || val === missing
        throw(LBDError("$where: $(repr(val)) can't be stored; omit the key instead"))
    elseif val isa AbstractString || val isa Symbol
        write_str_attr(g, key, String(val))
    elseif val isa Bool
        write_attribute(g, key, Int64(val))
    elseif val isa Union{Real,Complex}
        write_attribute(g, key, normalize_eltype([val])[1])
    elseif val isa AbstractArray{<:AbstractString} || val isa AbstractArray{Symbol}
        ndims(val) == 1 || throw(LBDError("$where: string arrays in meta must be 1-D"))
        write_attribute(g, key, String[String(x) for x in val])
    elseif val isa AbstractArray{Bool}
        write_attribute(g, key, to_file(Int64.(val)))
    elseif val isa AbstractArray{<:Union{Real,Complex}}
        write_attribute(g, key, to_file(normalize_eltype(collect(val))))
    elseif val isa Tuple
        write_meta_attr(g, key, collect(val), where)
    else
        throw(LBDError("$where: can't store value of type $(typeof(val)) in meta"))
    end
end

# ---- loading ----------------------------------------------------------------

"""
    LBD.load(path; values=nothing)

Read an `.lbd` file. `values`: a name or names of the values whose data to load (default: all).
Values not listed are still described (shape, dtype, axes, unit) but their `.data` is `nothing`.
"""
function load(path::AbstractString; values=nothing, quiet::Bool=false)
    wanted = if values === nothing
        nothing
    elseif values isa AbstractString
        Set{String}([String(values)])          # one name, not its characters
    else
        all(v -> v isa AbstractString, values) ||
            throw(ArgumentError("values must be a name or a collection of names, got $(repr(values))"))
        Set{String}(String.(collect(values)))
    end
    writing = endswith(lowercase(path), ".writing")
    writing && !quiet && @warn "$(basename(path)) is still being written, or its writer stopped before finishing " *
        "(LBD.writing_status tells which); reading what was written so far"
    writing || return load_once(path, wanted, false)
    # A file being written can be caught while its writer finishes it (the description and
    # metadata are rewritten then): read it again a moment later.
    for attempt in 1:20
        try
            return load_once(path, wanted, true)
        catch e
            (attempt == 20 || e isa KeyError) && rethrow()
            isfile(path) || throw(LBDError("$(basename(path)) was finished while it was read: open " *
                                           "$(basename(path)[1:end-length(".writing")])"))
            sleep(0.05)
        end
    end
end

function load_once(path, wanted, writing)
    d = open_for_reading(path, writing) do f
        d = read_header(f, path)
        if haskey(f, "axes")
            for name in keys(f["axes"])
                obj = f["axes"][name]
                if obj isa HDF5.Group
                    read_group!(d, name, obj, path)
                else
                    d.axes[name] = read_axis(name, obj, path)
                end
            end
        end
        if haskey(f, "values")
            for name in keys(f["values"])
                ds = f["values"][name]
                v = describe_value(name, ds)
                if wanted === nothing || name in wanted
                    v.data = read_value_data(ds)
                end
                d.values[name] = v
            end
        end
        if haskey(f, "measured")
            for name in keys(f["measured"])
                v = get(d.values, name, nothing)
                (v === nothing || v.data === nothing) && continue
                m = from_file(read(f["measured"][name])) .!= 0
                m isa AbstractArray || (m = fill(m))
                writing && (m = cut_to(m, size(v.data)))
                if size(m) == size(v.data) || (v.data isa Number && length(m) == 1)
                    v.measured = v.data isa Number ? m[] : m
                else
                    @warn "$(basename(path)): the measured mask of \"$name\" has size $(size(m)), not $(size(v.data)); it is ignored"
                end
            end
        end
        resolve_dims!(d, path)
        writing && same_lengths!(d)       # a growing axis, a group's levels and their values may be caught mid-write
        if wanted !== nothing
            missing_names = setdiff(wanted, keys(d.values))
            isempty(missing_names) || throw(KeyError("$(basename(path)): no value(s) named $(sort(collect(missing_names)))"))
        end
        d
    end
    validate_loaded(d)
    return d
end

function read_axis(name, ds, path)
    data = vec(read(ds))
    a = Axis(name, data, attr_str(ds, "unit"), attr_str(ds, "label", name))
    if haskey(attributes(ds), "elements")
        raw = read_attribute(ds, "elements")
        raw isa AbstractString && (raw = [raw])
        if raw isa AbstractVector && length(raw) == length(data) && all(e -> e isa AbstractString, raw)
            a.elements = String[String(e) for e in raw]
        else
            @warn "$(basename(path)): axis \"$name\" has elements that aren't one text per position; they are ignored"
        end
    end
    role = attr_str(ds, "role")
    if role == "point"
        a.role = role
    elseif !isempty(role)
        @warn "$(basename(path)): axis \"$name\" has an unknown role \"$role\"; it is read as a sweep axis"
    end
    return a
end

# A file being written is opened in SWMR mode with HDF5's file locking off (spec §7); one written
# by this process is read through its Writer (HDF5 shares one handle per file within a process).
function open_for_reading(f::Function, path, writing)
    if writing
        w = own_writer(path)
        if w !== nothing && w.file !== nothing
            flush_pending!(w)
            return f(w.file)
        end
        fapl = HDF5.FileAccessProperties()
        fapl.file_locking = (false, true)
        return h5open(f, path, "r"; swmr=true, fapl=fapl)
    end
    return h5open(f, path, "r")
end

cut_to(x::AbstractArray, sz) = x[(1:min(size(x, k), sz[k]) for k in 1:length(sz))...]

# An axis group (spec §1.8): its axes level by level, each point's parent (from 1 here).
function read_group!(d::Dataset, name, g, path)
    haskey(d.axes, name) && throw(LBDError("$(basename(path)): \"$name\" is used by an axis and a group"))
    order = axes_list(attr_str(g, "order"))
    isempty(order) && throw(LBDError("$(basename(path)): the axis group \"$name\" has no 'order' attribute; it breaks the LBD format"))
    for (k, a) in enumerate(order)
        (haskey(d.axes, a) || haskey(d.groups, a)) && throw(LBDError("$(basename(path)): \"$a\" (in group \"$name\") is used twice"))
        haskey(g, a) || throw(LBDError("$(basename(path)): /axes/$name/$a is missing"))
        ds = g[a]
        ax = Axis(a, vec(read(ds)), attr_str(ds, "unit"), attr_str(ds, "label", a), nothing, nothing, false, String(name), nothing)
        if k > 1
            haskey(g, a * "._parent") || throw(LBDError("$(basename(path)): axis \"$a\" of group \"$name\" has no \"$a._parent\"; it breaks the LBD format"))
            ax.parent = Int.(vec(read(g[a*"._parent"]))) .+ 1
        end
        d.axes[a] = ax
    end
    d.groups[String(name)] = Group(String(name), order)
end

# Each value's axes as the file lists them -> its dimensions: the last ones with role "point" are
# its data point's (they leave d.axes), the others sweep dimensions (a fixed axis, a group's level).
function resolve_dims!(d::Dataset, path)
    trailing = String[]
    for v in values(d.values)
        names = v.axes
        k = length(names)
        while k > 0 && haskey(d.axes, names[k]) && d.axes[names[k]].role == "point"
            k -= 1
        end
        append!(trailing, names[k+1:end])
        dims = try
            parse_dims(d, names[1:k], "value \"$(v.name)\"")
        catch e
            e isa LBDError || rethrow()
            throw(LBDError("$(basename(path)): $(e.msg)"))
        end
        length(dims) + length(names) - k == length(v.shape) || throw(LBDError(
            "$(basename(path)): value \"$(v.name)\" has $(length(v.shape)) dimension(s) but axes=$names"))
        v.elements = Any[d.axes[a].elements for a in names[k+1:end]]
        v.axes = String[a for dm in dims for a in dm]
        v.dims = Tuple[Tuple(dm) for dm in dims]
        v.point_shape = Tuple(v.shape[length(dims)+1:end])
    end
    for (a, ax) in collect(d.axes)
        ax.role == "point" || continue
        swept = any(v -> a in v.axes, values(d.values))
        if a in trailing && swept
            throw(LBDError("$(basename(path)): axis \"$a\" is a dimension of a data point of some values and a sweep axis of others; it can't be both"))
        elseif a in trailing
            delete!(d.axes, a)
        else
            ax.role = nothing
            @warn "$(basename(path)): axis \"$a\" is marked as a dimension of a data point (role \"point\") but no value's data point uses it; it is read as a sweep axis"
        end
    end
end

# In a file being written, keep what is complete: each group level's points up to the first whose
# parent isn't there yet, and each axis (or level) and the values along it cut to the length all
# of them have reached (the writer extends them one after the other).
function same_lengths!(d::Dataset)
    changed = true
    while changed
        changed = false
        for g in values(d.groups)
            above = typemax(Int)
            for (k, a) in enumerate(g.order)
                ax = d.axes[a]
                n = length(ax.data)
                if k > 1
                    n = min(n, length(ax.parent))
                    late = findfirst(>(above), ax.parent[1:n])
                    late === nothing || (n = late - 1)
                end
                if n < length(ax.data) || (k > 1 && n < length(ax.parent))
                    ax.data = ax.data[1:n]
                    k > 1 && (ax.parent = ax.parent[1:n])
                    changed = true
                end
                above = n
            end
        end
        for (a, ax) in d.axes
            n = length(ax.data)
            for v in values(d.values), (i, dm) in enumerate(v.dims)
                dm[end] == a && i <= length(v.shape) && (n = min(n, v.shape[i]))
            end
            if n < length(ax.data)
                ax.data = ax.data[1:n]
                ax.parent === nothing || (ax.parent = ax.parent[1:n])
                changed = true
            end
            for v in values(d.values)
                cut = false
                sh = collect(v.shape)
                for (i, dm) in enumerate(v.dims)
                    if dm[end] == a && i <= length(sh) && sh[i] > n
                        sh[i] = n
                        cut = true
                    end
                end
                cut || continue
                v.shape = Tuple(sh)
                v.data === nothing || (v.data = cut_to(v.data, v.shape))
                v.measured isa AbstractArray && (v.measured = cut_to(v.measured, v.shape))
            end
        end
    end
end

"""Read everything except value data. Cheap, even for large files."""
info(path::AbstractString) = load(path; values=String[])

function read_header(f, path)
    fmt = attr_str(f, "lbd_format", "")
    fmt == "LBD" || throw(LBDError("$(basename(path)) is not an LBD file (missing lbd_format=\"LBD\")"))
    ver = attr_str(f, "lbd_version", "")
    check_version(ver, path)
    d = Dataset(attr_str(f, "title"); description=attr_str(f, "description"))
    c = attr_str(f, "created"); d.created = isempty(c) ? nothing : c
    w = attr_str(f, "writer"); d.writer = isempty(w) ? nothing : w
    d.id = read_id(f, "id", path)
    d.parent_id = read_id(f, "parent_id", path)
    d.lbd_version = ver
    d.path = String(path)
    haskey(f, "meta") && (d.meta = read_meta(f["meta"]))
    if haskey(f, "plot")
        g = f["plot"]
        d.plot = attr_json(g, "spec", path)
        d.style = attr_json(g, "style", path)
        s = attr_str(g, "style_name"); d.style_name = isempty(s) ? nothing : s
        m = attr_str(g, "matplotlib"); d.matplotlib = isempty(m) ? nothing : m
    end
    return d
end

# An id attribute: a UUID, or nothing (missing; a malformed one warns and counts as missing).
function read_id(f, name, path)
    s = attr_str(f, name)
    isempty(s) && return nothing
    occursin(UUID_RE, lowercase(s)) && return lowercase(s)
    @warn "$(basename(path)): $name \"$s\" is not a valid id (a UUID); it is ignored, and saving gives the file a new one"
    return nothing
end

function check_version(ver, path)
    m = match(r"^(\d+)\.(\d+)$", ver)
    m === nothing && throw(LBDError("$(basename(path)): invalid lbd_version \"$ver\""))
    major, minor = parse(Int, m[1]), parse(Int, m[2])
    if major > FORMAT_MAJOR
        throw(LBDVersionError("$(basename(path)) uses LBD format $ver, but this LBD package ($PACKAGE_VERSION) " *
                              "only supports formats up to $FORMAT_MAJOR.x. Please update LBD."))
    elseif !haskey(LATEST_MINOR, major)
        throw(LBDError("$(basename(path)): LBD format $ver doesn't exist (the first version is 1.0)"))
    elseif minor > LATEST_MINOR[major]
        @warn "$(basename(path)) uses LBD format $ver, newer than $major.$(LATEST_MINOR[major]); some content may be ignored. Consider updating LBD."
    end
end

"The lowest format version that holds `d`'s content (spec §6): 2.0 with an axis group, 1.2 without."
version_needed(d::Dataset) = isempty(d.groups) ? GRID_VERSION : FORMAT_VERSION

function describe_value(name, ds)
    isbool = attr_int(ds, "lbd_bool") == 1
    T = eltype(ds)
    isbool || haskey(DTYPE_NAMES, T) ||
        throw(LBDError("value \"$name\" uses a type LBD does not support ($T)"))
    dtype = isbool ? "bool" : DTYPE_NAMES[T]
    shape = Tuple(reverse(collect(size(ds))))   # HDF5.jl reports dims in Julia (reversed) order
    return Value(name, nothing, axes_list(attr_str(ds, "axes")), attr_str(ds, "unit"),
                 attr_str(ds, "label", name), shape, dtype)
end

function read_value_data(ds)
    raw = from_file(read(ds))
    if attr_int(ds, "lbd_bool") == 1
        raw = raw isa Number ? raw != 0 : raw .!= 0
    end
    return raw
end

function validate_loaded(d::Dataset)
    for g in values(d.groups)
        above = 0
        for (k, a) in enumerate(g.order)
            ax = d.axes[a]
            all(isfinite, ax.data) || throw(LBDError("axis \"$a\" of group \"$(g.name)\" contains NaN or Inf"))
            if k > 1
                length(ax.parent) == length(ax.data) || throw(LBDError(
                    "\"$a._parent\" has $(length(ax.parent)) entries for $(length(ax.data)) points"))
                all(p -> 1 <= p <= above, ax.parent) || throw(LBDError(
                    "\"$a._parent\" points outside \"$(g.order[k-1])\" (0 … $(above - 1) in the file)"))
            end
            pts = collect(zip(ax.parent === nothing ? zeros(Int, length(ax.data)) : ax.parent, ax.data))
            length(unique(pts)) < length(pts) && @warn "group \"$(g.name)\" has the same point twice on level \"$a\" " *
                "(same coordinate under the same outer point); both are kept"
            above = length(ax.data)
        end
    end
    for v in values(d.values)
        (haskey(d.axes, v.name) || haskey(d.groups, v.name)) &&
            throw(LBDError("\"$(v.name)\" is used by an axis or group and a value"))
        for (i, dm) in enumerate(v.dims)
            n = dim_length(d, dm)
            n == v.shape[i] || throw(LBDError("value \"$(v.name)\": dimension $i has size $(v.shape[i]) but " *
                (is_group_dim(d, dm) ? "the level $(join(dm, ",")) has $n points" : "axis \"$(dm[1])\" has length $n")))
        end
    end
end

function read_meta(g, where="/meta")
    out = OrderedDict{String,Any}()
    for k in keys(attributes(g))
        val = read_attribute(g, k)
        out[k] = val isa AbstractArray && !(eltype(val) <: AbstractString) ? from_file(val) : val
    end
    for k in keys(g)
        obj = g[k]
        if obj isa HDF5.Group
            haskey(out, k) && @warn "$where has an attribute and a group both named \"$k\"; the group is used"
            out[k] = read_meta(obj, "$where/$k")
        else
            @warn "$where/$k is a dataset; LBD metadata are attributes, so it is skipped"
        end
    end
    return out
end

function attr_str(obj, key, default="")
    haskey(attributes(obj), key) || return default
    val = read_attribute(obj, key)
    val isa AbstractVector && length(val) == 1 && (val = val[1])
    return String(string(val))
end

attr_int(obj, key) = haskey(attributes(obj), key) ? Int(read_attribute(obj, key)) : 0

function attr_json(g, key, path)
    s = attr_str(g, key)
    isempty(s) && return nothing
    parsed = try
        JSON3.read(s)
    catch e
        e isa ArgumentError || rethrow()   # JSON3 reports invalid JSON as ArgumentError
        @warn "$(basename(path)): /plot/$key is not valid JSON; ignored"
        return nothing
    end
    if !(parsed isa JSON3.Object)
        @warn "$(basename(path)): /plot/$key must be a JSON object; ignored"
        return nothing
    end
    return to_plain(parsed)
end

to_plain(x::JSON3.Object) = Dict{String,Any}(String(k) => to_plain(v) for (k, v) in x)
to_plain(x::JSON3.Array) = Any[to_plain(v) for v in x]
to_plain(x) = x

include("writer.jl")

end # module
