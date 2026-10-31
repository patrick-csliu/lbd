function write_fixture(out)
% Called by tests/crosslang/run_all.py (see ../language.toml).
if ~isfolder(out), mkdir(out); end
[I, J, K] = ndgrid(0:2, 0:3, 0:1);
d = lbd.Dataset("Fixture – ünïcode", Created="2025-03-01T23:30:00+08:00");
d.addAxis("x", 0:9, Unit="s");
d.addAxis("a", [1 2 3], Unit="V");
d.addAxis("b", [1 2 3 4], Unit="A");
d.addAxis("c", [1 2], Unit="Hz");
d.addValue("y", (0:9).^2, "x", Unit="s^2");
d.addValue("k", int32((1:10) .* (-1).^(0:9)), "x");
d.addValue("mask", mod(0:9, 2) == 0, "x");
d.addValue("M", 10*I(:,:,1) + J(:,:,1), ["a" "b"]);
d.addValue("Z", complex(I(:,:,1) + 1, J(:,:,1) + 1), ["a" "b"]);
d.addValue("T", 100*I + 10*J + K, ["a" "b" "c"]);
d.addValue("q", 42.5);
d.addAxis("state", [], Elements=["ground" "état 1" "量子"]);
d.addValue("S", [0.5 1.5 2.5], "state");
[I2, R2, C2] = ndgrid(0:2, 0:1, 0:1);
d.addValue("C", 100*I2 + 10*R2 + C2, "a", Shape=[2 2], Elements={["I" "Q"], []});
d.Meta.sample = "chip – é";
d.Meta.T_mK = int64(12);
d.Meta.names = ["a" "b"];
d.Meta.vec = [1 2 3];
d.Meta.mat = [0 1 2; 3 4 5];
d.Meta.vna = struct('ifbw_Hz', 1000, 'averages', int64(4));
d.Plot = struct('kind', "heatmap", 'values', {{"M"}});
d.StyleName = "thesis";
d.Matplotlib = "3.9.0";   % MATLAB has no matplotlib: a fixed version for the test
d.save(fullfile(out, "fixture.lbd"));

% The live fixture: written while "measuring" with lbd.Writer, stopped early.
w = lbd.Writer(fullfile(out, "live.lbd"), Title="Live – ü");
w.addAxis("power", [1 2 3], Unit="dBm");
w.addAxis("freq", [0 0.5 1], Unit="Hz");
w.addAxis("state", [], Elements=["ground" "excited"]);
w.addAxis("time", [], Unit="s", Grows=true);
w.addValue("S21", [], ["power" "freq"], Dtype="complex128");
w.addValue("T", [], "time");
w.addValue("n", [], ["state" "power"], Dtype="int32");
for i = 1:2                                            % power 3 is never measured
    w.write(power=i, S21=complex(i, 1:3));
end
w.write(time=0, T=0);
w.write(time=[1 2], T=[10 20]);
w.write(time=3, T=30);
w.write(state="excited", power=1, n=7);
w.write(state="ground", power=2, n=3);
w.close(Stopped=true);
end
