# Reading only what is needed: LBD.open and the on-disk array (plan 6d).
#
# `LBD.open(path)` reads a file's structure and gives every value an `OnDisk` array as its data:
# indexing it reads only that part of the file (`d["S21"].data[4, :]`); `collect` reads it all.
# The file stays open until `close(d)` (or the end of a do-block). `mode="r"` (default) only
# reads; `mode="r+"` also writes at points that exist and saves (in place, or a copy).

# The file an opened dataset reads from: held open, or opened for each read (a file being
# written: spec §7 says readers don't keep it open). Reads are serialised.
mutable struct LazySource
    path::String
    mode::String
    writing::Bool
    file::Union{HDF5.File,Nothing}
    closed::Bool
    lock::ReentrantLock
end

function LazySource(path::AbstractString, mode::AbstractString)
    writing = endswith(lowercase(path), ".writing")
    file = writing ? nothing : h5open(path, mode == "r+" ? "r+" : "r")
    return LazySource(String(path), String(mode), writing, file, false, ReentrantLock())
end

function run_on(f::Function, s::LazySource)
    lock(s.lock) do
        s.closed && throw(LBDError("$(basename(s.path)) is closed: open it again, or use LBD.load"))
        s.file !== nothing && return f(s.file)
        return open_for_reading(f, s.path, true)
    end
end

function check_change(s::LazySource, what)
    s.mode == "r+" || throw(LBDError("$(basename(s.path)) is opened read-only (mode=\"r\"): $what is refused. " *
                                     "Open it with mode=\"r+\" to change it, or use LBD.load"))
    s.closed && throw(LBDError("$(basename(s.path)) is closed: open it again, or use LBD.load"))
end

function Base.close(s::LazySource)
    lock(s.lock) do
        s.file === nothing || close(s.file)
        s.file = nothing
        s.closed = true
    end
end

"""
    OnDisk{T,N} <: AbstractArray{T,N}

A value's data in the file (`LBD.open`): its size and type without reading; indexing reads only
that part (`x[4, :]`), `collect(x)` reads it all. Read the part first for anything elementwise:
each element read alone is one file read.
"""
struct OnDisk{T,N} <: AbstractArray{T,N}
    source::LazySource
    where_::String
    shape::NTuple{N,Int}
    isbool::Bool
end

Base.size(x::OnDisk) = x.shape
Base.show(io::IO, ::MIME"text/plain", x::OnDisk{T,N}) where {T,N} =
    print(io, "LBD.OnDisk ", x.where_, " ", x.shape, " ", T, " (in the file; index it to read)")
Base.show(io::IO, x::OnDisk) = show(io, MIME"text/plain"(), x)
Base.collect(x::OnDisk{T,N}) where {T,N} = N == 0 ? fill(x[]) : x[ntuple(_ -> Colon(), N)...]
Base.Array(x::OnDisk) = collect(x)
Base.copy(x::OnDisk) = collect(x)

# One element: the general method below (a box of one).
Base.getindex(x::OnDisk{T,N}, I::Vararg{Int,N}) where {T,N} = read_part(x, I)
Base.getindex(x::OnDisk, I...) = read_part(x, I)

function read_part(x::OnDisk{T,N}, I) where {T,N}
    N == 0 && return read_box(x, ())[]
    if length(I) != N
        return collect(x)[I...]                       # linear indexing: read it all, then index
    end
    checkbounds(x, I...)
    J = to_indices(x, I)
    box = UnitRange{Int}[]
    picks = Any[]
    keep = Int[]
    for (k, j) in enumerate(J)
        if j isa Integer
            push!(box, j:j)
        else
            v = collect(j)
            isempty(v) && return Array{T}(undef, Tuple(length(collect(jj)) for jj in J if !(jj isa Integer))...)
            lo, hi = minimum(v), maximum(v)
            push!(box, lo:hi)
            push!(picks, v .- (lo - 1))
            push!(keep, k)
        end
    end
    arr = read_box(x, box)
    arr = arr[(j isa Integer ? 1 : picks[findfirst(==(k), keep)] for (k, j) in enumerate(J))...]
    return isempty(keep) ? arr : reshape(arr, Tuple(length(picks[i]) for i in eachindex(keep)))
end

function read_box(x::OnDisk{T,N}, box) where {T,N}
    raw = run_on(x.source) do f
        ds = f[x.where_]
        N == 0 ? read(ds) : ds[reverse(Tuple(box))...]
    end
    arr = N == 0 ? fill(raw) : from_file(raw)
    x.isbool && (arr = arr .!= 0)
    return convert(Array{T}, arr)
