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

function testIdMadeKeptAndNew(tc)
% The identity: a UUID version 7, made at the first save, kept when saved again to the same
% file, new (the old one as ParentId) when saved to another file or by newId.
f = fullfile(tc.TestData.dir, "id.lbd");
g = fullfile(tc.TestData.dir, "id other.lbd");
d = lbd.Dataset("t");
d.addAxis("x", [1 2]);
d.addValue("y", [1 2], "x");
tc.verifyEmpty(d.Id);
d.save(f);
first = d.Id;
verifyUuid7(tc, first);
tc.verifyEmpty(d.ParentId);
r = lbd.load(f);
tc.verifyEqual(r.Id, first);
r.Description = "edited";
r.save(f);                                                   % the same file: kept
tc.verifyEqual(lbd.load(f).Id, first);
r.save(g);                                                   % another file: new, with its parent
tc.verifyNotEqual(r.Id, first);
verifyUuid7(tc, r.Id);
tc.verifyEqual(r.ParentId, first);
tc.verifyEqual(lbd.load(g).Id, r.Id);
tc.verifyEqual(lbd.load(g).ParentId, first);
tc.verifyEqual(lbd.load(f).Id, first);                       % the original untouched
before = r.Id;
r.newId();
tc.verifyEqual(r.ParentId, before);
verifyUuid7(tc, r.Id);
tc.verifyNotEqual(r.Id, before);
tc.verifyError(@() setId(r), 'MATLAB:class:SetProhibited');  % read-only
end

function setId(d)
d.Id = "x";
end

function testIdNotFromRngAndUnique(tc)
% ids come from the operating system's source: rng(0) doesn't repeat them
ids = strings(1, 2);
for k = 1:2
    rng(0);
    d = lbd.Dataset("t");
    d.addAxis("x", [1 2]);
    d.addValue("y", [1 2], "x");
    d.save(fullfile(tc.TestData.dir, "seeded" + k + ".lbd"));
    ids(k) = d.Id;
end
tc.verifyNotEqual(ids(1), ids(2));
many = strings(1, 10000);
for k = 1:numel(many)
    many(k) = lbd.Dataset.newIdText();
end
tc.verifyEqual(numel(unique(many)), numel(many));
for k = 1:200
    verifyUuid7(tc, many(k));
end
end

function testMalformedIdWarns(tc)
f = fullfile(tc.TestData.dir, "badid.lbd");
d = lbd.Dataset("t");
d.addAxis("x", [1 2]);
d.addValue("y", [1 2], "x");
d.save(f);
fid = H5F.open(f, 'H5F_ACC_RDWR', 'H5P_DEFAULT');
H5A.delete(fid, 'id');
H5F.close(fid);
h5writeatt(f, '/', 'id', 'not-a-uuid');
r = tc.verifyWarning(@() lbd.load(f), 'lbd:badId');
tc.verifyEmpty(r.Id);
end

function verifyUuid7(tc, id)
id = char(id);
tc.verifyEqual(numel(id), 36);
tc.verifyNotEmpty(regexp(id, '^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$', 'once'), id);
ms = hex2dec([id(1:8) id(10:13)]);
now = posixtime(datetime('now', 'TimeZone', 'UTC')) * 1000;
tc.verifyLessThan(abs(now - ms), 60000, "the time field is now");
end

function testCreatedKeptAndSettable(tc)
f = fullfile(tc.TestData.dir, "created.lbd");
d = lbd.Dataset("t");
d.addAxis("x", [1 2]);
d.addValue("y", [1 2], "x");
tc.verifyEmpty(d.Created);
d.save(f);
first = d.Created;
r = lbd.load(f);
tc.verifyEqual(r.Created, first);
r.Description = "edited later";
r.save(f);
tc.verifyEqual(lbd.load(f).Created, first);                  % saved again: kept
d2 = lbd.Dataset("t", Created="2025-03-01T23:30:00+08:00");
d2.addAxis("x", [1 2]);
d2.addValue("y", [1 2], "x");
d2.save(f);
tc.verifyEqual(lbd.load(f).Created, "2025-03-01T23:30:00+08:00");
d2.Created = datetime(2024, 1, 2, 3, 4, 5, 'TimeZone', '-05:00');
d2.save(f);
tc.verifyEqual(lbd.load(f).Created, "2024-01-02T03:04:05-05:00");
d2.Created = "2024-06-01T12:00:00";                          % no offset: this computer's
d2.save(f);
tc.verifyTrue(startsWith(lbd.load(f).Created, "2024-06-01T12:00:00") && strlength(lbd.load(f).Created) == 25);
for bad = ["yesterday", "2025-03-01", "2025-13-01T00:00:00+00:00"]
    tc.verifyError(@() lbd.Dataset("t", Created=bad), 'lbd:invalid');
