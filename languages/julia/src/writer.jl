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
    beat::Union{Heartbeat,Nothing}        # the heartbeat file name.lbd.live (live.jl)
    beat_timer::Union{Timer,Nothing}      # rewrites it on time, also between writes
    failure::Any                  # an exception from writing to the file
    state::Symbol                 # :new, :writing, :finished, :stopped
    lock::ReentrantLock
end

const OWN_WRITERS = Dict{String,Writer}()      # files written by this process
own_key(path) = (p = abspath(path); Sys.iswindows() ? lowercase(p) : p)
own_writer(path) = get(OWN_WRITERS, own_key(path), nothing)

# ---- who has a file open; network shares (for messages only) ------------------------------

"""The programs that have `path` open, as text ("" if unknown): on Windows from the Restart
Manager (what Explorer uses for "the file is open in …"), elsewhere from `lsof`. Only for a
better message: never fails."""
function who_has_open(path::AbstractString)::String
    try
        Sys.iswindows() && return restart_manager(path)
        out = read(pipeline(ignorestatus(`lsof -Fc $path`); stderr=devnull), String)
        return join(sort(unique(l[2:end] for l in split(out, '\n') if startswith(l, "c"))), ", ")
    catch
        return ""
    end
end

# RM_PROCESS_INFO: RM_UNIQUE_PROCESS (pid, start time: 12 bytes), strAppName (256 UTF-16),
# strServiceShortName (64), ApplicationType, AppStatus, TSSessionId, bRestartable: 668 bytes.
const RM_INFO_BYTES = 668

function restart_manager(path::AbstractString)::String
    session, key = Ref{UInt32}(0), zeros(UInt16, 64)
    ccall((:RmStartSession, "rstrtmgr"), stdcall, UInt32, (Ref{UInt32}, UInt32, Ptr{UInt16}), session, 0, key) == 0 ||
        return ""
    try
        name = vcat(transcode(UInt16, String(abspath(path))), UInt16(0))
        GC.@preserve name begin
            files = [pointer(name)]
            ccall((:RmRegisterResources, "rstrtmgr"), stdcall, UInt32,
                  (UInt32, UInt32, Ptr{Ptr{UInt16}}, UInt32, Ptr{Cvoid}, UInt32, Ptr{Cvoid}),
                  session[], 1, files, 0, C_NULL, 0, C_NULL)
        end
        needed, count, reason = Ref{UInt32}(0), Ref{UInt32}(0), Ref{UInt32}(0)
        ccall((:RmGetList, "rstrtmgr"), stdcall, UInt32, (UInt32, Ref{UInt32}, Ref{UInt32}, Ptr{UInt8}, Ref{UInt32}),
              session[], needed, count, C_NULL, reason)
        needed[] == 0 && return ""
        infos = zeros(UInt8, RM_INFO_BYTES * needed[])
        count[] = needed[]
        ccall((:RmGetList, "rstrtmgr"), stdcall, UInt32, (UInt32, Ref{UInt32}, Ref{UInt32}, Ptr{UInt8}, Ref{UInt32}),
              session[], needed, count, infos, reason) == 0 || return ""
        names = String[]
        for i in 0:count[]-1
            at = i * RM_INFO_BYTES
            pid = reinterpret(UInt32, infos[at+1:at+4])[1]
            pid == getpid() && continue
            app = reinterpret(UInt16, infos[at+13:at+12+512])
            push!(names, "$(transcode(String, app[1:something(findfirst(==(0), app), length(app) + 1) - 1])) (process $pid)")
        end
        return join(names, ", ")
    finally
        ccall((:RmEndSession, "rstrtmgr"), stdcall, UInt32, (UInt32,), session[])
    end
end

"""Whether `folder` is on a network share (Windows: a UNC path or a remote drive)."""
function on_network_share(folder::AbstractString)::Bool
    Sys.iswindows() || return false
    p = abspath(folder)
    startswith(p, "\\\\") && return true
    root = vcat(transcode(UInt16, p[1:3]), UInt16(0))
    return ccall((:GetDriveTypeW, "kernel32"), stdcall, UInt32, (Ptr{UInt16},), root) == 4    # DRIVE_REMOTE
end

function Writer(path::AbstractString; title::AbstractString="", description::AbstractString="",
                created=nothing, flush_every::Real=0.5, force_every::Real=2.0)
    lowercase(splitext(path)[2]) == ".lbd" ||
        throw(LBDError("$(basename(path)): LBD.Writer writes .lbd files; give a name ending in .lbd"))
    writing = path * ".writing"
    for p in (path, writing)
        ispath(p) && throw(LBDError("$p exists; LBD.Writer never replaces a file - choose another name"))
    end
    (flush_every > 0 && force_every > 0) || throw(LBDError("flush_every and force_every must be positive numbers of seconds"))
    folder = dirname(abspath(path))
    on_network_share(isdir(folder) ? folder : pwd()) &&
        @warn "$folder is on a network share; writing while measuring is not tested there yet. Measure into a local folder if you see problems."
    d = Dataset(title; description=description, created=created)
    d.live = true
    return Writer(String(path), writing, d, flush_every, force_every, nothing, nothing, Any[], 0.0, 0.0,
                  nothing, nothing, nothing, nothing, :new, ReentrantLock())
