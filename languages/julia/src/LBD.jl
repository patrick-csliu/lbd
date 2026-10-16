"""
    LBD

Read and write LBD (Lab Data, `.lbd`) files. See `spec/LBD-v1.md`.

```julia
using LBD
d = LBD.Dataset("Resonator power sweep")
add_axis!(d, "power", -40.0:4:0; unit="dBm", label="Power")
add_axis!(d, "freq", range(4e9, 8e9, 401); unit="Hz", label="Frequency")
add_value!(d, "S21", s21, ["power", "freq"])      # size(s21) == (11, 401)
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

export Dataset, Axis, Value, add_axis!, add_value!, LBDError, LBDVersionError

const PACKAGE_VERSION = "1.0.0"
const FORMAT_VERSION = "1.0"
const FORMAT_MAJOR = 1
const FORMAT_MINOR = 0
const NAME_RE = r"^[A-Za-z][A-Za-z0-9_]{0,62}$"
const COMPRESS_MIN_SIZE = 1024

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
end
Base.length(a::Axis) = length(a.data)

mutable struct Value
    name::String
    data::Any                 # Array, a Number for 0-D values, or `nothing` if not loaded
    axes::Vector{String}
    unit::String
    label::String
    shape::Tuple              # logical shape, kept even when data is not loaded
    dtype::String
end

mutable struct Dataset
    title::String
    description::String
    created::Union{String,Nothing}
    writer::Union{String,Nothing}
    lbd_version::String
    axes::OrderedDict{String,Axis}
    values::OrderedDict{String,Value}
    meta::OrderedDict{String,Any}
    plot::Union{Dict{String,Any},Nothing}
    style::Union{Dict{String,Any},Nothing}
    style_name::Union{String,Nothing}
    matplotlib::Union{String,Nothing}   # matplotlib version that last wrote the saved view (kept as is)
    path::Union{String,Nothing}
end

Dataset(title::AbstractString=""; description::AbstractString="") = Dataset(
    String(title), String(description), nothing, nothing, FORMAT_VERSION,
    OrderedDict{String,Axis}(), OrderedDict{String,Value}(), OrderedDict{String,Any}(),
    nothing, nothing, nothing, nothing, nothing,
)

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
    add_axis!(d, name, data; unit="", label=name)

Add a 1-D real axis.
"""
function add_axis!(d::Dataset, name::AbstractString, data; unit::AbstractString="", label::AbstractString=name)
    check_new_name(d, name)
    arr = collect(data)
    ndims(arr) == 1 || throw(LBDError("axis \"$name\" must be 1-D, got size $(size(arr))"))
    T = eltype(arr)
    (T <: Real && !(T <: Bool)) || throw(LBDError("axis \"$name\" must be real numeric, got $T"))
    arr = normalize_eltype(arr)
    haskey(DTYPE_NAMES, eltype(arr)) || throw(LBDError("axis \"$name\": unsupported element type $(eltype(arr))"))
    a = Axis(String(name), arr, String(unit), String(label))
    d.axes[a.name] = a
    return a
end

"""
    add_value!(d, name, data, axes=String[]; unit="", label=name, dtype=:auto)

Add an N-D value. `axes` lists one axis name per dimension (or a single name / comma-separated
string). `size(data)` must match the axis lengths. `dtype=:auto` keeps the element type;
pass e.g. `Float32` to force one.
"""
function add_value!(d::Dataset, name::AbstractString, data, axes=String[];
                    unit::AbstractString="", label::AbstractString=name, dtype=:auto)
    check_new_name(d, name)
    arr = coerce_value(data, dtype, name)
    axl = axes_list(axes)
    nd = arr isa Number ? 0 : ndims(arr)
    length(axl) == nd || throw(LBDError(
        "value \"$name\" has $nd dimension(s) but $(length(axl)) axes were given: $axl"))
    for (i, ax) in enumerate(axl)
        haskey(d.axes, ax) || throw(LBDError("value \"$name\": axis \"$ax\" does not exist; add it with add_axis! first"))
        length(d.axes[ax]) == size(arr, i) || throw(LBDError(
            "value \"$name\": dimension $i has size $(size(arr, i)) but axis \"$ax\" has length $(length(d.axes[ax]))"))
    end
    shape = arr isa Number ? () : size(arr)
    v = Value(String(name), arr, axl, String(unit), String(label), shape, DTYPE_NAMES[eltype(arr)])
    d.values[v.name] = v
    return v
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
"""
function save(path::AbstractString, d::Dataset; compression::Bool=false)
    lowercase(splitext(path)[2]) == ".lbd" || @warn "$(basename(path)): LBD files should use the .lbd extension"
    for v in values(d.values)
        v.data === nothing && throw(LBDError("value \"$(v.name)\" was not loaded; load the file without `values=` to re-save it"))
    end
    tmp = "$path.tmp-$(getpid())"
    try
        h5open(tmp, "w") do f
            write_file(f, d, compression)
        end
        mv(tmp, path; force=true)
    finally
        isfile(tmp) && rm(tmp)
    end
    d.path = String(path)
    return path
end

function write_file(f, d::Dataset, compression::Bool)
    d.created = Dates.format(now(), dateformat"yyyy-mm-ddTHH:MM:SS") * utc_offset()
    d.writer = "julia LBD $PACKAGE_VERSION"
    write_str_attr(f, "lbd_format", "LBD")
    write_str_attr(f, "lbd_version", FORMAT_VERSION)
    write_str_attr(f, "title", d.title)
    write_str_attr(f, "description", d.description)
    write_str_attr(f, "created", d.created)
    write_str_attr(f, "writer", d.writer)

    ga = create_group(f, "axes")
    for a in values(d.axes)
        ds = write_array(ga, a.name, a.data, compression)
        write_str_attr(ds, "unit", a.unit)
        write_str_attr(ds, "label", a.label)
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

    write_meta(create_group(f, "meta"), d.meta, "meta")

    if d.plot !== nothing || d.style !== nothing || d.style_name !== nothing
        gp = create_group(f, "plot")
        d.plot !== nothing && write_str_attr(gp, "spec", JSON3.write(d.plot))
        d.style !== nothing && write_str_attr(gp, "style", JSON3.write(d.style))
        d.style_name !== nothing && write_str_attr(gp, "style_name", d.style_name)
        d.matplotlib !== nothing && !isempty(d.matplotlib) && write_str_attr(gp, "matplotlib", d.matplotlib)
    end
end

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
function load(path::AbstractString; values=nothing)
    wanted = if values === nothing
        nothing
    elseif values isa AbstractString
        Set{String}([String(values)])          # one name, not its characters
    else
        all(v -> v isa AbstractString, values) ||
            throw(ArgumentError("values must be a name or a collection of names, got $(repr(values))"))
        Set{String}(String.(collect(values)))
    end
    d = h5open(path, "r") do f
        d = read_header(f, path)
        if haskey(f, "axes")
            for name in keys(f["axes"])
                ds = f["axes"][name]
                d.axes[name] = Axis(name, vec(read(ds)), attr_str(ds, "unit"), attr_str(ds, "label", name))
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
        if wanted !== nothing
            missing_names = setdiff(wanted, keys(d.values))
            isempty(missing_names) || throw(KeyError("$(basename(path)): no value(s) named $(sort(collect(missing_names)))"))
        end
        d
    end
    validate_loaded(d)
    return d
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

end # module
