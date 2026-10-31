# Writing while measuring: LBD.Writer (spec §7, "Files being written").
#
# The Writer writes `name.lbd.writing` in HDF5's single-writer / multiple-reader (SWMR) mode, so
# LBD readers can show the data while it is measured, and holds the guard: an exclusive lock on
# one byte at offset 2^40 of the file, for as long as it writes. The lock disappears with the
# process, so `writing_status` tells "measuring" (held) from "stopped" (a crash, an error, a
# script ended without closing; `recover` turns such a file into an `.lbd` file). At the finish
# the file is closed and renamed to `name.lbd`.

const GUARD_OFFSET = Int64(2)^40   # the guard's byte: far beyond any data, so no read is blocked
const FINISH_WAIT = 10.0           # seconds the finish waits for a program holding the file (Windows)

"""
    LBD.Writer(path; title="", description="", created=nothing, flush_every=0.5, force_every=2.0)

Write a file while measuring: readers see the data as it comes, and a crash loses at most the
last moments. Build it like a `Dataset` (`add_axis!`, `add_value!` without data, `w.meta`), then
`write!` each point, trace or map as it is measured. It writes `path * ".writing"`; `close`
makes it `path`. Use it with `lbd_writer`, which closes it, or leaves the `.writing` file when
the block throws:

```julia
lbd_writer("sweep.lbd"; title="Resonator power sweep") do w
    add_axis!(w, "power", p; unit="dBm")
    add_axis!(w, "freq", f; unit="Hz")
    add_value!(w, "S21"; axes=["power", "freq"], dtype=ComplexF64)
    for i in eachindex(p)
        write!(w; power=i, S21=measure(p[i]))
    end
end
```

Saving a whole dataset at the end with `LBD.save` stays the simple way when nobody needs to
look while it is measured.
"""
mutable struct Writer
    path::String                  # the finished file
    writing_path::String          # the file while written
    d::Dataset                    # the description and the checks
    flush_every::Float64
    force_every::Float64
    file::Union{HDF5.File,Nothing}
    guard::Union{IOStream,Nothing}
    pending::Vector{Any}
    last_flush::Float64
    last_force::Float64
    timer::Union{Timer,Nothing}
    failure::Any                  # an exception from writing to the file
    state::Symbol                 # :new, :writing, :finished, :stopped
    lock::ReentrantLock
end

const OWN_WRITERS = Dict{String,Writer}()      # files written by this process
own_key(path) = (p = abspath(path); Sys.iswindows() ? lowercase(p) : p)
own_writer(path) = get(OWN_WRITERS, own_key(path), nothing)

function Writer(path::AbstractString; title::AbstractString="", description::AbstractString="",
                created=nothing, flush_every::Real=0.5, force_every::Real=2.0)
    lowercase(splitext(path)[2]) == ".lbd" ||
        throw(LBDError("$(basename(path)): LBD.Writer writes .lbd files; give a name ending in .lbd"))
    writing = path * ".writing"
    for p in (path, writing)
        ispath(p) && throw(LBDError("$p exists; LBD.Writer never replaces a file - choose another name"))
    end
    (flush_every > 0 && force_every > 0) || throw(LBDError("flush_every and force_every must be positive numbers of seconds"))
    d = Dataset(title; description=description, created=created)
    d.live = true
    return Writer(String(path), writing, d, flush_every, force_every, nothing, nothing, Any[], 0.0, 0.0,
                  nothing, nothing, :new, ReentrantLock())
end

function Base.getproperty(w::Writer, s::Symbol)
    s in (:title, :description, :meta, :plot, :style, :style_name, :axes, :values, :id) && return getfield(getfield(w, :d), s)
    return getfield(w, s)
end
function Base.setproperty!(w::Writer, s::Symbol, x)
    s in (:title, :description, :meta, :plot, :style, :style_name) && return setfield!(getfield(w, :d), s, x)
    return setfield!(w, s, x)
end
Base.show(io::IO, w::Writer) = print(io, "LBD.Writer(\"", w.state == :writing ? w.writing_path : w.path, "\", :", w.state, ")")

