function write_fixture(out)
% Called by tests/crosslang/run_all.py (see ../language.toml).
if ~isfolder(out), mkdir(out); end
[I, J, K] = ndgrid(0:2, 0:3, 0:1);
d = lbd.Dataset("Fixture – ünïcode");
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
end
