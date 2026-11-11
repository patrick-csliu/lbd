# Labels of a data file (spec §1.9): a star, a project, users, tags and a comment, stored in the
# file's /labels group so they go wherever the file goes; `written` is when they were set.

const LABEL_KEYS = (:star, :project, :users, :tags, :comment)

"A label time: UTC with milliseconds, e.g. \"2026-11-11T09:30:00.125Z\" (texts sort as times)."
label_time() = Dates.format(Dates.now(Dates.UTC), "yyyy-mm-ddTHH:MM:SS.sss") * "Z"

"A label as stored: the parts of a nested label (\"Chip 3/Cooldown 7\") without spaces around the slashes."
function clean_label(label, what)
    label isa AbstractString || throw(LBDError("$what: a label must be text, not $(typeof(label)) ($(repr(label)))"))
    parts = strip.(split(label, "/"))
    any(isempty, parts) && throw(LBDError("$what: \"$label\" is empty or has an empty part; write labels like \"Qubit A/Device 3\""))
    return String(join(parts, "/"))
end

function clean_labels(items, what)
    items isa AbstractString && throw(LBDError("$what: give a list of labels, e.g. [\"$items\"], not one text"))
    items isa Union{AbstractVector,Tuple,AbstractSet} || throw(LBDError("$what: give a list of labels, not $(typeof(items))"))
    out = unique(String[clean_label(x, what) for x in items])
    return sort!(out; by=lowercase)
end

"""
    Labels(; star=false, project=nothing, users=String[], tags=String[], comment="")

A file's labels, as LBD Viewer's Library shows them. `d.labels` of every `Dataset` (and
`Writer`) is one. Each change is checked at once and sets `written` (when they were set, UTC):

    d.labels.star = true
    d.labels.tags = ["calibration"]
    add_tags!(d, "Chip 3/Cooldown 7")
    d.labels = (project="Cooldown 7", users=["Ana"])
"""
mutable struct Labels
    star::Bool
    project::Union{String,Nothing}
    users::Vector{String}
    tags::Vector{String}
    comment::String
    written::Union{String,Nothing}
end

function Labels(; star=false, project=nothing, users=String[], tags=String[], comment="")
    l = Labels(false, nothing, String[], String[], "", nothing)
    for (k, v) in ((:star, star), (:project, project), (:users, users), (:tags, tags), (:comment, comment))
        set_label!(l, k, v)
    end
    setfield!(l, :written, has_labels_set(l) ? label_time() : nothing)
    return l
end

has_labels_set(l::Labels) = l.star || l.project !== nothing || !isempty(l.users) || !isempty(l.tags) || !isempty(l.comment)
"Whether the file gets a /labels group: labels set, or set and all removed again."
has_labels(l::Labels) = has_labels_set(l) || l.written !== nothing

function set_label!(l::Labels, s::Symbol, x)
    if s === :star
        x isa Bool || throw(LBDError("labels.star must be true or false, not $(repr(x))"))
        setfield!(l, :star, x)
    elseif s === :project
        setfield!(l, :project, x === nothing || x == "" ? nothing : clean_label(x, "labels.project"))
    elseif s === :users || s === :tags
        setfield!(l, s, clean_labels(x, "labels.$s"))
    elseif s === :comment
        x isa AbstractString || throw(LBDError("labels.comment must be text, not $(typeof(x))"))
        setfield!(l, :comment, String(x))
    elseif s === :written
        setfield!(l, :written, x === nothing ? nothing : String(x))
        return
    else
        throw(LBDError("labels: no label \"$s\"; the labels are star, project, users, tags, comment"))
    end
end

function Base.setproperty!(l::Labels, s::Symbol, x)
    set_label!(l, s, x)
    s === :written || setfield!(l, :written, label_time())
    return x
end

Base.:(==)(a::Labels, b::Labels) = all(getfield(a, k) == getfield(b, k) for k in LABEL_KEYS)
Base.copy(l::Labels) = Labels(l.star, l.project, copy(l.users), copy(l.tags), l.comment, l.written)
Base.show(io::IO, l::Labels) = print(io, "Labels(", join(("$k=$(repr(getfield(l, k)))" for k in LABEL_KEYS
    if !(getfield(l, k) in (false, nothing, "", String[]))), ", "), ")")

"`x` as Labels: Labels (copied), a NamedTuple or Dict with the keys star, project, users, tags, comment, or nothing."
function as_labels(x)
    x === nothing && return Labels()
    x isa Labels && return copy(x)
    pairs_ = x isa NamedTuple ? pairs(x) : x isa AbstractDict ? x :
        throw(LBDError("labels must be a NamedTuple like (tags=[\"calibration\"], star=true), a Dict or LBD.Labels, not $(typeof(x))"))
    kw = Dict{Symbol,Any}(Symbol(k) => v for (k, v) in pairs_)
    unknown = setdiff(keys(kw), LABEL_KEYS)
    isempty(unknown) || throw(LBDError("labels: unknown key(s) $(join(sort!(String.(collect(unknown))), ", ")); " *
                                       "the labels are star, project, users, tags, comment"))
    return Labels(; kw...)
end

"""
    add_tags!(d, tags...)

Add tags to the file's labels: `add_tags!(d, "calibration", "Chip 3/Cooldown 7")`.
"""
function add_tags!(d, tags::AbstractString...)
    l = d.labels
    l.tags = vcat(l.tags, collect(tags))
    return l
end

# ---- in the file ----------------------------------------------------------------------------------