"""
    lbd_writer(f, path; kw...)

Run `f(w)` with a new `LBD.Writer(path; kw...)` and close it afterwards. If `f` throws, what was
measured stays in the `.writing` file ("stopped before finishing"; `recover` makes it an `.lbd`
file) and the error goes on.
"""
function lbd_writer(f::Function, path::AbstractString; kw...)
    w = Writer(path; kw...)
    try
        f(w)
    catch
        try
            abort!(w)
        catch e
            @warn "$(basename(w.writing_path)): writing what was measured failed too: $(sprint(showerror, e))"
        end
        isfile(w.writing_path) && @warn "the measurement stopped with an error; what was measured is in " *
            "$(basename(w.writing_path)) (LBD.recover makes it an .lbd file)"
        rethrow()
    end
    return close(w)
end

function before_start(w::Writer, what)
    w.state == :new || throw(LBDError("$what: give every axis and value before the first write! " *
                                      "(a file being written can't get new ones)"))
end

"""As `add_axis!` for a `Dataset`; before the first `write!`."""
function add_axis!(w::Writer, name::AbstractString, data=nothing; kw...)
    before_start(w, "add_axis!")
    return add_axis!(w.d, name, data; kw...)
end

"""As `add_value!` for a `Dataset`; before the first `write!`. Without data the value is filled
by `write!`; with data it is written whole at the start."""
function add_value!(w::Writer, name::AbstractString, data, axes=String[]; kw...)
    before_start(w, "add_value!")
    return add_value!(w.d, name, data, axes; kw...)
end
add_value!(w::Writer, name::AbstractString; axes=String[], kw...) = add_value!(w, name, nothing, axes; kw...)

"""
    start!(w)

Create the `.writing` file now (the first `write!` does it otherwise).
"""
function start!(w::Writer)
    w.state == :new || return w
    d = w.d
    isempty(d.values) && throw(LBDError("add at least one value before writing"))
    (ispath(w.writing_path) || ispath(w.path)) && throw(LBDError("$(w.writing_path) exists; LBD.Writer never replaces a file"))
    d.created = d.created === nothing ? Dates.format(now(), dateformat"yyyy-mm-ddTHH:MM:SS") * utc_offset() :
        created_text(d.created)
    d.writer = "julia LBD $PACKAGE_VERSION"
    d.id = uuid7()
    # the HDF5 1.10 format (SWMR needs it): readable by every HDF5 since, unlike :latest
    f = h5open(w.writing_path, "w"; libver_bounds=(v"1.10", v"1.10"))
    try
        w.guard = take_guard(w.writing_path)    # at once: from now on it reads "measuring"
        create_live!(f, d)
        HDF5.start_swmr_write(f)
    catch
        close(f)
        w.guard === nothing || (close(w.guard); w.guard = nothing)
        rm(w.writing_path; force=true)
        rethrow()
    end
    w.file = f
    w.state = :writing
    w.last_flush = w.last_force = time()
    OWN_WRITERS[own_key(w.writing_path)] = w
    return w
end

function create_live!(f, d::Dataset)
    write_str_attr(f, "lbd_format", "LBD")
    d.lbd_version = version_needed(d)
    write_str_attr(f, "lbd_version", d.lbd_version)
    write_str_attr(f, "title", d.title)
    write_str_attr(f, "description", d.description)
    write_str_attr(f, "created", d.created)
    write_str_attr(f, "writer", d.writer)
    write_str_attr(f, "id", d.id)
    ga = create_group(f, "axes")
    for a in values(d.axes)
        ds = a.grows ? live_dataset(ga, a.name, Float64, (0,), true) : write_array(ga, a.name, a.data, false)
        write_str_attr(ds, "unit", a.unit)
        write_str_attr(ds, "label", a.label)
        a.elements === nothing || write_attribute(ds, "elements", String[e for e in a.elements])
        a.role === nothing || write_str_attr(ds, "role", a.role)
    end
    gv = create_group(f, "values")
    masks = String[]
    for v in values(d.values)
        grows = !isempty(v.axes) && d.axes[v.axes[1]].grows
        T = JULIA_TYPES[v.dtype]
        if v.name in d.placeholders
            ds = live_dataset(gv, v.name, T === Bool ? UInt8 : T, v.shape, grows)
            (T <: AbstractFloat || T <: Complex) || push!(masks, v.name)
        else
            data = v.data isa Bool ? UInt8(v.data) : eltype(v.data) === Bool ? UInt8.(v.data) : v.data
            ds = write_array(gv, v.name, to_file(data), false)
        end
        write_str_attr(ds, "unit", v.unit)
        write_str_attr(ds, "label", v.label)
        write_str_attr(ds, "axes", join(v.axes, ","))
        T === Bool && write_attribute(ds, "lbd_bool", Int64(1))
    end
    if !isempty(masks)
        gm = create_group(f, "measured")
        for name in masks
            v = d.values[name]
            live_dataset(gm, name, UInt8, v.shape, !isempty(v.axes) && d.axes[v.axes[1]].grows)
        end
    end
    write_meta(create_group(f, "meta"), d.meta, "meta")
