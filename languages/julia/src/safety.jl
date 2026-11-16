# A save never loses the data (plan 17, part F): settings checked when they are set; a setting
# that can't be stored left out at save (with a warning, its text kept in /extra/not_saved);
# data that can't make a valid file kept in `name.lbd.rescue`; `check` and a dry run before
# measuring.

"A setting a save left out: where it is (\"meta/vna/ifbw\", \"plot\"), its text, and why."
const LeftOut = NamedTuple{(:where, :value, :reason),Tuple{String,String,String}}
"Something `check` (or a dry run) found: where, what, and how to fix it."
const Problem = NamedTuple{(:where, :what, :fix),Tuple{String,String,String}}

shown(x) = (t = x isa AbstractString ? String(x) : repr(x); length(t) <= 2000 ? t : first(t, 2000) * " …")

# The metadata that can be stored, tried item by item in a scratch file; the others go to `left`.
function storable_meta(meta, where::String, scratch, left::Vector{LeftOut})
    out = OrderedDict{String,Any}()
    for (k, val) in meta
        key = string(k)
        w = "$where/$key"
        try
            (isempty(key) || occursin('/', key)) && throw(LBDError("$where: invalid meta key \"$key\""))
            if val isa AbstractDict || val isa NamedTuple
                out[key] = storable_meta(val isa NamedTuple ? OrderedDict(pairs(val)) : val, w,
                                         create_group(scratch, key), left)
            else
                write_meta_attr(scratch, key, val, w)
                out[key] = val
            end
        catch e
            (e isa LBDError || e isa ArgumentError || e isa MethodError || e isa HDF5.API.H5Error) || rethrow()
            push!(left, (where=w, value=shown(val), reason=sprint(showerror, e)))
        end
    end
    return out
end

function with_scratch(f)
    h5open(tempname() * ".h5", "w"; driver=HDF5.Drivers.Core(; backing_store=false)) do scratch
        f(scratch)
    end
end

"Check metadata as `d.meta = …` gives it: the first item that can't be stored is an error."
function check_meta(meta)
    meta isa AbstractDict || throw(LBDError("meta must be a Dict, not $(typeof(meta))"))
    left = LeftOut[]
    with_scratch(s -> storable_meta(meta, "meta", create_group(s, "meta"), left))
    isempty(left) || throw(LBDError(left[1].reason))
end

json_or_error(x, what) = try
    JSON3.write(x)
catch e
    throw(LBDError("$what can't be stored as JSON: $(sprint(showerror, e))"))
end

# The settings as they are written; those that can't be stored are left out.
function storable_settings(d::Dataset)
    left = LeftOut[]
    meta = with_scratch(s -> storable_meta(d.meta, "meta", create_group(s, "meta"), left))
    texts = Dict{String,Union{String,Nothing}}()
    for (key, x) in (("plot", d.plot), ("style", d.style))
        texts[key] = nothing
        x === nothing && continue
        try
            texts[key] = json_or_error(x, key)
        catch e
            e isa LBDError || rethrow()
            push!(left, (where=key, value=shown(x), reason=e.msg))
        end
    end
    return (meta=meta, plot=texts["plot"], style=texts["style"], left_out=left)
end

# The data as it is now (values and axes changed by hand): the first problem, or nothing.
function data_problem(d::Dataset)
    for a in values(d.axes)
        a.grows && isempty(a.data) && return "the growing axis \"$(a.name)\" has no points yet; write some before saving"
    end
    for v in values(d.values)
        v.data === nothing && return "value \"$(v.name)\" was not loaded; load the file without `values=` to re-save it"
        got = v.data isa AbstractArray ? Tuple(size(v.data)) : ()
        got == Tuple(v.shape) ||
            return "value \"$(v.name)\": its data has size $got, but its axes give $(Tuple(v.shape))"
    end
    try
        validate_loaded(d)
    catch e
        e isa LBDError || rethrow()
        return e.msg
    end
    return nothing
end