function write_labels(f, l::Labels)
    haskey(f, "labels") && delete_object(f, "labels")
    has_labels(l) || return
    # checked again: a label pushed onto the vectors directly (push!(d.labels.tags, …)) is checked here
    users, tags = clean_labels(l.users, "labels.users"), clean_labels(l.tags, "labels.tags")
    g = create_group(f, "labels")
    write_attribute(g, "star", Int8(l.star))
    l.project === nothing || write_str_attr(g, "project", l.project)
    write_str_attr(g, "users", JSON3.write(users))
    write_str_attr(g, "tags", JSON3.write(tags))
    write_str_attr(g, "comment", l.comment)
    write_str_attr(g, "written", something(l.written, label_time()))
end

function read_labels(f, path)
    l = Labels()
    haskey(f, "labels") || return l
    g = f["labels"]
    if !(g isa HDF5.Group)
        @warn "$(basename(path)): /labels is not a group; reading the file without its labels"
        return l
    end
    for key in ("star", "project", "users", "tags", "comment")
        haskey(attributes(g), key) || continue
        try
            if key == "star"
                raw = read_attribute(g, key)
                (raw isa Integer && raw in (0, 1)) || throw(LBDError("expected 0 or 1, got $(repr(raw))"))
                set_label!(l, :star, raw == 1)
            elseif key in ("users", "tags")
                items = JSON3.read(attr_str(g, key))
                items isa JSON3.Array || throw(LBDError("expected a JSON list of labels"))
                set_label!(l, Symbol(key), collect(items))
            else
                set_label!(l, Symbol(key), attr_str(g, key))
            end
        catch e
            (e isa LBDError || e isa ArgumentError) || rethrow()
            @warn "$(basename(path)): the label '$key' can't be read ($(sprint(showerror, e))); reading the file without it"
        end
    end
    w = attr_str(g, "written")
    setfield!(l, :written, isempty(w) ? nothing : w)
    return l
end

const LABELS_MINOR = Dict(1 => 3, 2 => 1)   # the first minor version with labels, per major version

"The format version of a file once it has labels: 1.3 from 1.0 to 1.2, 2.1 from 2.0 (spec §6)."
function labels_version(ver)
    major, minor = parse.(Int, split(ver, "."))
    return minor < LABELS_MINOR[major] ? "$major.$(LABELS_MINOR[major])" : String(ver)
end

function write_labels_in_place(f, l::Labels)
    if has_labels(l)
        ver = attr_str(f, "lbd_version")
        new = labels_version(ver)
        if new != ver
            delete_attribute(f, "lbd_version")
            write_str_attr(f, "lbd_version", new)
        end
    end
    write_labels(f, l)
end

# ---- on an existing file -----------------------------------------------------------------------

function edit_labels(change, path::AbstractString, what)
    endswith(lowercase(path), ".writing") && throw(LBDError(
        "$(basename(path)) is still being written: $what can't change it. Labels given to the LBD.Writer " *
        "(w.labels) are written when it finishes; or change the finished file"))
    lowercase(splitext(path)[2]) == ".lbd" || @warn "$(basename(path)): LBD files should use the .lbd extension"
    isfile(path) || throw(LBDError("no such file: $path"))
    h5open(path, "r+") do f
        attr_str(f, "lbd_format") == "LBD" || throw(LBDError("$(basename(path)) is not an LBD file (missing lbd_format=\"LBD\")"))
        check_version(attr_str(f, "lbd_version"), path)
        l = read_labels(f, path)
        change(l)
        setfield!(l, :written, label_time())
        write_labels_in_place(f, l)
        return l
    end
end

"""
    LBD.labels(path) -> Labels or nothing

The labels stored in a file, or `nothing` if it has none. Reads only the file's description.
"""
function labels(path::AbstractString)
    isfile(path) || throw(LBDError("no such file: $path"))
    h5open(path, "r") do f
        attr_str(f, "lbd_format") == "LBD" || throw(LBDError("$(basename(path)) is not an LBD file (missing lbd_format=\"LBD\")"))
        check_version(attr_str(f, "lbd_version"), path)
        haskey(f, "labels") || return nothing
        return read_labels(f, path)
    end
end

"""
    LBD.set_labels(path; star=, project=, users=, tags=, comment=, replace=false) -> Labels

Change the labels of an existing file; the data is not touched or rewritten. Only what is given
changes; tags and users are added to the file's, or with `replace=true` replace them. Works on
any `.lbd` file, with or without LBD Viewer.

    LBD.set_labels("sweep.lbd"; tags=["calibration"], star=true)
"""
function set_labels(path::AbstractString; replace::Bool=false, kw...)
    isempty(kw) && throw(LBDError("set_labels needs at least one of star=, project=, users=, tags=, comment="))
    as_labels(NamedTuple(kw))                       # every label checked before the file is opened
    return edit_labels(path, "set_labels") do l
        for (k, v) in kw
            if k in (:users, :tags) && !replace
                set_label!(l, k, vcat(getfield(l, k), collect(v)))
            else
                set_label!(l, k, v)
            end
        end
    end
end

"""
    LBD.remove_labels(path; tags=String[], users=String[]) -> Labels

Remove tags and users from an existing file's labels; a label it doesn't have is ignored.
"""
function remove_labels(path::AbstractString; tags=String[], users=String[])
    probe = Labels(; tags=tags, users=users)        # checked before the file is opened
    return edit_labels(path, "remove_labels") do l
        set_label!(l, :tags, setdiff(l.tags, probe.tags))
        set_label!(l, :users, setdiff(l.users, probe.users))
    end
end