end

# A chunked dataset of logical `shape`, reading NaN (or 0) where nothing was written; `grows`:
# unlimited along its first logical dimension. HDF5.jl counts dimensions in Julia order (reversed).
function live_dataset(g, name, T, shape, grows)
    isempty(shape) && return create_dataset(g, name, datatype(T), dataspace(()); fill_value=not_measured(T))
    dims = reverse(Tuple(shape))
    maxd = grows ? (dims[1:end-1]..., -1) : dims
    chunk = collect(max.(dims, 1))
    grows && (chunk[end] = max(1, 8192 ÷ max(1, prod(chunk[1:end-1]))))
    while prod(chunk) > 2^17 && any(>(1), chunk)
        k = argmax(chunk)
        chunk[k] = cld(chunk[k], 2)
    end
    return create_dataset(g, name, datatype(T), dataspace(dims; max_dims=maxd); chunk=Tuple(chunk),
                          fill_value=not_measured(T))
end

"""
    write!(w::Writer; names...)

Put measured data in its place: as `write!` for a `Dataset`. It returns at once; the data
reaches the file within `flush_every` seconds (or at `flush`, `close`).
"""
function write!(w::Writer, names::AbstractDict=Dict{String,Any}(); kw...)
    raise_failure(w)
    w.state == :new && start!(w)
    w.state == :writing || throw(LBDError("$(basename(w.path)): the Writer is closed; nothing more can be written"))
    plan = plan_write(w.d, names, kw)
    lock(w.lock) do
        if plan.grow !== nothing
            ax = w.d.axes[plan.grow.axis]
            ax.data = vcat(Float64.(ax.data), plan.grow.coords)
            push!(w.pending, (:grow, plan.grow.axis, plan.grow.coords, length(ax.data)))
        end
        for p in plan.puts
            push!(w.pending, (:put, p.name, p.idx, copy(p.data)))   # a copy: the caller may reuse its buffer
        end
    end
    if time() - w.last_flush >= w.flush_every
        flush_pending!(w)
        raise_failure(w)
    else
        flush_soon!(w)
    end
    return nothing
end

"""Write everything collected so far to the file now (readers see it)."""
function Base.flush(w::Writer)
    raise_failure(w)
    w.state == :writing && flush_pending!(w)
    raise_failure(w)
    return w
end

# A one-off timer, so a burst of writes followed by a pause still reaches the file.
function flush_soon!(w::Writer)
    (w.timer !== nothing && isopen(w.timer)) && return
    w.timer = Timer(_ -> flush_pending!(w), w.flush_every)
end

function flush_pending!(w::Writer)
    lock(w.lock) do
        (w.file === nothing || w.failure !== nothing) && return
        items, w.pending = w.pending, Any[]
        try
            for item in items
                apply_live!(w, item)
            end
            isempty(items) || flush(w.file)
            if time() - w.last_force >= w.force_every
                force_to_disk(w.guard)
                w.last_force = time()
            end
        catch e
            w.failure = e
        end
        w.last_flush = time()
    end
end