"""
    LBD.check(d) -> Vector of (where, what, fix)

What a save would refuse or leave out, without writing anything; empty if everything can be
saved. Never throws. Run it before a long measurement.
"""
function check(d::Dataset)
    problems = Problem[]
    try
        p = data_problem(d)
        p === nothing || push!(problems, (where="data", what=p, fix="fix it before saving; a save would keep the data in name.lbd.rescue and throw"))
        for l in storable_settings(d).left_out
            push!(problems, (where=l.where, what=l.reason, fix="change or remove it; a save would leave it out"))
        end
    catch e
        push!(problems, (where="data", what=sprint(showerror, e), fix="fix it before saving"))
    end
    return problems
end

function dry_run(path::AbstractString, d::Dataset)
    problems = check(d)
    folder = dirname(abspath(path))
    if !isdir(folder)
        push!(problems, (where="path", what="the folder $folder doesn't exist", fix="make it, or save elsewhere"))
    else
        need = sum((sizeof(a.data) for a in values(d.axes)); init=0) +
               sum((v.data isa AbstractArray ? sizeof(v.data) : 8 for v in values(d.values) if v.data !== nothing); init=0)
        free = diskstat(folder).available
        free < need * 1.1 + 2^20 && push!(problems, (where="path", what="the disk has $(free ÷ 2^20) MB free; the file needs about $(need ÷ 2^20) MB",
                                                      fix="free some room, or save elsewhere"))
    end
    return (path=String(path), left_out=LeftOut[], problems=problems)
end

const RESCUE_SUFFIX = ".rescue"

# Everything given, as it is (no LBD rules), so a save that can't make a valid file loses nothing.
function write_rescue(d::Dataset, path::AbstractString, error::AbstractString)
    target = path * RESCUE_SUFFIX
    k = 2
    while ispath(target)
        target = "$path.$k$RESCUE_SUFFIX"
        k += 1
    end
    h5open(target, "w") do f
        write_attribute(f, "lbd_rescue", 1)
        write_str_attr(f, "error", error)
        for (key, x) in (("title", d.title), ("description", d.description), ("created", d.created))
            write_str_attr(f, key, shown(something(x, "")))
        end
        for (key, x) in (("meta", d.meta), ("plot", d.plot), ("style", d.style))
            write_str_attr(f, key, try JSON3.write(x) catch; JSON3.write(shown(x)) end)
        end
        for (kind, items) in (("axes", d.axes), ("values", d.values))
            g = create_group(f, kind)
            for (i, (name, item)) in enumerate(items)
                data = item.data
                ds_name = string(i)
                try
                    write_dataset(g, ds_name, to_file(data isa AbstractArray ? collect(data) : [data]))
                catch
                    write_dataset(g, ds_name, shown(data))
                end
                ds = g[ds_name]
                write_str_attr(ds, "name", String(name))
                write_str_attr(ds, "unit", item.unit)
                item isa Value && write_str_attr(ds, "axes", JSON3.write(item.axes))
            end
        end
    end
    return target
end

function read_rescue(path::AbstractString)
    h5open(path, "r") do f
        haskey(attributes(f), "lbd_rescue") || throw(LBDError("$(basename(path)) is not a rescue file written by LBD"))
        out = Dict{String,Any}(k => attr_str(f, k) for k in ("error", "title", "description", "created"))
        for k in ("meta", "plot", "style")
            out[k] = JSON3.read(attr_str(f, k, "null"))
        end
        for kind in ("axes", "values")
            items = OrderedDict{String,Any}()
            for i in sort(collect(keys(f[kind])); by=x -> parse(Int, x))
                ds = f[kind][i]
                raw = read(ds)
                items[attr_str(ds, "name", i)] = Dict{String,Any}(
                    "data" => raw isa AbstractString ? raw : from_file(raw), "unit" => attr_str(ds, "unit"),
                    "axes" => haskey(attributes(ds), "axes") ? String.(JSON3.read(attr_str(ds, "axes"))) : String[])
            end
            out[kind] = items
        end
        return out
    end
end
