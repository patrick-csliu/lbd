using LBD
using HDF5
using Test

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
        @test LBD.version().lbd_version == "1.0"
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