function apply_live!(w::Writer, item)
    f, d = w.file, w.d
    if item[1] === :grow
        _, g, c, n = item
        for v in values(d.values)            # values first: readers cut to the shortest
            (isempty(v.axes) || v.axes[1] != g) && continue
            extend!(f["values"][v.name], n)
            haskey(f, "measured") && haskey(f["measured"], v.name) && extend!(f["measured"][v.name], n)
        end
        ds = f["axes"][g]
        extend!(ds, n)
        ds[(n - length(c) + 1):n] = c
    else
        _, name, idx, data = item
        v = d.values[name]
        shape = Tuple(d.axes[a].grows ? length(d.axes[a].data) : s for (a, s) in zip(v.axes, v.shape))
        put!(f["values"][name], idx, eltype(data) === Bool || data isa Bool ? UInt8.(data) : data, shape)
        if haskey(f, "measured") && haskey(f["measured"], name)
            put!(f["measured"][name], idx, data isa Number ? 0x01 : fill(0x01, size(data)), shape)
        end
    end
end

function extend!(ds, n)
    dims = size(ds)
    HDF5.set_extent_dims(ds, (dims[1:end-1]..., n))   # the first logical dimension is Julia's last
end

# Write `data` at the logical place `idx` (an index, a range or `:` per dimension) of `ds`.
function put!(ds, idx, data, shape)
    if isempty(idx)
        write_dataset(ds, datatype(typeof(data)), fill(data))
        return
    end
    ranges = [i isa Colon ? (1:shape[k]) : i isa Integer ? (i:i) : i for (k, i) in enumerate(idx)]
    block = reshape(data isa Number ? [data] : data, Tuple(length.(ranges)))
    ds[reverse(ranges)...] = to_file(block)
end

function raise_failure(w::Writer)
    w.failure === nothing && return
    throw(LBDError("writing $(basename(w.writing_path)) failed: $(sprint(showerror, w.failure)). What was written " *
                   "before is in $(w.writing_path); LBD.recover makes it an .lbd file once this Writer is closed"))
end

"""
    close(w::Writer; stopped=false) -> path

Finish: write what is left, close the file and rename it to `w.path` (or `name (2).lbd` if that
was made meanwhile). `stopped=true`: the measurement was stopped on purpose; the points not
measured stay `NaN` (or masked) without the warning about them.
"""
function Base.close(w::Writer; stopped::Bool=false)
    w.state == :new && start!(w)
    w.state == :writing || return w.path
    check_description(w.d)                 # bad metadata: still writing, nothing lost
    stop_timer!(w)
    flush_pending!(w)
    if w.failure !== nothing
        abort!(w)
        raise_failure(w)
    end
    close(w.file)
    w.file = nothing
    missing_masks = try
        finish_description(w)
    catch
        release_guard!(w)
        w.state = :stopped
        rethrow()
    end
    release_guard!(w)
    if !isempty(missing_masks) && !stopped
        @warn "$(basename(w.path)): $(join(missing_masks, ", ")) not measured everywhere; the points not measured are " *
              "marked in the file (close(w; stopped=true) says the measurement was stopped on purpose)"
    end
    target = free_name(w.path)
    target == w.path || @warn "$(basename(w.path)) was made by someone else while measuring; the measurement is saved as $(basename(target))"
    deadline = time() + FINISH_WAIT
    while true
        try
            mv(w.writing_path, target)
            break
        catch e
            e isa Base.IOError || rethrow()
            if time() > deadline
                w.state = :stopped
                throw(LBDError("the measurement is complete, but another program kept $(w.writing_path) open for " *
                               "$(FINISH_WAIT) s, so it couldn't be renamed to $(basename(target)). Close it there, then " *
                               "rename it yourself or use LBD.recover"))
            end
            sleep(0.1)
        end
    end
    w.state = :finished
    w.path = target
    return target
end

"""
    abort!(w)

Stop without finishing: what was written stays in the `.writing` file ("stopped before
finishing"; `recover` makes it an `.lbd` file).
"""
function abort!(w::Writer)
    w.state == :writing || return w
    stop_timer!(w)
    try
        flush_pending!(w)
        close(w.file)
    finally
        w.file = nothing
        release_guard!(w)
        w.state = :stopped
    end
    return w