end

function Base.setindex!(x::OnDisk{T,N}, v, I...) where {T,N}
    check_change(x.source, "write!")
    J = to_indices(x, I)
    box = [j isa Integer ? (j:j) : (collect(j) == first(j):last(j) ? (first(j):last(j)) :
           throw(LBDError("writing into an opened file takes indices and ranges of consecutive points"))) for j in J]
    block = reshape(v isa Number ? [v] : collect(v), Tuple(length.(box)))
    data = x.isbool ? UInt8.(block) : convert(Array{T}, block)
    run_on(x.source) do f
        f[x.where_][reverse(Tuple(box))...] = to_file(data)
    end
    return x
end

"""
    LBD.open(path; mode="r") -> Dataset
    LBD.open(path; mode="r") do d … end

Open an `.lbd` file to read only what is needed: the structure now, value data when it is
indexed. Each value's `data` is an `OnDisk` array: `d["S21"].data[4, :]` reads row 4 only,
`size` reads nothing, `collect` reads it all. `coords`, `rows` and `to_dense` read only what they
need. `close(d)` (or the end of the do-block) closes it; what was read stays usable.

`mode="r"` (default): read only; `write!` and `save` are refused. `mode="r+"`: `write!` puts data
into the file at points that exist (no new points or axes), `LBD.save(d)` rewrites the
description, metadata and saved view in place, `LBD.save("copy.lbd", d)` copies the file
piece by piece. A file being written (`.lbd.writing`) opens with `mode="r"`, as it was then.
"""
function open(path::AbstractString; mode::AbstractString="r")
    mode in ("r", "r+") || throw(LBDError("mode must be \"r\" (read) or \"r+\" (read and write), not \"$mode\""))
    endswith(lowercase(path), ".writing") && mode != "r" &&
        throw(LBDError("$(basename(path)) is being written by a measurement: open it with mode=\"r\""))
    d = load(path; values=String[])                    # the structure; no value data
    source = LazySource(path, mode)
    try
        has_mask = run_on(source) do f
            Dict(name => haskey(f, "measured") && haskey(f["measured"], name) for name in keys(d.values))
        end
        for (name, v) in d.values
            T = JULIA_TYPES[v.dtype]
            N = length(v.shape)
            v.data = OnDisk{T,N}(source, "values/$name", Tuple(v.shape), v.dtype == "bool")
            has_mask[name] && (v.measured = OnDisk{Bool,N}(source, "measured/$name", Tuple(v.shape), true))
        end
    catch
        close(source)
        rethrow()
    end
    d.source = source
    return d
end

function open(f::Function, path::AbstractString; kw...)
    d = open(path; kw...)
    try
        return f(d)
    finally
        close(d)
    end
end

"""Close the file of a dataset opened with `LBD.open` (nothing to do after `LBD.load`)."""
Base.close(d::Dataset) = (d.source === nothing || close(d.source); nothing)

# `LBD.save(d)` of a dataset opened with mode="r+": the description, metadata and saved view
# rewritten in the file (the data is already there).
function save_in_place(d::Dataset)
    s = d.source
    h5open(tempname() * ".h5", "w"; driver=HDF5.Drivers.Core(; backing_store=false)) do f
        write_meta(create_group(f, "meta"), d.meta, "meta")             # refused before anything changes
    end
    run_on(s) do f
        for a in ("title", "description")
            haskey(attributes(f), a) && delete_attribute(f, a)
        end
        write_str_attr(f, "title", d.title)
        write_str_attr(f, "description", d.description)
        haskey(f, "meta") && delete_object(f, "meta")
        write_meta(create_group(f, "meta"), d.meta, "meta")
        haskey(f, "plot") && delete_object(f, "plot")
        if d.plot !== nothing || d.style !== nothing || d.style_name !== nothing
            gp = create_group(f, "plot")
            d.plot !== nothing && write_str_attr(gp, "spec", JSON3.write(d.plot))
            d.style !== nothing && write_str_attr(gp, "style", JSON3.write(d.style))
            d.style_name !== nothing && write_str_attr(gp, "style_name", d.style_name)
            d.matplotlib !== nothing && !isempty(d.matplotlib) && write_str_attr(gp, "matplotlib", d.matplotlib)
        end
    end
    return s.path
end
