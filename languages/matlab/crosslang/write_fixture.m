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

% The groups fixture (format 2.0): variable sweeps, the same in every language.
g = lbd.Dataset("Groups");
g.addGroup("AB");
g.addAxis("A", [], Group="AB", Unit="V");
g.addAxis("B", [], Group="AB", Unit="Hz");
g.addAxis("C", [0.1 0.2 0.3]);
g.addValue("f", [], ["A" "B"]);
g.addValue("q", [], "A");
g.addValue("h", [], ["A" "B" "C"]);
g.addValue("cov", [], ["A" "B"], Shape=[2 2]);
g.addValue("n", [], ["A" "B"], Dtype="int16");
g.addGroup("PQR");
for a = ["P" "Q" "R"], g.addAxis(a, [], Group="PQR"); end
g.addValue("u", [], ["P" "Q"]);
g.addValue("w", [], "PQR");
bs = {10, [10 20], [15 25 35]};
for a = 1:3                                            % by coordinates
    for b = bs{a}
        g.write(A=a, B=b, f=100 * a + b, h=[a b a + b], cov=[a b; b -a]);
    end
    g.write(A=a, q=1.5 * a);
end
g.write(A=1, B=10, n=1);
g.write(A=3, B=25, n=2);
for p = 1:3                                            % by Parent=
    i = g.write(P=p);
    for q = 0:p - 1
        k = g.write(Parent=i, Q=q, u=10 * p + q);
        r = 0:q - 1;
        g.write(Parent=k, R=r, w=100 * p + 10 * q + r);
    end
end
g.save(fullfile(out, "groups.lbd"));

% The r+ fixture (plan 6d): saved, then opened with Mode="r+" and changed in place.
r = lbd.Dataset("R plus");
r.addAxis("x", 0:4);
r.addValue("y", zeros(1, 5), "x");
r.save(fullfile(out, "rplus.lbd"));
o = lbd.open(fullfile(out, "rplus.lbd"), Mode="r+");
o.write(x=3, y=7);
o.Meta.edited = 1;
o.save();
o.close();
end