end

function Base.getproperty(w::Writer, s::Symbol)
    s in (:title, :description, :meta, :plot, :style, :style_name, :axes, :groups, :values, :id) && return getfield(getfield(w, :d), s)
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

"""As `add_group!` for a `Dataset`; before the first `write!`. Its points are written into the
file as `write!` adds them."""
function add_group!(w::Writer, name::AbstractString)
    before_start(w, "add_group!")
    return add_group!(w.d, name)
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
    w.beat = Heartbeat(w.writing_path, d, d.writer)
    # Rewritten when Julia is free: an instrument call that blocks longer than a few minutes
    # shows as "no sign" on other computers for that long.
    w.beat_timer = Timer(_ -> beat_now!(w), 5.0; interval=5.0)
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
    for a in file_axes(d)
        ds = a.grows ? live_dataset(ga, a.name, Float64, (0,), (1,)) : write_array(ga, a.name, a.data, false)
        write_str_attr(ds, "unit", a.unit)
        write_str_attr(ds, "label", a.label)
        a.elements === nothing || write_attribute(ds, "elements", String[e for e in a.elements])
        a.role === nothing || write_str_attr(ds, "role", a.role)
    end
    for g in values(d.groups)                    # each level grows as write! adds points
        gg = create_group(ga, g.name)
        write_str_attr(gg, "order", join(g.order, ","))
        for (k, name) in enumerate(g.order)
            ds = live_dataset(gg, name, Float64, (0,), (1,))
            write_str_attr(ds, "unit", d.axes[name].unit)
            write_str_attr(ds, "label", d.axes[name].label)
            k > 1 && live_dataset(gg, name * "._parent", Int64, (0,), (1,))
        end
    end
    gv = create_group(f, "values")
    masks = String[]
    for v in values(d.values)
        grows = growing_dims(d, v)
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
        write_str_attr(ds, "axes", join(vcat(v.axes, point_names(v)), ","))
        T === Bool && write_attribute(ds, "lbd_bool", Int64(1))
    end
    if !isempty(masks)
        gm = create_group(f, "measured")
        for name in masks
            v = d.values[name]
            live_dataset(gm, name, UInt8, v.shape, growing_dims(d, v))
        end
    end
    write_meta(create_group(f, "meta"), d.meta, "meta")
end

# The dimensions of `v` that grow while it is written: a growing axis, a group's level.
growing_dims(d::Dataset, v::Value) =
    Tuple(i for (i, dm) in enumerate(v.dims) if d.axes[dm[end]].grows || d.axes[dm[end]].group !== nothing)

# A chunked dataset of logical `shape`, reading NaN (or 0) where nothing was written; `grows`: the
# logical dimensions that are unlimited. HDF5.jl counts dimensions in Julia order (reversed).
function live_dataset(g, name, T, shape, grows)
    isempty(shape) && return create_dataset(g, name, datatype(T), dataspace(()); fill_value=not_measured(T))
    nd = length(shape)
    dims = reverse(Tuple(shape))
    jgrows = [nd - i + 1 for i in grows]              # the same dimensions, in Julia order
    maxd = Tuple(k in jgrows ? -1 : dims[k] for k in 1:nd)
    chunk = collect(max.(dims, 1))
    chunk[jgrows] .= 1
    for k in jgrows
        chunk[k] = max(1, 8192 ÷ max(1, prod(chunk)))
    end
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
function write!(w::Writer, names::AbstractDict=Dict{String,Any}(); parent=nothing, kw...)
    raise_failure(w)
    w.state == :new && start!(w)
    w.state == :writing || throw(LBDError("$(basename(w.path)): the Writer is closed; nothing more can be written"))
    plan = plan_write(w.d, names, kw, parent)
    lock(w.lock) do
        if plan.grow !== nothing
            ax = w.d.axes[plan.grow.axis]
            ax.data = vcat(Float64.(ax.data), plan.grow.coords)
            push!(w.pending, (:grow, plan.grow.axis, plan.grow.coords, length(ax.data)))
        end
        grow_levels!(w.d, plan)                   # the points in memory (lookups), at once
        for (a, c, p) in plan.levels
            push!(w.pending, (:level, a, Float64.(c), p, length(w.d.axes[a].data)))
        end
        counted = Any[]
        for p in plan.puts
            p.data isa AbstractArray && isempty(p.data) && continue    # no points (an (A, B) without C)
            push!(w.pending, (:put, p.name, p.idx, copy(p.data)))   # a copy: the caller may reuse its buffer
            push!(counted, p)
        end
        record!(w.beat, counted)
    end
    beat_now!(w)
    if time() - w.last_flush >= w.flush_every
        flush_pending!(w)
        raise_failure(w)
    else
        flush_soon!(w)
    end
    return plan.result
end

