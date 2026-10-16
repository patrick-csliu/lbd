function tests = test_lbd
% Run with:  results = runtests("matlab/tests")
tests = functiontests(localfunctions);
end

function setupOnce(tc)
here = fileparts(mfilename('fullpath'));
addpath(fullfile(here, '..'));
tc.TestData.dir = tempname;
mkdir(tc.TestData.dir);
tc.TestData.examples = fullfile(here, '..', '..', '..', 'examples', 'data');
end

function teardownOnce(tc)
rmdir(tc.TestData.dir, 's');
end

function d = makeSweep()
f = linspace(4e9, 8e9, 41);
p = -40:4:0;
s21 = exp(1i * (p' * f) * 1e-10);           % 11 x 41 = (power, freq)
d = lbd.Dataset("Resonator power sweep", "test");
d.addAxis("power", p, Unit="dBm", Label="Power");
d.addAxis("freq", f, Unit="Hz", Label="Frequency");
d.addValue("S21", s21, ["power" "freq"]);
d.addValue("mag", abs(s21), "power,freq", Label="|S21|");
end

function testRoundTrip(tc)
d = makeSweep();
p = d.save(fullfile(tc.TestData.dir, "sweep.lbd"));
r = lbd.load(p);
v = lbd.version();
tc.verifyEqual(r.Title, "Resonator power sweep");
tc.verifyEqual(r.Description, "test");
tc.verifyEqual(r.Writer, "matlab lbd " + v.package);
tc.verifyEqual(r.Axes.power.Data, d.Axes.power.Data);
tc.verifyEqual(r.Axes.freq.Unit, "Hz");
tc.verifyEqual(r.Values.S21.Axes, ["power" "freq"]);
tc.verifySize(r.Values.S21.Data, [11 41]);
tc.verifyFalse(isreal(r.Values.S21.Data));
tc.verifyEqual(r.Values.S21.Data, d.Values.S21.Data);
tc.verifyEqual(r.Values.mag.Label, "|S21|");
tc.verifyEqual(r.Values.S21.Dtype, "complex128");
end

function testLayoutOnDisk(tc)
p = fullfile(tc.TestData.dir, "layout.lbd");
makeSweep().save(p);
info = h5info(p, '/values/S21');
% h5info reports dims in MATLAB (reversed) order: logical (11, 41) -> [41 11]
tc.verifyEqual(info.Dataspace.Size, [41 11]);
tc.verifyEqual(info.Datatype.Class, 'H5T_COMPOUND');
tc.verifyEqual(string(h5readatt(p, '/values/S21', 'axes')), "power,freq");
end

function testDtypes(tc)
d = lbd.Dataset();
d.addAxis("x", 1:5);
d.addValue("i16", int16(1:5), "x");
d.addValue("f32", single(1:5), "x");
d.addValue("c64", complex(single(1:5)), "x");
d.addValue("mask", logical([1 0 1 0 1]), "x");
d.addValue("forced", 1:5, "x", Dtype="float32");
r = lbd.load(d.save(fullfile(tc.TestData.dir, "t.lbd")));
tc.verifyClass(r.Values.i16.Data, 'int16');
tc.verifyClass(r.Values.f32.Data, 'single');
tc.verifyClass(r.Values.c64.Data, 'single');
tc.verifyFalse(isreal(r.Values.c64.Data));
tc.verifyClass(r.Values.mask.Data, 'logical');
tc.verifyEqual(r.Values.mask.Data, logical([1 0 1 0 1])');
tc.verifyClass(r.Values.forced.Data, 'single');
tc.verifyEqual(r.Values.mask.Dtype, "bool");
end

function testScalarValue(tc)
d = lbd.Dataset();
d.addValue("fit_Q", 12345.6);
r = lbd.load(d.save(fullfile(tc.TestData.dir, "s.lbd")));
tc.verifyEmpty(r.Values.fit_Q.Axes);
tc.verifyEqual(r.Values.fit_Q.Data, 12345.6);
end

function testThreeD(tc)
d = lbd.Dataset();
d.addAxis("a", 1:2); d.addAxis("b", 1:3); d.addAxis("c", 1:4);
A = reshape(1:24, 2, 3, 4);
d.addValue("A", A, ["a" "b" "c"]);
r = lbd.load(d.save(fullfile(tc.TestData.dir, "3d.lbd")));
tc.verifyEqual(r.Values.A.Data, A);
tc.verifyEqual(r.Values.A.Shape, [2 3 4]);
end

function testMeta(tc)
d = lbd.Dataset();
d.Meta.T_mK = 12;
d.Meta.sample = "R7 – chip 3";
d.Meta.gain = 1.5;
d.Meta.flag = true;
d.Meta.z = 1 + 2i;
d.Meta.vec = [1 2 3];
d.Meta.mat = [0 1 2; 3 4 5];
d.Meta.names = ["a" "b"];
d.Meta.vna = struct('ifbw_Hz', 1000, 'averages', 4, 'port', struct('n', 2));
m = lbd.load(d.save(fullfile(tc.TestData.dir, "m.lbd"))).Meta;
tc.verifyEqual(m.T_mK, 12);
tc.verifyEqual(m.sample, "R7 – chip 3");
tc.verifyEqual(m.gain, 1.5);
tc.verifyEqual(m.flag, int64(1));
tc.verifyEqual(m.z, 1 + 2i);
tc.verifyEqual(m.vec, [1 2 3]');
tc.verifyEqual(m.mat, [0 1 2; 3 4 5]);
tc.verifyEqual(m.names, ["a" "b"]);
tc.verifyEqual(m.vna.averages, 4);
tc.verifyEqual(m.vna.port.n, 2);
end

function testPlotAndStyle(tc)
d = makeSweep();
d.Plot = struct('kind', "heatmap", 'values', {{"S21"}}, 'complex', "db");
d.Style = struct('figure', struct('width_mm', 120));
d.StyleName = "thesis";
d.Matplotlib = "3.10.1";
r = lbd.load(d.save(fullfile(tc.TestData.dir, "p.lbd")));
tc.verifyEqual(string(r.Plot.kind), "heatmap");
tc.verifyEqual(string(r.Plot.values), "S21");
tc.verifyEqual(r.Style.figure.width_mm, 120);
tc.verifyEqual(r.StyleName, "thesis");
tc.verifyEqual(r.Matplotlib, "3.10.1");        % kept as is through a MATLAB save
r2 = lbd.load(r.save(fullfile(tc.TestData.dir, "p2.lbd")));
tc.verifyEqual(r2.Matplotlib, "3.10.1");
end

function testInfoPartialCompression(tc)
p = fullfile(tc.TestData.dir, "sweep2.lbd");
makeSweep().save(p);
i = lbd.info(p);
tc.verifyEmpty(i.Values.S21.Data);
tc.verifyEqual(i.Values.S21.Shape, [11 41]);
tc.verifyEqual(i.Values.S21.Dtype, "complex128");
part = lbd.load(p, Values="mag");
tc.verifyNotEmpty(part.Values.mag.Data);
tc.verifyEmpty(part.Values.S21.Data);
tc.verifyError(@() lbd.load(p, Values="nope"), 'lbd:notFound');
tc.verifyError(@() i.save(fullfile(tc.TestData.dir, "x.lbd")), 'lbd:invalid');

d = lbd.Dataset();
d.addAxis("x", 1:100); d.addAxis("y", 1:200);
d.addValue("z", zeros(100, 200), ["x" "y"]);
pc = d.save(fullfile(tc.TestData.dir, "c.lbd"), Compression=true);
tc.verifyEqual(lbd.load(pc).Values.z.Data, zeros(100, 200));
info = h5info(pc, '/values/z');
tc.verifyNotEmpty(info.Filters);
end

function testValidation(tc)
d = lbd.Dataset();
d.addAxis("x", [1 2]);
tc.verifyError(@() d.addAxis("1bad", [1 2]), 'lbd:invalid');
tc.verifyError(@() d.addAxis("x2", [1 2; 3 4]), 'lbd:invalid');
tc.verifyError(@() d.addValue("v", [1 2 3], "x"), 'lbd:invalid');
tc.verifyError(@() d.addValue("v", [1 2], "nope"), 'lbd:invalid');
tc.verifyError(@() d.addValue("x", [1 2], "x"), 'lbd:invalid');
tc.verifyError(@() d.addValue("v", ["a" "b"], "x"), 'lbd:invalid');
tc.verifyError(@() d.addValue("v", [1i 2i], "x", Dtype="float64"), 'lbd:invalid');
d.Meta.bad = [];
p = fullfile(tc.TestData.dir, "bad.lbd");
tc.verifyError(@() d.save(p), 'lbd:invalid');
tc.verifyFalse(isfile(p));
end

function testVersions(tc)
p = fullfile(tc.TestData.dir, "v.lbd");
makeSweep().save(p);
setVersion(p, "1.7");
tc.verifyWarning(@() lbd.load(p), 'lbd:newerVersion');
setVersion(p, "2.0");
tc.verifyError(@() lbd.load(p), 'lbd:version');
v = lbd.version();
tc.verifyEqual(v.lbd_version, "1.0");
end

function setVersion(p, ver)
fid = H5F.open(p, 'H5F_ACC_RDWR', 'H5P_DEFAULT');
H5A.delete(fid, 'lbd_version');
H5F.close(fid);
h5writeatt(p, '/', 'lbd_version', char(ver));
end

function testReadsPythonExamples(tc)
ex = tc.TestData.examples;
tc.assumeTrue(isfolder(ex), "examples/data not found; run examples/python/make_examples.py");
r = lbd.load(fullfile(ex, "2026", "resonator", "power_sweep.lbd"));
tc.verifyEqual(r.Values.S21.Axes, ["power" "freq"]);
tc.verifySize(r.Values.S21.Data, [numel(r.Axes.power.Data) numel(r.Axes.freq.Data)]);
tc.verifyEqual(r.Meta.vna.averages, int64(4));
tc.verifyEqual(string(r.Plot.complex), "db");
t = lbd.load(fullfile(ex, "temperature_map.lbd"));
tc.verifySize(t.Values.temperature.Data, [81 121]);
tc.verifyEqual(t.Values.temperature.Unit, "K");
end

function testSavedViewMustBeAnObject(tc)
d = makeSweep();
p = fullfile(tc.TestData.dir, "view.lbd");
d.Plot = 5;
tc.verifyError(@() d.save(p), 'lbd:invalid');
d.Plot = '[1, 2]';
tc.verifyError(@() d.save(p), 'lbd:invalid');
d.Plot = '{"kind": ';
tc.verifyError(@() d.save(p), 'lbd:invalid');
tc.verifyFalse(isfile(p));
d.Plot = '{"kind": "heatmap"}';
d.Style = struct("figure", struct("width_mm", 120));
d.StyleName = "";
tc.verifyError(@() d.save(p), 'lbd:invalid');
d.StyleName = "thesis";
d.save(p);
r = lbd.load(p);
tc.verifyEqual(r.Plot.kind, 'heatmap');
end

function testMetaProblemsWarn(tc)
d = makeSweep();
p = fullfile(tc.TestData.dir, "metaodd.lbd");
d.save(p);
h5create(p, "/meta/table", [1 3]);
h5write(p, "/meta/table", [1 2 3]);
fid = H5F.open(p, 'H5F_ACC_RDWR', 'H5P_DEFAULT');
gid = H5G.open(fid, '/meta');
for name = ["a b", "aB"]   % makeValidName("a b") is "aB"
    sid = H5S.create('H5S_SCALAR');
    aid = H5A.create(gid, char(name), 'H5T_NATIVE_DOUBLE', sid, 'H5P_DEFAULT');
    H5A.write(aid, 'H5ML_DEFAULT', 1);
    H5A.close(aid); H5S.close(sid);
end
H5G.close(gid); H5F.close(fid);
tc.verifyWarning(@() lbd.load(p), 'lbd:metaDataset');
tc.verifyWarning(@() lbd.load(p), 'lbd:metaCollision');
end

function testInvalidSavedJsonWarns(tc)
d = makeSweep();
p = fullfile(tc.TestData.dir, "badjson.lbd");
d.save(p);
fid = H5F.open(p, 'H5F_ACC_RDWR', 'H5P_DEFAULT');
gid = H5G.create(fid, 'plot', 'H5P_DEFAULT', 'H5P_DEFAULT', 'H5P_DEFAULT');
H5G.close(gid); H5F.close(fid);
h5writeatt(p, '/plot', 'spec', '[1, 2]');
r = tc.verifyWarning(@() lbd.load(p), 'lbd:json');
tc.verifyEmpty(r.Plot);
end