end
tc.verifyError(@() lbd.Dataset("t", Created=20250301), 'lbd:invalid');
end

function testVersions(tc)
p = fullfile(tc.TestData.dir, "v.lbd");
makeSweep().save(p);
setVersion(p, "1.7");
tc.verifyWarning(@() lbd.load(p), 'lbd:newerVersion');
setVersion(p, "2.0");
lbd.load(p);                                        % 2.0 is known: no warning
setVersion(p, "2.1");
tc.verifyWarning(@() lbd.load(p), 'lbd:newerVersion');
setVersion(p, "3.0");
tc.verifyError(@() lbd.load(p), 'lbd:version');
v = lbd.version();
tc.verifyEqual(v.lbd_version, "2.0");
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

function testAxisElements(tc)
p = fullfile(tc.TestData.dir, "elements.lbd");
d = lbd.Dataset("elements");
d.addAxis("state", [], Elements=["ground" "excited"], Label="Prepared state");
d.addAxis("device", [1 2 5], Elements=["Q1" "état 1" "量子"]);
d.addAxis("one", 7, Elements="only");
d.addAxis("t", linspace(0, 1, 3));
d.addValue("I", zeros(2, 3), ["state" "t"]);
d.save(p);
r = lbd.load(p);
tc.verifyEqual(r.Axes.state.Elements, ["ground" "excited"]);
tc.verifyEqual(double(r.Axes.state.Data'), [0 1]);
tc.verifyEqual(r.Axes.device.Elements, ["Q1" "état 1" "量子"]);
tc.verifyEqual(r.Axes.one.Elements, "only");
tc.verifyEmpty(r.Axes.t.Elements);
tc.verifyEqual(r.LbdVersion, "1.2");
tc.verifyError(@() d.addAxis("x", [0 1], Elements=["a" "b" "c"]), 'lbd:invalid');
tc.verifyError(@() d.addAxis("y"), 'lbd:invalid');
end

function testDataPointShape(tc)
p = fullfile(tc.TestData.dir, "shape.lbd");
d = lbd.Dataset("shape");
d.addAxis("amp", linspace(0, 0.5, 4), Unit="V");
b = reshape(1:12, 4, 3);
v = d.addValue("bloch", b, "amp", Shape=3, Elements=["x" "y" "z"]);
tc.verifyEqual(v.Axes, "amp");                      % what was swept
tc.verifyEqual(v.PointShape, 3);                    % one data point
tc.verifyEqual(v.Dims, {"amp"});
tc.verifyFalse(isfield(d.Axes, "bloch_dim1"));      % a data point isn't a sweep axis
d.addValue("cov", zeros(4, 2, 2), "amp", Shape=[2 2], Elements={["I" "Q"], []});
d.save(p);
r = lbd.load(p);
tc.verifyEqual(r.Values.bloch.Data, b);
tc.verifyEqual(r.Values.bloch.PointShape, 3);
tc.verifyEqual(fieldnames(r.Axes), {'amp'});
tc.verifyEqual(r.Values.bloch.Elements, {["x" "y" "z"]});
tc.verifyEqual(r.Values.cov.Axes, "amp");
tc.verifyEqual(r.Values.cov.PointShape, [2 2]);
tc.verifyEqual(r.Values.cov.Shape, [4 2 2]);
tc.verifyEqual(r.Values.cov.Elements{1}, ["I" "Q"]);
tc.verifyEmpty(r.Values.cov.Elements{2});
tc.verifyEqual(string(h5readatt(p, '/values/bloch', 'axes')), "amp,bloch_dim1");
% the shape must be said; the value's axes come first
tc.verifyError(@() d.addValue("r", zeros(4, 3), "amp"), 'lbd:invalid');
tc.verifyError(@() d.addValue("r", zeros(3, 4), "amp", Shape=3), 'lbd:invalid');
tc.verifyError(@() d.addValue("r", zeros(4, 3), "amp", Shape=3, Elements=["u" "v"]), 'lbd:invalid');
end

function testBadElementsInAFileWarn(tc)
p = fullfile(tc.TestData.dir, "badelements.lbd");
d = lbd.Dataset("bad");
d.addAxis("state", [], Elements=["ground" "excited"]);
d.save(p);
fid = H5F.open(p, 'H5F_ACC_RDWR', 'H5P_DEFAULT');
did = H5D.open(fid, '/axes/state');
H5A.delete(did, 'elements');
H5D.close(did); H5F.close(fid);
h5writeatt(p, '/axes/state', 'elements', 'one');
r = tc.verifyWarning(@() lbd.load(p), 'lbd:badElements');
tc.verifyEmpty(r.Axes.state.Elements);
end

function d = makePlanned()
d = lbd.Dataset("planned");
d.addAxis("power", linspace(-60, 0, 4), Unit="dBm");
d.addAxis("freq", linspace(6e9, 7e9, 5), Unit="Hz");
d.addAxis("state", [], Elements=["ground" "excited"]);
d.addValue("S21", [], ["power" "freq"], Dtype="complex128");
d.addValue("T", [], "power");
d.addValue("n", [], ["state" "power"], Dtype="int32");
end

function testWriteFillsValues(tc)
d = makePlanned();
tc.verifyTrue(all(isnan(d.Values.S21.Data(:))));
tc.verifySize(d.Values.S21.Data, [4 5]);
tc.verifyEqual(d.Values.n.Measured, false(2, 4));
d.write(power=2, S21=(1:5) * 1i, T=4.2);                 % a trace and a point
d.write(power=3, freq=4, S21=1 + 2i);
d.write(state="excited", power=4, n=7);
d.write("state", 1, "power", 1, "n", 3);                 % any name as text
tc.verifyEqual(d.Values.S21.Data(2, :), (1:5) * 1i);
tc.verifyEqual(d.Values.S21.Data(3, 4), 1 + 2i);
tc.verifyTrue(isnan(d.Values.S21.Data(3, 1)));
tc.verifyEqual(d.Values.T.Data(2), 4.2);
tc.verifyEqual(d.Values.n.Data(2, 4), int32(7));
tc.verifyEqual(nnz(d.Values.n.Measured), 2);
d.write(S21=ones(4, 5));                                 % the whole map
tc.verifyEqual(d.Values.S21.Data, complex(ones(4, 5)));
p = fullfile(tc.TestData.dir, "filled.lbd");
d.save(p);
r = lbd.load(p);
tc.verifyEqual(r.Values.n.Measured, d.Values.n.Measured);
tc.verifyEmpty(r.Values.T.Measured);
tc.verifyEqual(string(h5info(p, '/measured').Datasets.Name), "n");
d.write(n=ones(2, 4));                                   % now everything is measured
d.save(p);
tc.verifyEmpty(lbd.load(p).Values.n.Measured);
end

function testWriteErrors(tc)
d = makePlanned();
tc.verifyError(@() d.write(power=2, S21=ones(1, 4)), 'lbd:invalid');   % 5 frequencies
tc.verifyError(@() d.write(power=9, T=1), 'lbd:invalid');              % out of range
tc.verifyError(@() d.write(power=0, T=1), 'lbd:invalid');              % 1-based
tc.verifyError(@() d.write(freq=1, T=1), 'lbd:invalid');               % T isn't on freq
tc.verifyError(@() d.write(S21=1), 'lbd:invalid');                     % needs the whole map
tc.verifyError(@() d.write(state="mid", power=1, n=1), 'lbd:invalid');
tc.verifyError(@() d.write(state=1, power=1, n=1.5), 'lbd:invalid');
tc.verifyError(@() d.write(power=1, T=1i), 'lbd:invalid');
tc.verifyError(@() d.write(power=1), 'lbd:invalid');                   % no value
tc.verifyError(@() d.write(nope=1, T=1), 'lbd:invalid');
tc.verifyError(@() d.write("power", 1, "power", 2, "T", 1), 'lbd:invalid');
tc.verifyTrue(all(isnan(d.Values.T.Data)));                            % nothing half written
end

function testGrowingAxis(tc)
d = lbd.Dataset("log");
d.addAxis("time", [], Unit="s", Grows=true);
d.addAxis("ch", [1 2]);
d.addValue("T", [], "time");
d.addValue("V", [], ["time" "ch"]);
d.addValue("ok", [], "time", Dtype="bool");
tc.verifyError(@() d.addValue("bad", [], ["ch" "time"]), 'lbd:invalid');
tc.verifyError(@() d.save(fullfile(tc.TestData.dir, "empty.lbd")), 'lbd:invalid');
d.write(time=0.5, T=1, V=[1 2], ok=true);
d.write(time=[1 1.5], T=[2 3]);
tc.verifyEqual(d.Axes.time.Data, [0.5; 1; 1.5]);
tc.verifyEqual(d.Values.T.Data, [1; 2; 3]);
tc.verifyTrue(all(isnan(d.Values.V.Data(2:3, :)), 'all'));
tc.verifyEqual(d.Values.ok.Measured, [true; false; false]);
tc.verifyError(@() d.write(T=1), 'lbd:invalid');
p = fullfile(tc.TestData.dir, "log.lbd");
d.save(p);
r = lbd.load(p);
tc.verifyEqual(r.Axes.time.Data, [0.5; 1; 1.5]);
tc.verifyEqual(r.Values.ok.Measured, [true; false; false]);
end

function w = makeWriter(path)
w = lbd.Writer(path, Title="live", FlushEvery=60);
w.addAxis("power", 1:3);
w.addAxis("freq", linspace(0, 1, 4));
w.addValue("S21", [], ["power" "freq"], Dtype="complex128");
w.addValue("n", [], "power", Dtype="int64");
w.addAxis("time", [], Grows=true);
w.addValue("T", [], "time");
end

function testWriterLive(tc)
p = fullfile(tc.TestData.dir, "live.lbd");
w = makeWriter(p);
w.Meta.sample = "R7";
w.write(power=1, S21=(1:4) + 1i, n=5);
w.write(time=[0 1], T=[10 11]);
w.write(time=2, T=12);
tc.verifyTrue(isfile(p + ".writing"));
tc.verifyEqual(lbd.writingStatus(p + ".writing"), "measuring");
w.flush();
r = tc.verifyWarning(@() lbd.load(p + ".writing"), 'lbd:writing');
tc.verifyEqual(r.Values.S21.Data(1, :), (1:4) + 1i);
tc.verifyEqual(r.Axes.time.Data, [0; 1; 2]);
tc.verifyEqual(r.Values.T.Data, [10; 11; 12]);
tc.verifyError(@() w.addAxis("late", 1), 'lbd:invalid');
tc.verifyError(@() lbd.Writer(p), 'lbd:exists');
tc.verifyError(@() lbd.recover(p + ".writing"), 'lbd:held');
w.write(power=2, S21=ones(1, 4), n=6);
w.Description = "changed while measuring";
out = tc.verifyWarning(@() w.close(), 'lbd:notMeasured');       % n at power 3
tc.verifyEqual(out, p);
tc.verifyFalse(isfile(p + ".writing"));
r = lbd.load(p);
tc.verifyEqual(r.Description, "changed while measuring");
tc.verifyEqual(r.Meta.sample, "R7");
tc.verifyEqual(real(r.Values.S21.Data(2, :)), ones(1, 4));
tc.verifyFalse(isreal(r.Values.S21.Data));
tc.verifyTrue(all(isnan(r.Values.S21.Data(3, :))));
tc.verifyEqual(r.Values.n.Measured, [true; true; false]);
tc.verifyEqual(r.Values.T.Data, [10; 11; 12]);
tc.verifyEqual(r.Id, w.id());
tc.verifyError(@() w.write(power=3, n=1), 'lbd:closed');
end

function testWriterAbortAndRecover(tc)
p = fullfile(tc.TestData.dir, "stopped.lbd");
w = makeWriter(p);
w.write(power=1, S21=(1:4) * 1i, n=1);
w.write(time=0, T=5);
w.abort();
tc.verifyEqual(lbd.writingStatus(p), "stopped");
r = tc.verifyWarning(@() lbd.load(p + ".writing"), 'lbd:writing');
tc.verifyEqual(r.Values.T.Data, 5);
out = lbd.recover(p + ".writing");
tc.verifyEqual(out, p);
tc.verifyFalse(isfile(p + ".writing"));
r = lbd.load(p);
tc.verifyEqual(r.Id, w.id());
tc.verifyEqual(r.Values.S21.Data(1, :), (1:4) * 1i);
tc.verifyEqual(r.Values.n.Measured, [true; false; false]);
end

function testWriterStoppedAndNameTaken(tc)
p = fullfile(tc.TestData.dir, "taken.lbd");
w = makeWriter(p);
w.write(power=1, n=1);
fid = fopen(p, 'w'); fwrite(fid, 'x'); fclose(fid);
out = tc.verifyWarning(@() w.close(Stopped=true), 'lbd:exists');
tc.verifyEqual(out, fullfile(tc.TestData.dir, "taken (2).lbd"));
tc.verifyEqual(lbd.load(out).Values.n.Measured, [true; false; false]);
end

function testWriterRefusals(tc)
tc.verifyError(@() lbd.Writer(fullfile(tc.TestData.dir, "a.h5")), 'lbd:invalid');
d = lbd.Dataset();
d.addAxis("x", 1);
d.addValue("y", 1, "x");
tc.verifyError(@() d.save(fullfile(tc.TestData.dir, "a.lbd.writing")), 'lbd:invalid');
tc.verifyError(@() lbd.writingStatus(fullfile(tc.TestData.dir, "none.lbd")), 'lbd:notFound');
w = lbd.Writer(fullfile(tc.TestData.dir, "meta.lbd"));
w.addAxis("x", 1:2);
w.addValue("y", [], "x");
w.write(x=1, y=1);
w.Meta.bad = {1};
tc.verifyError(@() w.close(), 'lbd:invalid');
tc.verifyEqual(lbd.writingStatus(fullfile(tc.TestData.dir, "meta.lbd")), "measuring");
w.Meta = struct();
w.write(x=2, y=2);
tc.verifyEqual(lbd.load(w.close()).Values.y.Data, [1; 2]);
end

function testProgramHoldingAFileIsNamed(tc)
% The messages about a file another program keeps open name that program; a folder on a network
% share is noticed. The helpers are private: called from their folder.
p = fullfile(tc.TestData.dir, "held.txt");
fid = fopen(p, 'w'); fprintf(fid, 'x'); fclose(fid);
private = fullfile(fileparts(which('lbd.load')), 'private');
back = cd(private);
restore = onCleanup(@() cd(back));
tc.verifyEqual(lbd_who_has_open(fullfile(tc.TestData.dir, "nobody.txt")), "");
tc.verifyFalse(lbd_on_network_share(tc.TestData.dir));
if ispc
    tc.verifyTrue(lbd_on_network_share("\\server\share\data"));
end
if ispc || ~system('command -v lsof >/dev/null')
    holder = java.lang.ProcessBuilder({'powershell', '-NoProfile', '-Command', ...
        sprintf('$f = [IO.File]::Open(''%s'', ''Open''); Start-Sleep 30', p)});
    if ~ispc
        holder = java.lang.ProcessBuilder({'sh', '-c', sprintf('exec 3<"%s"; sleep 30', p)});
    end
    proc = holder.start();
    stop = onCleanup(@() proc.destroy());
    named = "";
    for k = 1:100
        named = lbd_who_has_open(p);
        if named ~= "", break; end
        pause(0.2);
    end
    tc.verifyNotEmpty(char(named));
end
end

% ---- axis groups (format 2.0): the data API's cases --------------------------------

function d = groupCase2()
% Case 2: group A -> B, B chosen per A (A=1: B=10; A=2: B=10, 20; A=3: B=15, 25, 35)
d = lbd.Dataset("case 2");
d.addGroup("AB");
d.addAxis("A", [], Group="AB");
d.addAxis("B", [], Group="AB");
d.addValue("f", [], ["A" "B"]);
d.addValue("q", [], "A");
bs = {10, [10 20], [15 25 35]};
for a = 1:3
    for b = bs{a}
        d.write(A=a, B=b, f=100 * a + b);
    end
    d.write(A=a, q=1.5 * a);
end
end

function d = groupCase4(byParent)
% Case 4: group A -> B -> C, B in 0:A-1, C in 0:B-1; f per (A, B), g per (A, B, C)
d = lbd.Dataset("case 4");
d.addGroup("ABC");
for a = ["A" "B" "C"], d.addAxis(a, [], Group="ABC"); end
d.addValue("f", [], ["A" "B"]);
d.addValue("g", [], "ABC");
for a = 1:3
    if byParent, i = d.write(A=a); end
    for b = 0:a - 1
        c = 0:b - 1;
        if byParent
            k = d.write(Parent=i, B=b, f=10 * a + b);
            d.write(Parent=k, C=c, g=100 * a + 10 * b + c);
        else
            d.write(A=a, B=b, f=10 * a + b);
            d.write(A=a, B=b, C=c, g=100 * a + 10 * b + c);
        end
    end
end
end

function testGroupCase2(tc)
for loaded = [false true]
    d = groupCase2();
    if loaded
        p = fullfile(tc.TestData.dir, "case2.lbd");
        d.save(p);
        d = lbd.load(p);
        tc.verifyEqual(d.LbdVersion, "2.0");
    end
    tc.verifyEqual(d.Groups.AB.Order, ["A" "B"]);
    tc.verifyEqual(d.Axes.A.Data', [1 2 3]);
    tc.verifyEqual(d.Axes.B.Data', [10 10 20 15 25 35]);
    tc.verifyEqual(d.Axes.B.Parent', int64([1 2 2 3 3 3]));         % from 1 in MATLAB
    tc.verifyEqual(d.Axes.B.Group, "AB");
    f = d.Values.f;
    tc.verifyEqual(f.Axes, ["A" "B"]);
    tc.verifyEqual(f.Dims, {["A" "B"]});
    tc.verifyEqual(f.Data', [110 210 220 315 325 335]);
    tc.verifyEqual(d.Values.q.Dims, {"A"});
    c = d.coords("f");
    tc.verifyEqual(c.A', [1 2 2 3 3 3]);
    tc.verifyEqual(c.B', [10 10 20 15 25 35]);
    m = d.toDense("f");
    tc.verifyEqual(m.Axes.B.Data', [10 15 20 25 35]);
    expected = nan(3, 5);
    expected(1, 1) = 110; expected(2, 1) = 210; expected(2, 3) = 220;
    expected(3, 2) = 315; expected(3, 4) = 325; expected(3, 5) = 335;
    tc.verifyEqual(m.Values.f.Data, expected);
    tc.verifyEqual(m.Values.f.Dims, {"A", "B"});
    r = d.rows("f", By="A");
    tc.verifyEqual([r{:, 1}], [1 2 3]);
    tc.verifyEqual(r{3, 2}.Axes.B.Data', [15 25 35]);
    tc.verifyEqual(r{3, 2}.Values.f.Data', [315 325 335]);
end
end

function testGroupCase4BothWays(tc)
a = groupCase4(false);
b = groupCase4(true);
for d = {a, b}
    d = d{1}; %#ok<FXSET>
    tc.verifyEqual(d.Axes.B.Data', [0 0 1 0 1 2]);
    tc.verifyEqual(d.Axes.C.Data', [0 0 0 1]);
    tc.verifyEqual(d.Axes.C.Parent', int64([3 5 6 6]));
    tc.verifyEqual(d.Values.f.Data', [10 20 21 30 31 32]);
    tc.verifyEqual(d.Values.g.Data', [210 310 320 321]);
end
p = fullfile(tc.TestData.dir, "case4.lbd");
a.save(p);
tc.verifyEqual(h5read(p, '/axes/ABC/C._parent')', int64([2 4 5 5]));   % from 0 in the file
tc.verifyEqual(string(h5readatt(p, '/values/g', 'axes')), "A,B,C");
r = lbd.load(p);
g = r.toDense("g");
tc.verifyEqual(size(g.Values.g.Data), [2 2 2]);
tc.verifyEqual(g.Axes.A.Data', [2 3]);
rows = r.rows("g", By="A");
tc.verifyEqual(rows{3, 2}.Groups.ABC.Order, ["B" "C"]);
tc.verifyEqual(rows{3, 2}.Axes.C.Parent', int64([2 3 3]));
tc.verifyEqual(rows{3, 2}.Values.g.Data', [310 320 321]);
byB = r.rows("g", By="B");
tc.verifyEqual(byB{6, 1}, [3 2]);
tc.verifyEqual(byB{6, 2}.Axes.C.Data', [0 1]);
end

function testGroupWithFixedAxisAndMatrix(tc)
d = lbd.Dataset("case 3 and 5b");
d.addGroup("AB");
d.addAxis("A", [], Group="AB");
d.addAxis("B", [], Group="AB");
d.addAxis("C", [0.1 0.2 0.3]);
d.addValue("h", [], ["A" "B" "C"]);
d.addValue("cov", [], ["A" "B"], Shape=[2 2]);
d.write(A=1, B=[10 20], h=[1 2 3; 4 5 6], cov=ones(2, 2, 2));
d.write(A=2, B=10, C=2, h=7);
tc.verifyEqual(d.Values.h.Dims, {["A" "B"], "C"});
tc.verifyEqual(d.Values.h.Data(3, :), [NaN 7 NaN]);
tc.verifyEqual(size(d.Values.cov.Data), [3 2 2]);
p = fullfile(tc.TestData.dir, "case3.lbd");
d.save(p);
r = lbd.load(p);
tc.verifyEqual(r.Values.h.Data, d.Values.h.Data);
tc.verifyEqual(r.Values.cov.PointShape, [2 2]);
m = r.toDense("h");
tc.verifyEqual(size(m.Values.h.Data), [2 2 3]);
tc.verifyEqual(squeeze(m.Values.h.Data(1, 2, :))', [4 5 6]);
end

function testGroupRefusalsAndNearEqual(tc)
d = groupCase2();
tc.verifyError(@() d.write(B=10, f=1), 'lbd:invalid');           % B only under A
tc.verifyError(@() d.write(A=3, f=1), 'lbd:invalid');            % f needs B too
tc.verifyError(@() d.write(A=NaN, B=1, f=1), 'lbd:invalid');
tc.verifyError(@() d.addValue("x", [], "B"), 'lbd:invalid');     % an inner axis alone
tc.verifyError(@() d.toDense("f", Limit=10), 'lbd:invalid');
tc.verifyEqual(numel(d.Axes.B.Data), 6);
e = lbd.Dataset();
e.addGroup("AB");
e.addAxis("A", [], Group="AB");
e.addAxis("B", [], Group="AB");
e.addValue("f", [], ["A" "B"]);
e.write(A=0.3, B=1, f=1);
tc.verifyWarning(@() e.write(A=0.1 + 0.2, B=2, f=2), 'lbd:nearEqual');
tc.verifyWarning(@() e.toDense("f"), 'lbd:nearEqual');
m = e.toDense("f", Round=9);
tc.verifyEqual(size(m.Values.f.Data), [1 2]);
m = e.toDense("f", RTol=1e-9);
tc.verifyEqual(m.Values.f.Data, [1 2]);
end

function testWriterGroupLive(tc)
p = fullfile(tc.TestData.dir, "live_group.lbd");
w = lbd.Writer(p, Title="variable");
w.addGroup("ABC");
for a = ["A" "B" "C"], w.addAxis(a, [], Group="ABC"); end
w.addValue("f", [], ["A" "B"]);
w.addValue("g", [], "ABC");
w.addValue("n", [], "A", Dtype="int16");
for a = 1:3
    i = w.write(A=a, n=a);
    tc.verifyEqual(i, a);
    for b = 0:a - 1
        k = w.write(Parent=i, B=b, f=10 * a + b);
        c = 0:b - 1;
        w.write(Parent=k, C=c, g=100 * a + 10 * b + c);
    end
end
w.flush();
live = tc.verifyWarning(@() lbd.load(w.WritingPath), 'lbd:writing');
w.close();
r = lbd.load(p);
tc.verifyEqual(r.LbdVersion, "2.0");
tc.verifyEqual(r.Axes.C.Parent', int64([3 5 6 6]));
tc.verifyEqual(r.Values.g.Data', [210 310 320 321]);
tc.verifyEqual(r.Values.f.Data', [10 20 21 30 31 32]);
tc.verifyEqual(r.Values.n.Data', int16([1 2 3]));
tc.verifyEmpty(r.Values.n.Measured);
end

% ---- lbd.open: read only what is needed (plan 6d) ---------------------------------------

function p = bigFile(tc)
p = fullfile(tc.TestData.dir, "big_" + string(randi(1e9)) + ".lbd");
d = lbd.Dataset("big");
d.addAxis("power", 1:6);
d.addAxis("freq", 1:50);
d.addValue("S", reshape(0:299, 50, 6)' + 1i, ["power" "freq"]);
d.addValue("ok", mod(0:5, 2) == 0, "power");
d.addValue("n", [], "power", Dtype="int16");
d.write(power=2, n=7);
d.addValue("q", 2.5);
d.Meta.T_mK = 12;
d.save(p, Compression=true);
end

function testOpenReadsParts(tc)
p = bigFile(tc);
whole = lbd.load(p);
d = lbd.open(p);
closer = onCleanup(@() d.close());
x = d.Values.S.Data;
tc.verifyClass(x, 'lbd.OnDisk');
tc.verifyEqual(size(x), [6 50]);
tc.verifyEqual(x(4, :), whole.Values.S.Data(4, :));
tc.verifyEqual(x(2:3, [10 3 3]), whole.Values.S.Data(2:3, [10 3 3]));
tc.verifyEqual(x(end, end), whole.Values.S.Data(end, end));
tc.verifyEqual(x(:, :), whole.Values.S.Data);
tc.verifyEqual(d.Values.ok.Data(:), whole.Values.ok.Data(:));
tc.verifyEqual(d.Values.n.Measured(:), whole.Values.n.Measured(:));
tc.verifyEqual(d.Values.q.Data(), 2.5);
tc.verifyEqual(d.Meta.T_mK, whole.Meta.T_mK);
tc.verifyError(@() x(7, 1), 'lbd:invalid');
d.close();
tc.verifyError(@() x(1, 1), 'lbd:closed');
end

function testOpenModes(tc)
p = bigFile(tc);
d = lbd.open(p);
tc.verifyError(@() d.write(power=1, n=1), 'lbd:readOnly');
tc.verifyError(@() d.save(fullfile(tc.TestData.dir, "nope.lbd")), 'lbd:readOnly');
d.close();
d = lbd.open(p, Mode="r+");
d.write(power=3, S=zeros(1, 50));
d.write(power=5, n=9);
d.Meta.checked = 1;
d.save();
copy = d.save(fullfile(tc.TestData.dir, "copy_" + string(randi(1e9)) + ".lbd"));
tc.verifyEqual(d.Path, p);
d.close();
r = lbd.load(p);
tc.verifyEqual(real(r.Values.S.Data(3, :)), zeros(1, 50));          % MATLAB drops an all-zero imaginary part
tc.verifyEqual(r.Values.n.Data(5), int16(9));
tc.verifyEqual(r.Meta.checked, 1);
c = lbd.load(copy);
tc.verifyEqual(c.Values.S.Data, r.Values.S.Data);
tc.verifyEqual(c.ParentId, r.Id);
end

function testOpenGroupsAndRows(tc)
p = fullfile(tc.TestData.dir, "open_groups.lbd");
groupCase4(true).save(p);
d = lbd.open(p);
closer = onCleanup(@() d.close());
r = d.rows("g", By="A");
tc.verifyEqual(r{3, 2}.Values.g.Data', [310 320 321]);
tc.verifyEqual(d.toDense("f").Values.f.Data(3, :), [30 31 32]);
tc.verifyEqual(d.coords("g").C', [0 0 0 1]);
end
