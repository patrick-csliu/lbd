# The heartbeat file name.lbd.live of a measurement (spec §7, plan 9): which computer and program
# measure and how far they are, rewritten at least every BEAT_EVERY seconds, so another computer
# (through a sync tool) can tell "measuring there" from "stopped" by when it saw the file change.
#
# Each value's sweep dimensions written one position at a time (the "stepped" ones, e.g. power)
# get a small array of how much of each position was written; the dimensions given whole in a
# write (a trace along frequency) count as `per_write`. So every point is counted once, without a
# mask as large as the value.

const BEAT_EVERY = 30.0     # seconds: rewritten at least this often
const LIVE_EVERY = 5.0      # and at most this often when the progress changed
const RATE_WINDOW = 300.0   # seconds of recent progress the rate is taken from
const MASK_LIMIT = 10_000_000

mutable struct ValueProgress
    names::Vector{String}
    lengths::Vector{Union{Int,Nothing}}    # nothing: a growing axis or a group's level
    total::Union{Int,Nothing}
    points::Int
    stepped::Union{Vector{Int},Nothing}
    per_write::Int
    mask::Union{Array{Float32},Nothing}
    axes::Dict{Int,Vector{Float64}}          # index, steps, first, last
    samples::Vector{Tuple{Float64,Int}}
end

function ValueProgress(d, v)
    names = [dim[end] for dim in v.dims]
    lengths = Union{Int,Nothing}[(ax = d.axes[n]; ax.grows || ax.group !== nothing ? nothing : length(ax.data)) for n in names]
    total = any(isnothing, lengths) ? nothing : prod(Int[l for l in lengths]; init=1)
    return ValueProgress(names, lengths, total, 0, nothing, 1, nothing, Dict{Int,Vector{Float64}}(), Tuple{Float64,Int}[])
end

count_cells(k::Integer, n) = 1
count_cells(::Colon, n) = n === nothing ? 0 : n
count_cells(k, n) = length(k)

function add_write!(vp::ValueProgress, idx, t::Float64)
    nd = length(vp.lengths)
    sweep = idx[1:nd]
    if vp.stepped === nothing
        vp.stepped = [i for i in 1:nd if sweep[i] isa Integer]
        if vp.total !== nothing
            others = setdiff(1:nd, vp.stepped)
            vp.per_write = prod(Int[vp.lengths[i] for i in others]; init=1)
            shape = Tuple(Int(vp.lengths[i]) for i in vp.stepped)
            prod(shape; init=1) <= MASK_LIMIT && (vp.mask = zeros(Float32, shape...))
        end
    end
    c = [count_cells(sweep[i], vp.lengths[i]) for i in 1:nd]
    written = prod(c; init=1)
    if vp.mask !== nothing
        sel = Any[sweep[i] for i in vp.stepped]
        others = prod(Int[c[i] for i in 1:nd if !(i in vp.stepped)]; init=1)
        view_ = isempty(sel) ? vp.mask : view(vp.mask, sel...)
        before = sum(view_)
        view_ .= min.(view_ .+ Float32(others / max(vp.per_write, 1)), 1f0)
        vp.points = min(round(Int, vp.points + (sum(view_) - before) * vp.per_write), vp.total)
    elseif vp.total !== nothing
        vp.points = min(vp.points + written, vp.total)
    else
        vp.points += written
    end
    for i in vp.stepped
        k = sweep[i]
        (k isa Integer && vp.lengths[i] !== nothing) || continue
        a = get!(vp.axes, i, [NaN, 0.0, NaN, NaN])
        if a[1] != k - 1                          # from 0, as in every language's file
            isnan(a[1]) ? (a[3] = t) : (a[2] += 1; a[4] = t)
            a[1] = k - 1
        end
    end
    push!(vp.samples, (t, vp.points))
    while length(vp.samples) > 2 && t - vp.samples[2][1] > RATE_WINDOW
        popfirst!(vp.samples)
    end
end