end

function stop_timer!(w::Writer)
    w.timer === nothing || close(w.timer)
    w.timer = nothing
end

function check_description(d::Dataset)
    d.plot === nothing || JSON3.write(d.plot)
    d.style === nothing || JSON3.write(d.style)
    h5open(tempname() * ".h5", "w"; driver=HDF5.Drivers.Core(; backing_store=false)) do f
        write_meta(create_group(f, "meta"), d.meta, "meta")
    end
end

# What SWMR can't change while writing: the description, metadata, saved view; and the masks of
# values measured completely. Returns the values not measured everywhere.
function finish_description(w::Writer)
    d = w.d
    missing_masks = String[]
    h5open(w.writing_path, "r+") do f
        for key in ("title", "description")
            delete_attribute(f, key)
        end
        write_str_attr(f, "title", d.title)
        write_str_attr(f, "description", d.description)
        delete_object(f, "meta")
        write_meta(create_group(f, "meta"), d.meta, "meta")
        if d.plot !== nothing || d.style !== nothing || d.style_name !== nothing
            gp = create_group(f, "plot")
            d.plot !== nothing && write_str_attr(gp, "spec", JSON3.write(d.plot))
            d.style !== nothing && write_str_attr(gp, "style", JSON3.write(d.style))
            d.style_name !== nothing && write_str_attr(gp, "style_name", d.style_name)
        end
        if haskey(f, "measured")
            gm = f["measured"]
            for name in collect(keys(gm))
                if all(!=(0), read(gm[name]))
                    delete_object(gm, name)
                else
                    push!(missing_masks, name)
                end
            end
            isempty(keys(gm)) && delete_object(f, "measured")
        end
    end
    return missing_masks
end

# `path`, or `name (2).lbd`, `name (3).lbd` … if it is taken.
function free_name(path)
    ispath(path) || return path
    stem, ext = splitext(path)
    k = 2
    while ispath("$stem ($k)$ext")
        k += 1
    end
    return "$stem ($k)$ext"
end

# ---- the guard lock --------------------------------------------------------

struct Overlapped                  # Windows OVERLAPPED: the offset of a byte-range lock
    internal::UInt
    internal_high::UInt
    offset::UInt32
    offset_high::UInt32
    event::Ptr{Cvoid}
end
const GUARD_OVERLAPPED = Overlapped(0, 0, UInt32(GUARD_OFFSET & 0xffffffff), UInt32(GUARD_OFFSET >> 32), C_NULL)

# POSIX `struct flock` for the guard byte (Linux: locks of an open file description, which other
# handles of the file in this process can't release; macOS: classic record locks).
@static if Sys.islinux()
    struct Flock
        l_type::Int16
        l_whence::Int16
        l_start::Int64
        l_len::Int64
        l_pid::Int32
    end
    const F_SETLK, F_GETLK, F_WRLCK, F_UNLCK = Cint(37), Cint(36), Int16(1), Int16(2)   # F_OFD_SETLK, F_OFD_GETLK
    flock_of(kind) = Flock(kind, 0, GUARD_OFFSET, 1, 0)
    flock_type(l::Flock) = l.l_type
elseif Sys.isapple()
    struct Flock
        l_start::Int64
        l_len::Int64
        l_pid::Int32
        l_type::Int16
        l_whence::Int16
    end
    const F_SETLK, F_GETLK, F_WRLCK, F_UNLCK = Cint(8), Cint(7), Int16(3), Int16(2)
    flock_of(kind) = Flock(GUARD_OFFSET, 1, 0, kind, 0)
    flock_type(l::Flock) = l.l_type
else
    struct Flock end               # Windows locks with LockFileEx instead
end

# Try to lock the guard byte of the open file `io`; true if it was free.
function try_guard(io::IOStream)
    if Sys.iswindows()
        h = Libc._get_osfhandle(RawFD(fd(io)))
        ok = ccall((:LockFileEx, "kernel32"), stdcall, Cint,
                   (Ptr{Cvoid}, UInt32, UInt32, UInt32, UInt32, Ref{Overlapped}),
                   h, 0x2 | 0x1, 0, 1, 0, Ref(GUARD_OVERLAPPED))       # exclusive | fail immediately
        return ok != 0
    end
    r = ccall(:fcntl, Cint, (Cint, Cint, Ref{Flock}), fd(io), F_SETLK, Ref(flock_of(F_WRLCK)))
    return r == 0
