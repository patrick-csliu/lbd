using LBD
using HDF5
using Test
using Dates
using Random

function make_sweep()
    f = collect(range(4e9, 8e9, 41))
    p = collect(-40.0:4:0)
    s21 = exp.(1im .* (p * f') .* 1e-10)          # size (11, 41) = (power, freq)
    d = LBD.Dataset("Resonator power sweep"; description="test")
    add_axis!(d, "power", p; unit="dBm", label="Power")
    add_axis!(d, "freq", f; unit="Hz", label="Frequency")
    add_value!(d, "S21", s21, ["power", "freq"])
    add_value!(d, "mag", abs.(s21), "power,freq"; label="|S21|")
    return d
end

@testset "LBD.jl" begin
    dir = mktempdir()

    @testset "round trip" begin
        d = make_sweep()
        p = LBD.save(joinpath(dir, "sweep.lbd"), d)
        r = LBD.load(p)
        @test r.title == "Resonator power sweep"
        @test r.description == "test"
        @test r.writer == "julia LBD $(LBD.version().package)"
        @test r["power"].data == d["power"].data
        @test r["freq"].unit == "Hz"
        @test r["S21"].axes == ["power", "freq"]
        @test size(r["S21"].data) == (11, 41)
        @test eltype(r["S21"].data) == ComplexF64
        @test r["S21"].data == d["S21"].data
        @test r["mag"].label == "|S21|"
    end

    @testset "layout and dimension order on disk" begin
        p = joinpath(dir, "sweep.lbd")
        h5open(p) do f
            # On disk the logical order is (power, freq) = C order, so HDF5.jl sees it reversed.
            @test size(f["values/S21"]) == (41, 11)
            @test HDF5.API.h5t_is_variable_str(HDF5.datatype(attributes(f)["title"]))
            @test read_attribute(f["values/S21"], "axes") == "power,freq"
            t = HDF5.datatype(f["values/S21"])
            @test HDF5.API.h5t_get_class(t) == HDF5.API.H5T_COMPOUND
        end
    end

    @testset "dtypes" begin
        d = LBD.Dataset()
        add_axis!(d, "x", 1:5)
        add_value!(d, "i16", Int16.(1:5), "x")
        add_value!(d, "f32", Float32.(1:5), "x")
        add_value!(d, "c64", ComplexF32.(1:5), "x")
        add_value!(d, "mask", [true, false, true, false, true], "x")
        add_value!(d, "forced", 1:5, "x"; dtype=Float32)
        add_value!(d, "half", Float16.(1:5), "x")
        r = LBD.load(LBD.save(joinpath(dir, "t.lbd"), d))
        @test eltype(r["i16"].data) == Int16
        @test eltype(r["f32"].data) == Float32
        @test eltype(r["c64"].data) == ComplexF32
        @test r["mask"].data == [true, false, true, false, true]
        @test eltype(r["mask"].data) == Bool
        @test eltype(r["forced"].data) == Float32
        @test eltype(r["half"].data) == Float32
    end

    @testset "scalar value" begin
        d = LBD.Dataset()
        add_value!(d, "fit_Q", 12345.6)
        r = LBD.load(LBD.save(joinpath(dir, "s.lbd"), d))
        @test r["fit_Q"].axes == String[]
        @test r["fit_Q"].data ≈ 12345.6
    end

    @testset "3-D order" begin
        d = LBD.Dataset()
        add_axis!(d, "a", 1:2); add_axis!(d, "b", 1:3); add_axis!(d, "c", 1:4)
        A = reshape(collect(1.0:24), 2, 3, 4)
        add_value!(d, "A", A, ["a", "b", "c"])
        r = LBD.load(LBD.save(joinpath(dir, "3d.lbd"), d))
        @test r["A"].data == A
        @test r["A"].shape == (2, 3, 4)
    end

    @testset "meta" begin
        d = LBD.Dataset()
        d.meta["T_mK"] = 12
        d.meta["sample"] = "R7 – chip 3"
        d.meta["gain"] = 1.5
        d.meta["flag"] = true
        d.meta["z"] = 1 + 2im
        d.meta["vec"] = [1.0, 2.0, 3.0]
        d.meta["mat"] = [0.0 1 2; 3 4 5]
        d.meta["names"] = ["a", "b"]
        d.meta["vna"] = Dict("ifbw_Hz" => 1000.0, "averages" => 4, "port" => Dict("n" => 2))
        m = LBD.load(LBD.save(joinpath(dir, "m.lbd"), d)).meta
        @test m["T_mK"] == 12
        @test m["sample"] == "R7 – chip 3"
        @test m["gain"] == 1.5
        @test m["flag"] == 1
        @test m["z"] == 1 + 2im
        @test m["vec"] == [1.0, 2.0, 3.0]
        @test m["mat"] == [0.0 1 2; 3 4 5]
        @test m["names"] == ["a", "b"]
        @test m["vna"]["averages"] == 4
        @test m["vna"]["port"]["n"] == 2
    end

    @testset "plot and style" begin
        d = make_sweep()
        d.plot = Dict{String,Any}("kind" => "heatmap", "values" => ["S21"], "complex" => "db")
        d.style = Dict{String,Any}("figure" => Dict{String,Any}("width_mm" => 120))
        d.style_name = "thesis"
        d.matplotlib = "3.10.1"
        r = LBD.load(LBD.save(joinpath(dir, "p.lbd"), d))
        @test r.plot["kind"] == "heatmap"
        @test r.plot["values"] == ["S21"]
        @test r.style["figure"]["width_mm"] == 120
        @test r.style_name == "thesis"
        @test r.matplotlib == "3.10.1"            # kept as is through a Julia save
        @test LBD.load(LBD.save(joinpath(dir, "p2.lbd"), r)).matplotlib == "3.10.1"
    end

    @testset "info, partial load, compression" begin
        p = joinpath(dir, "sweep.lbd")
        i = LBD.info(p)
        @test i["S21"].data === nothing
        @test i["S21"].shape == (11, 41)
        @test i["S21"].dtype == "complex128"
        part = LBD.load(p; values=["mag"])
        @test part["mag"].data !== nothing && part["S21"].data === nothing
        @test_throws KeyError LBD.load(p; values=["nope"])

        d = LBD.Dataset()
        add_axis!(d, "x", 1:100); add_axis!(d, "y", 1:200)
        add_value!(d, "z", zeros(100, 200), ["x", "y"])
        pc = LBD.save(joinpath(dir, "c.lbd"), d; compression=true)
        @test LBD.load(pc)["z"].data == zeros(100, 200)
    end

    @testset "validation" begin
        d = LBD.Dataset()
        add_axis!(d, "x", [1.0, 2.0])
        @test_throws LBDError add_axis!(d, "1bad", [1, 2])
        @test_throws LBDError add_axis!(d, "x2", [1 2; 3 4])
        @test_throws LBDError add_value!(d, "v", [1, 2, 3], "x")
        @test_throws LBDError add_value!(d, "v", [1, 2], "nope")
        @test_throws LBDError add_value!(d, "x", [1, 2], "x")
        @test_throws LBDError add_value!(d, "v", ["a", "b"], "x")
        @test_throws LBDError add_value!(d, "v", [1im, 2im], "x"; dtype=Float64)
        d.meta["bad"] = nothing
        @test_throws LBDError LBD.save(joinpath(dir, "bad.lbd"), d)
        @test !isfile(joinpath(dir, "bad.lbd"))
    end

    @testset "created: filled at the first save, kept after, can be set" begin
        d = Dataset("t")
        add_axis!(d, "x", [1.0, 2.0])
        add_value!(d, "y", [1.0, 2.0], ["x"])
        f = joinpath(dir, "created.lbd")
        @test d.created === nothing
        LBD.save(f, d)
        first = d.created
        r = LBD.load(f)
        @test r.created == first
        r.description = "edited later"
        LBD.save(f, r)
        @test LBD.load(f).created == first                       # saved again: kept
        d2 = Dataset("t"; created="2025-03-01T23:30:00+08:00")
        add_axis!(d2, "x", [1.0, 2.0])
        add_value!(d2, "y", [1.0, 2.0], ["x"])
        LBD.save(f, d2)
        @test LBD.load(f).created == "2025-03-01T23:30:00+08:00"
        d2.created = "2024-06-01T12:00:00"                        # no offset: this computer's
        LBD.save(f, d2)
        @test startswith(LBD.load(f).created, "2024-06-01T12:00:00") && length(LBD.load(f).created) == 25
        d2.created = DateTime(2024, 1, 2, 3, 4, 5)
        LBD.save(f, d2)
        @test startswith(LBD.load(f).created, "2024-01-02T03:04:05")
        for bad in ("yesterday", "2025-03-01", "2025-13-01T00:00:00+00:00")
            @test_throws LBDError Dataset("t"; created=bad)
        end
        @test_throws LBDError Dataset("t"; created=20250301)
    end

    @testset "id: made at the first save, kept, new when saved elsewhere" begin
        V7 = r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
        u = LBD.uuid7()
        @test occursin(V7, u)
        ms = parse(Int, replace(u[1:13], "-" => ""); base=16)          # the time field: now
        @test abs(ms / 1000 - Dates.datetime2unix(Dates.now(Dates.UTC))) < 5
        @test length(Set(LBD.uuid7() for _ in 1:10_000)) == 10_000

        mk() = (d = Dataset("t"); add_axis!(d, "x", [1.0, 2.0]); add_value!(d, "y", [1.0, 2.0], ["x"]); d)
        a, b = joinpath(dir, "id_a.lbd"), joinpath(dir, "id_b.lbd")
        d = mk()
        @test d.id === nothing
        LBD.save(a, d)
        first = d.id
        @test occursin(V7, first) && d.parent_id === nothing
        r = LBD.load(a)
        @test r.id == first && r.parent_id === nothing
        r.description = "edited"
        LBD.save(a, r)                                                  # the same file: kept
        @test LBD.load(a).id == first
        LBD.save(b, r)                                                  # another file: new, made from it
        rb = LBD.load(b)
        @test rb.id != first && rb.parent_id == first && r.id == rb.id
        new_id!(r)
        @test r.parent_id == rb.id && r.id != rb.id

        # seeded generators don't make ids repeat
        ids = String[]
        for _ in 1:2
            Random.seed!(0)
            d = mk()
            LBD.save(joinpath(dir, "seeded.lbd"), d)
            push!(ids, d.id)
        end
        @test ids[1] != ids[2]
        # made at once on several threads: all different
        if Threads.nthreads() > 1
            got = Vector{String}(undef, 4000)
            Threads.@threads for i in 1:4000
                got[i] = LBD.uuid7()
            end
            @test length(Set(got)) == 4000
        end

        # a malformed id: a warning, ignored, and saving gives a new one
        h5open(a, "r+") do f
            HDF5.delete_attribute(f, "id")
            attributes(f)["id"] = "not-an-id"
        end
        bad = @test_logs (:warn, r"not a valid id") LBD.load(a)
        @test bad.id === nothing
        LBD.save(a, bad)
        @test occursin(V7, LBD.load(a).id)
    end

    @testset "versions" begin
        p = joinpath(dir, "v.lbd")
        LBD.save(p, make_sweep())
        h5open(p, "r+") do f
            delete_attribute(f, "lbd_version")
            write_attribute(f, "lbd_version", "1.7")
        end
        @test_logs (:warn, r"newer") LBD.load(p)
        h5open(p, "r+") do f
            delete_attribute(f, "lbd_version")
            write_attribute(f, "lbd_version", "2.0")
        end
        @test_throws LBDVersionError LBD.load(p)
        @test LBD.version().lbd_version == "1.2"
    end

    @testset "robust reading" begin
        p = joinpath(dir, "robust.lbd")
        LBD.save(p, make_sweep())
        # one name, not its characters
        r = LBD.load(p; values="S21")
        @test r["S21"].data !== nothing
        @test_throws ArgumentError LBD.load(p; values=[1, 2])
        # a dataset inside /meta and a saved view that isn't a JSON object
        h5open(p, "r+") do f
            f["meta"]["table"] = [1, 2, 3]
            g = create_group(f, "plot")
            write_attribute(g, "spec", "[1, 2]")
        end
        r = @test_logs (:warn, r"/meta/table is a dataset") (:warn, r"must be a JSON object") match_mode=:any LBD.load(p)
        @test r.plot === nothing
        # an HDF5 type LBD doesn't support
        q = joinpath(dir, "strings.lbd")
        LBD.save(q, make_sweep())
        h5open(q, "r+") do f
            f["values"]["names"] = ["a", "b"]
            write_attribute(f["values"]["names"], "axes", "x")
        end
        @test_throws LBDError LBD.load(q)
    end

    @testset "elements of an axis (format 1.2)" begin
        p = joinpath(dir, "elements.lbd")
        d = Dataset("elements")
        add_axis!(d, "state"; elements=["ground", "excited"], label="Prepared state")
        add_axis!(d, "device", [1, 2, 5]; elements=["Q1", "état 1", "量子"])
        add_axis!(d, "one", [7]; elements=["only"])
        add_axis!(d, "t", range(0, 1, length=3))
        add_value!(d, "I", zeros(2, 3), ["state", "t"])
        LBD.save(p, d)
        r = LBD.load(p)
        @test r["state"].elements == ["ground", "excited"]
        @test r["state"].data == [0, 1]
        @test r["device"].elements == ["Q1", "état 1", "量子"]
        @test r["one"].elements == ["only"]
        @test r["t"].elements === nothing && r["t"].role === nothing
        @test r.lbd_version == "1.2"
        @test_throws LBDError add_axis!(d, "x", [0, 1]; elements=["a", "b", "c"])
        @test_throws LBDError add_axis!(d, "y")
    end

    @testset "the shape of a data point (format 1.2)" begin
        p = joinpath(dir, "shape.lbd")
        d = Dataset("shape")
        add_axis!(d, "amp", range(0, 0.5, length=4); unit="V")
        b = reshape(collect(1.0:12.0), 4, 3)
        v = add_value!(d, "bloch", b, "amp"; shape=(3,), elements=["x", "y", "z"])
        @test v.axes == ["amp", "bloch_dim1"]
        @test d.axes["bloch_dim1"].role == "point"
        add_value!(d, "cov", zeros(4, 2, 2), "amp"; shape=(2, 2), elements=[["I", "Q"], nothing])
        LBD.save(p, d)
        r = LBD.load(p)
        @test r["bloch"].data == b
        @test r["bloch"].point_axes == ["bloch_dim1"]
        @test LBD.point_shape(r["bloch"]) == (3,)
        @test r["bloch"].elements == Any[["x", "y", "z"]]
        @test r["cov"].elements == Any[["I", "Q"], nothing]
        @test LBD.point_shape(LBD.info(p)["cov"]) == (2, 2)
        @test_throws LBDError add_value!(d, "r", zeros(4, 3), "amp")              # the shape must be said
        @test_throws LBDError add_value!(d, "r", zeros(3, 4), "amp"; shape=(3,)) # the axes come first
        @test_throws LBDError add_value!(d, "r", zeros(4, 3), "amp"; shape=(3,), elements=["u", "v"])
    end

    function make_planned()
        d = LBD.Dataset("planned")
        add_axis!(d, "power", collect(range(-60.0, 0, 4)); unit="dBm")
        add_axis!(d, "freq", collect(range(6e9, 7e9, 5)); unit="Hz")
        add_axis!(d, "state"; elements=["ground", "excited"])
        add_value!(d, "S21"; axes=["power", "freq"], dtype=ComplexF64)
        add_value!(d, "T"; axes="power")
        add_value!(d, "n"; axes=["state", "power"], dtype=Int32)
        return d
    end

    @testset "write!: filling values piece by piece" begin
        d = make_planned()
        @test all(isnan, d["S21"].data) && size(d["S21"].data) == (4, 5)
        @test d["S21"].measured === nothing
        @test d["n"].measured == falses(2, 4)
        write!(d; power=2, S21=(1:5) .* im, T=4.2)           # a trace and a point
        write!(d; power=3, freq=4, S21=1 + 2im)
        write!(d; state="excited", power=4, n=7)
        write!(d, Dict("state" => 1, "power" => 1); n=3)       # names as a Dict
        @test d["S21"].data[2, :] == (1:5) .* im
        @test d["S21"].data[3, 4] == 1 + 2im && isnan(d["S21"].data[3, 1])
        @test d["T"].data[2] == 4.2
        @test d["n"].data[2, 4] == 7 && count(d["n"].measured) == 2
        p = joinpath(dir, "filled.lbd")
        LBD.save(p, d)
        r = LBD.load(p)
        @test r["n"].measured == d["n"].measured
        @test r["T"].measured === nothing
        @test h5open(f -> collect(keys(f["measured"])), p) == ["n"]
        write!(d; n=ones(Int, 2, 4))                         # now everything is measured
        LBD.save(p, d)
        @test LBD.load(p)["n"].measured === nothing
        # errors, and nothing half written
        @test_throws LBDError write!(d; power=2, S21=ones(4))
        @test_throws LBDError write!(d; power=9, T=1)
        @test_throws LBDError write!(d; power=0, T=1)          # 1-based
        @test_throws LBDError write!(d; freq=1, T=1)
        @test_throws LBDError write!(d; S21=1)
        @test_throws LBDError write!(d; state="mid", power=1, n=1)
        @test_throws LBDError write!(d; state=1, power=1, n=1.5)
        @test_throws LBDError write!(d; power=1, T=1im)
        @test_throws LBDError write!(d; power=1)
        @test_throws LBDError write!(d; nope=1, T=1)
        @test_throws LBDError write!(d, Dict("power" => 1); power=2, T=1)
        @test isnan(d["T"].data[1])
    end

    @testset "write!: a growing axis" begin
        d = LBD.Dataset("log")
        add_axis!(d, "time"; unit="s", grows=true)
        add_axis!(d, "ch", [1, 2])
        add_value!(d, "T"; axes="time")
        add_value!(d, "V"; axes=["time", "ch"])
        add_value!(d, "ok"; axes="time", dtype=Bool)
        @test_throws LBDError add_value!(d, "bad"; axes=["ch", "time"])
        @test_throws LBDError LBD.save(joinpath(dir, "empty.lbd"), d)
        write!(d; time=0.5, T=1, V=[1, 2], ok=true)
        write!(d; time=[1, 1.5], T=[2, 3])
        @test d["time"].data == [0.5, 1, 1.5]
        @test d["T"].data == [1, 2, 3]
        @test all(isnan, d["V"].data[2:3, :])
        @test d["ok"].measured == [true, false, false]
        @test_throws LBDError write!(d; T=1)
        p = joinpath(dir, "log.lbd")
        LBD.save(p, d)
        r = LBD.load(p)
        @test r["time"].data == [0.5, 1, 1.5]
        @test r["ok"].measured == [true, false, false]
    end

    function live_writer(path; kw...)
        w = LBD.Writer(path; title="live", flush_every=60, kw...)
        add_axis!(w, "power", 1:3)
        add_axis!(w, "freq", collect(range(0, 1, 4)))
        add_value!(w, "S21"; axes=["power", "freq"], dtype=ComplexF64)
        add_value!(w, "n"; axes="power", dtype=Int64)
        add_axis!(w, "time"; grows=true)
        add_value!(w, "T"; axes="time")
        return w
    end

    @testset "Writer: writing while measuring" begin
        p = joinpath(dir, "live.lbd")
        w = live_writer(p)
        w.meta["sample"] = "R7"
        write!(w; power=1, S21=(1:4) .+ 1im, n=5)
        write!(w; time=[0, 1], T=[10, 11])
        write!(w; time=2, T=12)
        @test isfile(p * ".writing") && !isfile(p)
        @test writing_status(p * ".writing") == "measuring"
        r = @test_logs (:warn, r"still being written") LBD.load(p * ".writing")
        @test r["S21"].data[1, :] == (1:4) .+ 1im
        @test r["time"].data == [0, 1, 2] && r["T"].data == [10, 11, 12]
        @test_throws LBDError add_axis!(w, "late", [1])
        @test_throws LBDError LBD.Writer(p)
        @test_throws LBDError recover(p * ".writing")
        write!(w; power=2, S21=ones(4), n=6)
        w.description = "changed while measuring"
        out = @test_logs (:warn, r"n not measured everywhere") close(w)
        @test out == p && !isfile(p * ".writing")
        r = LBD.load(p)
        @test r.description == "changed while measuring"
        @test r.meta["sample"] == "R7"
        @test r["S21"].data[2, :] == ones(4)
        @test all(isnan, r["S21"].data[3, :])
        @test r["n"].measured == [true, true, false]
        @test r.id == w.id
        @test_throws LBDError write!(w; power=3, n=1)
    end

    @testset "Writer: an error in the block, recover" begin
        p = joinpath(dir, "stopped.lbd")
        wref = Ref{Any}(nothing)
        @test_logs (:warn, r"stopped with an error") match_mode=:any @test_throws ErrorException lbd_writer(p; flush_every=60) do w
            wref[] = w
            add_axis!(w, "x", 1:4)
            add_value!(w, "y"; axes="x")
            write!(w; x=1, y=1.0)
            write!(w; x=2, y=2.0)                            # not flushed yet: written on the way out
            error("instrument did not answer")
        end
        @test !isfile(p) && writing_status(p) == "stopped"
        @test recover(p * ".writing") == p
        @test !isfile(p * ".writing")
        r = LBD.load(p)
        @test r.id == wref[].id
        @test r["y"].data[1:2] == [1.0, 2.0] && isnan(r["y"].data[3])
    end

    @testset "Writer: stopped early, a name taken, bad metadata" begin
        p = joinpath(dir, "taken.lbd")
        w = live_writer(p)
        write!(w; power=1, n=1)
        w.meta["bad"] = nothing
        @test_throws LBDError close(w)
        @test writing_status(p) == "measuring"
        delete!(w.meta, "bad")
        write(p, "someone else's")
        out = @test_logs (:warn, r"saved as taken \(2\)\.lbd") close(w; stopped=true)
        @test out == joinpath(dir, "taken (2).lbd")
        @test LBD.load(out)["n"].measured == [true, false, false]
        @test read(p, String) == "someone else's"
        @test_throws LBDError LBD.Writer(joinpath(dir, "a.h5"))
        d = LBD.Dataset()
        add_axis!(d, "x", [1])
        add_value!(d, "y", [1.0], "x")
        @test_throws LBDError LBD.save(joinpath(dir, "a.lbd.writing"), d)
    end

    @testset "reads Python-written examples" begin
        ex = joinpath(@__DIR__, "..", "..", "..", "examples", "data")
        if isdir(ex)
            r = LBD.load(joinpath(ex, "2026", "resonator", "power_sweep.lbd"))
            @test r["S21"].axes == ["power", "freq"]
            @test size(r["S21"].data) == (length(r["power"]), length(r["freq"]))
            @test r.meta["vna"]["averages"] == 4
            @test r.plot["complex"] == "db"
            t = LBD.load(joinpath(ex, "temperature_map.lbd"))
            @test size(t["temperature"].data) == (81, 121)
        else
            @warn "examples/data not found; run examples/python/make_examples.py"
        end
    end
end