json_text(x::Nothing) = "null"
json_text(x::Bool) = x ? "true" : "false"
json_text(x::Integer) = string(x)
json_text(x::AbstractFloat) = isfinite(x) ? string(round(x; digits=6)) : "null"
function json_text(s::AbstractString)
    out = IOBuffer()
    print(out, '"')
    for ch in s
        if ch == '"' || ch == '\\'
            print(out, '\\', ch)
        elseif ch < ' '
            print(out, "\\u", string(UInt16(ch); base=16, pad=4))
        else
            print(out, ch)
        end
    end
    print(out, '"')
    return String(take!(out))
end
json_text(v::AbstractVector) = "[" * join(json_text.(v), ", ") * "]"
json_text(p::Pair) = json_text(string(p.first)) * ": " * json_text(p.second)
json_text(d::Vector{<:Pair}) = "{" * join(json_text.(d), ", ") * "}"     # keys in this order

function info(vp::ValueProgress)
    rate = nothing
    if length(vp.samples) >= 2 && vp.samples[end][1] > vp.samples[1][1]
        rate = (vp.samples[end][2] - vp.samples[1][2]) / (vp.samples[end][1] - vp.samples[1][1])
    end
    axes = Vector{Pair{String,Any}}[]
    for i in sort(collect(keys(vp.axes)))
        a = vp.axes[i]
        step = a[2] > 0 ? (a[4] - a[3]) / a[2] : nothing
        push!(axes, ["name" => vp.names[i], "index" => Int(a[1]), "length" => vp.lengths[i], "step_seconds" => step])
    end
    return Pair{String,Any}["points" => vp.points, "total" => vp.total, "per_write" => vp.per_write,
                            "rate" => rate, "axes" => axes]
end

mutable struct Heartbeat
    path::String
    d::Any
    program::String
    computer::String
    started::String
    clock0::Float64
    values::Dict{String,ValueProgress}
    changed::Bool
    last_written::Union{Float64,Nothing}
    last_call::Union{Float64,Nothing}
    longest_gap::Float64
    failed::Bool
end

live_path(writing_path::AbstractString) = (endswith(lowercase(writing_path), ".writing") ?
    writing_path[1:end-length(".writing")] : writing_path) * ".live"
local_time_text() = Dates.format(now(), dateformat"yyyy-mm-ddTHH:MM:SS") * utc_offset()
clock_now(b::Heartbeat) = time() - b.clock0

Heartbeat(writing_path, d, program) = Heartbeat(live_path(writing_path), d, program, gethostname(), local_time_text(),
                                                 time(), Dict{String,ValueProgress}(), true, nothing, nothing, 0.0, false)

function record!(b::Heartbeat, puts)
    t = clock_now(b)
    b.last_call === nothing || (b.longest_gap = max(b.longest_gap, t - b.last_call))
    b.last_call = t
    for p in puts
        vp = get!(() -> ValueProgress(b.d, b.d.values[p.name]), b.values, p.name)
        add_write!(vp, p.idx, t)
    end
    b.changed = true
end

function due(b::Heartbeat)
    t = clock_now(b)
    b.last_written === nothing && return true
    return t - b.last_written >= BEAT_EVERY || (b.changed && t - b.last_written >= LIVE_EVERY)
end

function write_beat!(b::Heartbeat)
    b.last_written = clock_now(b)
    b.changed = false
    content = Pair{String,Any}["lbd_live" => 1, "computer" => b.computer, "process" => getpid(), "program" => b.program,
                               "started" => b.started, "updated" => local_time_text(), "beat_every" => BEAT_EVERY,
                               "longest_gap" => b.longest_gap,
                               "values" => Pair{String,Any}[n => info(vp) for (n, vp) in b.values]]
    tmp = b.path * ".tmp"
    try
        write(tmp, json_text(content))
        mv(tmp, b.path; force=true)
    catch e
        if !b.failed
            b.failed = true
            @warn "$(basename(b.path)) (how far the measurement is, for other computers) can't be written: " *
                  "$(sprint(showerror, e)); the measurement goes on"
        end
        rm(tmp; force=true)
    end
end

remove_beat(b::Heartbeat) = (rm(b.path; force=true); rm(b.path * ".tmp"; force=true))