end

function take_guard(path)
    io = open(path, "r+")
    try_guard(io) || (close(io); throw(LBDError("$path is being written by another program")))
    return io
end

function release_guard!(w::Writer)
    w.guard === nothing || close(w.guard)        # closing the handle releases its lock
    w.guard = nothing
    delete!(OWN_WRITERS, own_key(w.writing_path))
end

function force_to_disk(io::IOStream)
    if Sys.iswindows()
        h = Libc._get_osfhandle(RawFD(fd(io)))
        ccall((:FlushFileBuffers, "kernel32"), stdcall, Cint, (Ptr{Cvoid},), h) != 0 ||
            throw(Base.IOError("forcing the data to disk failed", Int(Libc.GetLastError())))
    else
        ccall(:fsync, Cint, (Cint,), fd(io)) == 0 || throw(Base.SystemError("fsync"))
    end
end

"""
    writing_status(path) -> String

`"measuring"`: the writer of the file being written holds its guard lock; `"stopped"`: it
doesn't (it crashed, or the script ended or was stopped before finishing) — `recover` makes it
an `.lbd` file. `path` is `name.lbd.writing` (or `name.lbd`, meaning its `.writing` file). Only
programs on this computer are seen: a file measured elsewhere and synced here is `"stopped"`.
"""
function writing_status(path::AbstractString)
    p = writing_path_of(path)
    isfile(p) || throw(LBDError("no file being written: $p"))
    own_writer(p) === nothing || return "measuring"
    io = try
        open(p, "r+")
    catch
        open(p, "r")
    end
    try
        if Sys.iswindows()
            try_guard(io) || return "measuring"
            h = Libc._get_osfhandle(RawFD(fd(io)))
            ccall((:UnlockFileEx, "kernel32"), stdcall, Cint, (Ptr{Cvoid}, UInt32, UInt32, UInt32, Ref{Overlapped}),
                  h, 0, 1, 0, Ref(GUARD_OVERLAPPED))
            return "stopped"
        end
        l = Ref(flock_of(F_WRLCK))
        ccall(:fcntl, Cint, (Cint, Cint, Ref{Flock}), fd(io), F_GETLK, l) == 0 || throw(Base.SystemError("fcntl"))
        return flock_type(l[]) == F_UNLCK ? "stopped" : "measuring"
    finally
        close(io)
    end
end

function writing_path_of(path)
    p = String(path)
    endswith(lowercase(p), ".writing") && return p
    lowercase(splitext(p)[2]) == ".lbd" && return p * ".writing"
    throw(LBDError("$(basename(p)) is not a file being written (name.lbd.writing)"))
end

"""
    recover(path) -> String

Make a stopped `.writing` file into an `.lbd` file with everything it holds: copies what was
written into `name.lbd` (or `name (2).lbd` … if that is taken), checks the copy, removes the
`.writing` file, and returns the new file's path. Points never measured stay `NaN` (or masked).
The file keeps its id. Refused while it is still measuring.
"""
function recover(path::AbstractString)
    src = writing_path_of(path)
    writing_status(src) == "measuring" &&
        throw(LBDError("$(basename(src)) is still being written (its writer holds it); recover it only after the measurement stopped"))
    d = load(src; quiet=true)
    target = free_name(src[1:end-length(".writing")])
    d.path = target                        # the same measurement: keep its id
    save(target, d)
    check = info(target)
    (check.id == d.id && Set(keys(check.values)) == Set(keys(d.values))) ||
        throw(LBDError("recovering $(basename(src)): the copy $(basename(target)) doesn't match; $(basename(src)) is kept"))
    deadline = time() + FINISH_WAIT
    while true
        try
            rm(src)
            break
        catch e
            (e isa Base.IOError && time() < deadline) || rethrow()
            sleep(0.1)
        end
    end
    return target
end
