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

export Dataset, Axis, Value, add_axis!, add_value!, write!, new_id!, LBDError, LBDVersionError
export Writer, lbd_writer, writing_status, recover

const PACKAGE_VERSION = "1.3.0-dev"
const FORMAT_VERSION = "1.2"
const FORMAT_MAJOR, FORMAT_MINOR = parse.(Int, split(FORMAT_VERSION, "."))
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
    role::Union{String,Nothing}               # "point": an axis of a value's data point (1.2); nothing: a sweep axis
    grows::Bool                               # write! adds its points (add_axis!(...; grows=true)); not stored
end
Axis(name, data, unit, label) = Axis(name, data, unit, label, nothing, nothing, false)
Axis(name, data, unit, label, elements, role) = Axis(name, data, unit, label, elements, role, false)
Base.length(a::Axis) = length(a.data)

mutable struct Value
    name::String
    data::Any                 # Array, a Number for 0-D values, or `nothing` if not loaded
    axes::Vector{String}
    unit::String
    label::String
    shape::Tuple              # logical shape, kept even when data is not loaded
    dtype::String
    point_axes::Vector{String}   # the axes of one data point (the last of `axes`; format 1.2)
    elements::Vector{Any}        # per data-point dimension: its texts (Vector{String}) or nothing
    # For an integer or Bool value filled by write!: true where something was written; nothing
    # for every other value (NaN means "not measured")
    measured::Any
end
Value(name, data, axes, unit, label, shape, dtype) = Value(name, data, axes, unit, label, shape, dtype, String[], Any[], nothing)
Value(name, data, axes, unit, label, shape, dtype, point_axes, elements) =
    Value(name, data, axes, unit, label, shape, dtype, point_axes, elements, nothing)

"""The shape of one data point of `v`: `()` for one number, `(3,)` for a vector of 3 …"""
point_shape(v::Value) = isempty(v.point_axes) ? () : Tuple(v.shape[end-length(v.point_axes)+1:end])

mutable struct Dataset
    title::String
    description::String
    created::Union{String,DateTime,Nothing}   # when the data was created; filled at the first save if nothing
    writer::Union{String,Nothing}
    lbd_version::String
    axes::OrderedDict{String,Axis}
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
end