"""Write everything collected so far to the file now (readers see it)."""
function Base.flush(w::Writer)
    raise_failure(w)
    w.state == :writing && flush_pending!(w)
    raise_failure(w)
    return w
end

"""Rewrite the heartbeat file when it is due (live.jl)."""
function beat_now!(w::Writer)
    lock(w.lock) do
        (w.state === :writing && w.beat !== nothing && due(w.beat)) && write_beat!(w.beat)
    end
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
    if item[1] === :grow || item[1] === :level
        g, c, n = item[2], item[3], item[end]
        for v in values(d.values)            # values first: readers cut to the shortest
            for (pos, dm) in enumerate(v.dims)
                dm[end] == g || continue
                extend!(f["values"][v.name], n, pos, length(v.shape))
                haskey(f, "measured") && haskey(f["measured"], v.name) && extend!(f["measured"][v.name], n, pos, length(v.shape))
            end
        end
        where = d.axes[g].group === nothing ? f["axes"] : f["axes"][d.axes[g].group]
        if item[1] === :level && item[4] !== nothing
            par = where[g * "._parent"]
            extend!(par, n)
            par[(n - length(c) + 1):n] = Int64.(item[4]) .- 1          # from 0 in the file
        end
        ds = where[g]
        extend!(ds, n)
        ds[(n - length(c) + 1):n] = c
    else
        _, name, idx, data = item
        v = d.values[name]
        shape = (Tuple(dim_length(d, dm) for dm in v.dims)..., v.point_shape...)
        put!(f["values"][name], idx, eltype(data) === Bool || data isa Bool ? UInt8.(data) : data, shape)
        if haskey(f, "measured") && haskey(f["measured"], name)
            put!(f["measured"][name], idx, data isa Number ? 0x01 : fill(0x01, size(data)), shape)
        end
    end
end

# Grow `ds` to `n` along its logical dimension `pos` (of `nd`); HDF5.jl counts in reversed order.
function extend!(ds, n, pos=1, nd=ndims(ds))
    dims = collect(size(ds))
    dims[nd - pos + 1] = n
    HDF5.set_extent_dims(ds, Tuple(dims))
end

# Write `data` at the logical place `idx` (an index, a range, a vector of indices or `:` per
# dimension) of `ds`.
function put!(ds, idx, data, shape)
    if isempty(idx)
        write_dataset(ds, datatype(typeof(data)), fill(data))
        return
    end
    for (k, i) in enumerate(idx)                # indices that aren't one run (points of a group): run by run
        if i isa AbstractVector && length(i) > 1 && any(!=(1), diff(i))
            ranges = [j isa Colon ? (1:shape[m]) : j isa Integer ? (j:j) : j for (m, j) in enumerate(idx)]
            block = reshape(data isa Number ? [data] : data, Tuple(length.(ranges)))
            stops = vcat(findall(!=(1), diff(i)), length(i))
            start = 1
            for stop in stops
                sub = copy(idx)
                sub[k] = i[start:stop]
                sel = [m == k ? (start:stop) : Colon() for m in 1:length(idx)]
                put!(ds, sub, block[sel...], shape)
                start = stop + 1
            end
            return
        end
    end
    ranges = [i isa Colon ? (1:shape[k]) : i isa Integer ? (i:i) : (first(i):last(i)) for (k, i) in enumerate(idx)]   # one run each
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
                who = who_has_open(w.writing_path)
                throw(LBDError("the measurement is complete, but $(isempty(who) ? "another program" : who) kept $(w.writing_path) open for " *
                               "$(FINISH_WAIT) s, so it couldn't be renamed to $(basename(target)). Close it there, then " *
                               "rename it yourself or use LBD.recover"))
            end
            sleep(0.1)
        end
    end
    w.state = :finished
    w.path = target
    w.beat === nothing || remove_beat(w.beat)
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
    w.beat_timer === nothing || close(w.beat_timer)
    w.beat_timer = nothing
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
    # fcntl is variadic: its third argument must be passed as one (on Apple silicon it goes on the
    # stack, not in a register, and a plain ccall made every lock fail there).
    l = Ref(flock_of(F_WRLCK))
    r = GC.@preserve l @ccall fcntl(fd(io)::Cint, F_SETLK::Cint; Base.unsafe_convert(Ptr{Flock}, l)::Ptr{Flock})::Cint
    return r == 0
end

function take_guard(path)
    io = Base.open(path, "r+")
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
        Base.open(p, "r+")
    catch
        Base.open(p, "r")
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
        GC.@preserve l (@ccall fcntl(fd(io)::Cint, F_GETLK::Cint; Base.unsafe_convert(Ptr{Flock}, l)::Ptr{Flock})::Cint) == 0 ||
            throw(Base.SystemError("fcntl"))
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
            e isa Base.IOError || rethrow()
            if time() > deadline
                who = who_has_open(src)
                throw(LBDError("recovered $(basename(target)), but can't remove $(basename(src)): " *
                               "$(isempty(who) ? "another program" : who) keeps it open"))
            end
            sleep(0.1)
        end
    end
    rm(live_path(src); force=true)              # its heartbeat, left by the crash
    return target
end