Dataset(title::AbstractString=""; description::AbstractString="", created=nothing) = Dataset(
    String(title), String(description), created === nothing ? nothing : created_text(created), nothing, FORMAT_VERSION,
    OrderedDict{String,Axis}(), OrderedDict{String,Value}(), OrderedDict{String,Any}(),
    nothing, nothing, nothing, nothing, nothing, nothing, nothing, false, String[],
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
    haskey(d, name) && throw(LBDError("name \"$name\" is already used by an axis or value"))
end

"""
    add_axis!(d, name, data=nothing; unit="", label=name, elements=nothing, grows=false)

Add a 1-D real axis. `elements`: a text for each position (e.g. `["ground", "excited"]`);
`data` may then be left out (the positions are numbered 0, 1, 2 …). `grows=true`: an axis of
unknown length (a log, "until I stop it"), given no data; `write!` adds its points. It must be
the first axis of the values on it.
"""
function add_axis!(d::Dataset, name::AbstractString, data=nothing; unit::AbstractString="",
                   label::AbstractString=name, elements=nothing, grows::Bool=false)
    check_new_name(d, name)
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

Add an N-D value. `axes` lists one axis name per dimension (or a single name / comma-separated
string). `size(data)` must match the axis lengths. `dtype=:auto` keeps the element type;
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
    axl = axes_list(axes)
    point = check_shape(shape, name)
    measured = nothing
    placeholder = false
    if data === nothing                 # filled later by write!: "not measured yet"
        for ax in axl
            haskey(d.axes, ax) || throw(LBDError("value \"$name\": axis \"$ax\" does not exist; add it with add_axis! first"))
        end
        T = dtype === :auto ? Float64 : dtype
        (T isa DataType && haskey(DTYPE_NAMES, T)) || throw(LBDError(
            "value \"$name\": unsupported dtype $dtype; allowed: $(sort(collect(values(DTYPE_NAMES)))) or :auto"))
        full = (Tuple(length(d.axes[a]) for a in axl)..., point...)
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
    if length(axl) + length(point) != nd
        if length(axl) < nd && isempty(point)
            throw(LBDError("value \"$name\" has $nd dimension(s) but $(length(axl)) axes were given: $axl; " *
                           "if each data point holds several numbers, say so with shape=$(size(arr)[length(axl)+1:end])"))
        end
        throw(LBDError("value \"$name\" has $nd dimension(s), but its axes $axl and shape=$point make " *
                       "$(length(axl) + length(point))"))
    end
    growing = [ax for ax in axl if haskey(d.axes, ax) && d.axes[ax].grows]
    (length(growing) > 1 || (!isempty(growing) && axl[1] != growing[1])) && throw(LBDError(
        "value \"$name\": a growing axis must be its first axis, and only one (here $axl)"))
    for (i, ax) in enumerate(axl)
        haskey(d.axes, ax) || throw(LBDError("value \"$name\": axis \"$ax\" does not exist; add it with add_axis! first"))
        if !placeholder && length(d.axes[ax]) != size(arr, i)
            hint = !isempty(point) && size(arr)[end-length(point)+1:end] != point ?
                "; the value's axes come first, then the data point (e.g. use permutedims)" : ""
            throw(LBDError("value \"$name\": dimension $i has size $(size(arr, i)) but axis \"$ax\" has " *
                           "length $(length(d.axes[ax]))$hint"))
        end
    end
    if !placeholder && !isempty(point) && size(arr)[length(axl)+1:end] != point
        throw(LBDError("value \"$name\": its data points have shape $(size(arr)[length(axl)+1:end]), not shape=$point"))
    end
    named = value_elements(elements, point, name)
    point_names = ["$(name)_dim$k" for k in 1:length(point)]
    for pn in point_names
        haskey(d, pn) && throw(LBDError("value \"$name\" needs the name \"$pn\" for an axis of its data " *
                                        "points, but it is already used; rename that axis or value"))
    end
    for (k, (pn, n)) in enumerate(zip(point_names, point))
        plabel = length(point) > 1 ? "$label (dim$k)" : String(label)
        d.axes[pn] = Axis(pn, collect(0:n-1), "", plabel, named[k], "point")
    end
    vshape = placeholder ? (Tuple(length(d.axes[a]) for a in axl)..., point...) : arr isa Number ? () : size(arr)
    T = arr isa Number ? typeof(arr) : eltype(arr)
    v = Value(String(name), arr, vcat(axl, point_names), String(unit), String(label), vshape,
              DTYPE_NAMES[T], point_names, named, measured)
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
- a value: its data, sized as the value's axes that weren't given (and its data point), in order.

Names that can't be keywords go in the `Dict`. Writing again to the same place replaces the data.

```julia
write!(d; power=3, S21=trace)               # a trace
write!(d; power=3, freq=7, S21=z, T=t)      # a point, and T at power 3
write!(d; time=12.5, T=4.2)                 # a growing axis: adds a point
```
"""
function write!(d::Dataset, names::AbstractDict=Dict{String,Any}(); kw...)
    apply_write!(d, plan_write(d, names, kw))
    return nothing
end

function plan_write(d::Dataset, names::AbstractDict, kw)
    given = OrderedDict{String,Any}(String(k) => v for (k, v) in names)
    for (k, v) in kw
        haskey(given, String(k)) && throw(LBDError("write!: \"$k\" is given twice"))
        given[String(k)] = v
    end
    unknown = [k for k in keys(given) if !haskey(d, k)]
    isempty(unknown) || throw(LBDError("write!: no axis or value named $unknown; axes: $(collect(keys(d.axes))), " *
                                       "values: $(collect(keys(d.values)))"))
    vals = [k for k in keys(given) if haskey(d.values, k)]
    isempty(vals) && throw(LBDError("write!: give at least one value with its data, e.g. write!(d; power=3, S21=trace)"))
    positions = [k for k in keys(given) if haskey(d.axes, k)]
    grow = nothing
    index = Dict{String,Int}()
    for a in positions
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
        for a in v.axes
            ax = d.axes[a]
            if ax.grows
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
        x = fits_type(given[name], v.dtype, name)
        x = shaped_for(x, need, name, free)
        push!(puts, (name=name, idx=idx, data=x))
    end
    return (grow=grow, puts=puts)
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
        for v in values(d.values)
            (isempty(v.axes) || v.axes[1] != g) && continue
            T = eltype(v.data)
            rest = size(v.data)[2:end]
            if !(T <: AbstractFloat || T <: Complex) && v.measured === nothing
                v.measured = trues(size(v.data))
            end
            v.data = cat(v.data, fill(not_measured(T), (length(c), rest...)); dims=1)
            v.measured === nothing || (v.measured = cat(v.measured, falses((length(c), rest...)); dims=1))
            v.shape = size(v.data)
        end
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
    write_str_attr(f, "lbd_version", FORMAT_VERSION)
    write_str_attr(f, "title", d.title)
    write_str_attr(f, "description", d.description)
    write_str_attr(f, "created", d.created)
    write_str_attr(f, "writer", d.writer)
    write_str_attr(f, "id", d.id)
    d.parent_id === nothing || write_str_attr(f, "parent_id", d.parent_id)

    ga = create_group(f, "axes")
    for a in values(d.axes)
        ds = write_array(ga, a.name, a.data, compression)
        write_str_attr(ds, "unit", a.unit)
        write_str_attr(ds, "label", a.label)
        if a.elements !== nothing
            check_elements(a.elements, length(a.data), "axis \"$(a.name)\"")
            write_attribute(ds, "elements", String[e for e in a.elements])
        end
        a.role === nothing || write_str_attr(ds, "role", a.role)
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
        write_str_attr(ds, "axes", join(v.axes, ","))
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
    d = open_for_reading(path, writing) do f
        d = read_header(f, path)
        if haskey(f, "axes")
            for name in keys(f["axes"])
                ds = f["axes"][name]
                d.axes[name] = read_axis(name, ds, path)
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
        writing && same_lengths!(d)       # a growing axis and its values may be caught mid-write
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

# In a file being written, cut each axis and the values on it to the length all of them have
# reached (the writer extends them one after the other).
function same_lengths!(d::Dataset)
    for (a, ax) in d.axes
        n = length(ax.data)
        for v in values(d.values)
            k = findfirst(==(a), v.axes)
            k === nothing || k > length(v.shape) || (n = min(n, v.shape[k]))
        end
        n < length(ax.data) && (ax.data = ax.data[1:n])
        for v in values(d.values)
            k = findfirst(==(a), v.axes)
            (k === nothing || v.shape[k] <= n) && continue
            v.shape = Tuple(i == k ? n : s for (i, s) in enumerate(v.shape))
            v.data === nothing || (v.data = cut_to(v.data, v.shape))
            v.measured isa AbstractArray && (v.measured = cut_to(v.measured, v.shape))
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
                              "only supports $FORMAT_MAJOR.x. Please update LBD."))
    elseif major == FORMAT_MAJOR && minor > FORMAT_MINOR
        @warn "$(basename(path)) uses LBD format $ver, newer than $FORMAT_VERSION; some content may be ignored. Consider updating LBD."
    end
end

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
    for v in values(d.values)
        length(v.axes) == length(v.shape) ||
            throw(LBDError("value \"$(v.name)\" has $(length(v.shape)) dimension(s) but axes=$(v.axes)"))
        for (i, ax) in enumerate(v.axes)
            haskey(d.axes, ax) || throw(LBDError("value \"$(v.name)\" refers to missing axis \"$ax\""))
            length(d.axes[ax]) == v.shape[i] || throw(LBDError(
                "value \"$(v.name)\": dimension $i has size $(v.shape[i]) but axis \"$ax\" has length $(length(d.axes[ax]))"))
        end
        # a data point's axes are the last ones with role "point"
        k = length(v.axes)
        while k > 0 && d.axes[v.axes[k]].role == "point"
            k -= 1
        end
        v.point_axes = v.axes[k+1:end]
        v.elements = Any[d.axes[a].elements for a in v.point_axes]
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
