function check_fixture(root)
% Called by tests/crosslang/run_all.py (see ../language.toml).
files = dir(fullfile(root, '*', 'fixture.lbd'));
failed = false;
for f = files'
    lang = string(regexp(f.folder, '[^\\/]+$', 'match', 'once'));
    try
        checkOne(fullfile(f.folder, f.name));
        fprintf('  matlab reads %-7s OK\n', lang);
    catch err
        failed = true;
        fprintf('  matlab reads %-7s FAILED: %s\n', lang, err.message);
    end
end
for f = dir(fullfile(root, '*', 'live.lbd'))'
    lang = string(regexp(f.folder, '[^\\/]+$', 'match', 'once'));
    try
        checkLive(fullfile(f.folder, f.name));
        fprintf('  matlab reads %-7s live.lbd OK\n', lang);
    catch err
        failed = true;
        fprintf('  matlab reads %-7s live.lbd FAILED: %s\n', lang, err.message);
    end
end
for f = dir(fullfile(root, '*', 'groups.lbd'))'
    lang = string(regexp(f.folder, '[^\\/]+$', 'match', 'once'));
    try
        checkGroups(fullfile(f.folder, f.name));
        fprintf('  matlab reads %-7s groups.lbd OK\n', lang);
    catch err
        failed = true;
        fprintf('  matlab reads %-7s groups.lbd FAILED: %s\n', lang, err.message);
    end
end
if failed
    error('crosslang:failed', 'MATLAB cross-language check failed');
end
end

function checkGroups(p)
d = lbd.load(p);
expect(d.LbdVersion == "2.0", "version 2.0");
expect(isequal(d.Groups.AB.Order, ["A" "B"]) && isequal(d.Groups.PQR.Order, ["P" "Q" "R"]), "group orders");
expect(isequal(double(d.Axes.A.Data(:)'), [1 2 3]), "A");
expect(isequal(double(d.Axes.B.Data(:)'), [10 10 20 15 25 35]), "B");
expect(isequal(d.Axes.B.Parent(:)', int64([1 2 2 3 3 3])), "B parents (from 1)");
expect(d.Axes.A.Unit == "V" && d.Axes.B.Group == "AB" && d.Axes.C.Group == "", "units and groups");
expect(isequal(d.Values.f.Dims, {["A" "B"]}) && isequal(d.Values.h.Dims, {["A" "B"], "C"}), "dims");
expect(isequal(d.Values.f.Data(:)', [110 210 220 315 325 335]), "f");
expect(isequal(d.Values.q.Data(:)', [1.5 3 4.5]), "q");
expect(isequal(size(d.Values.h.Data), [6 3]) && isequal(d.Values.h.Data(6, :), [3 35 38]), "h");
expect(isequal(d.Values.cov.PointShape, [2 2]) && isequal(squeeze(d.Values.cov.Data(5, :, :)), [3 25; 25 -3]), "cov");
expect(isa(d.Values.n.Data, 'int16') && isequal(d.Values.n.Data(:)', int16([1 0 0 0 2 0])), "n");
expect(isequal(d.Values.n.Measured(:)', [true false false false true false]), "n measured");
expect(isequal(double(d.Axes.Q.Data(:)'), [0 0 1 0 1 2]) && isequal(d.Axes.R.Parent(:)', int64([3 5 6 6])), "PQR");
expect(isequal(d.Values.u.Data(:)', [10 20 21 30 31 32]) && isequal(d.Values.w.Data(:)', [210 310 320 321]), "u, w");
m = d.toDense("f");
expect(isequal(m.Axes.B.Data(:)', [10 15 20 25 35]) && isnan(m.Values.f.Data(1, 2)) && m.Values.f.Data(3, 4) == 325, "toDense");
end

function checkLive(p)
expect(~isfile(p + ".writing"), "the .writing file is left");
d = lbd.load(p);
expect(d.Title == "Live – ü", "title: " + d.Title);
s = d.Values.S21.Data;
expect(~isreal(s) && isequal(size(s), [3 3]), "S21 size");
expect(isequal(s(1:2, :), complex([1; 2] * ones(1, 3), ones(2, 1) * (1:3))), "S21 rows 1-2");
expect(all(isnan(s(3, :))), "power 3 is not measured");
expect(isequal(d.Axes.time.Data, [0; 1; 2; 3]), "time");
expect(isequal(d.Values.T.Data, [0; 10; 20; 30]), "T");
expect(isempty(d.Values.T.Measured) && isempty(d.Values.S21.Measured), "no masks for T, S21");
expect(isa(d.Values.n.Data, 'int32') && isequal(d.Values.n.Data, int32([0 3 0; 7 0 0])), "n");
expect(isequal(d.Values.n.Measured, logical([0 1 0; 1 0 0])), "n measured");
expect(isequal(d.Axes.state.Elements, ["ground" "excited"]), "state elements");
end

function checkOne(p)
d = lbd.load(p);
[I, J, K] = ndgrid(0:2, 0:3, 0:1);
expect(d.Title == "Fixture – ünïcode", "title: " + d.Title);
expect(d.Created == "2025-03-01T23:30:00+08:00", "created: " + string(d.Created));
again = fullfile(tempname, "again.lbd");                 % loaded and saved again: created kept
mkdir(fileparts(again));
lbd.load(p).save(again);
expect(lbd.load(again).Created == "2025-03-01T23:30:00+08:00", "created after saving again");
% the identity: a UUID version 7; saved to another file: a new one, the fixture's as its parent
expect(~isempty(d.Id) && ~isempty(regexp(d.Id, '^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$', 'once')), ...
    "id: " + strjoin(string(d.Id), ""));
other = lbd.load(again);
expect(other.Id ~= d.Id && other.ParentId == d.Id, "id after saving to another file");
% a copy of the file saved again to the same place: the same id
copy = fullfile(tempname, "copy.lbd");
mkdir(fileparts(copy));
copyfile(p, copy);
c = lbd.load(copy);
c.save(copy);
expect(lbd.load(copy).Id == d.Id, "id after saving a copy to the same place");
expect(isequal(d.Axes.x.Data, (0:9)'), "x");
expect(isequal([d.Axes.x.Unit d.Axes.a.Unit d.Axes.b.Unit d.Axes.c.Unit], ["s" "V" "A" "Hz"]), "units");
expect(isequal(d.Values.y.Data, ((0:9).^2)'), "y");
expect(d.Values.y.Unit == "s^2", "y unit");
expect(isa(d.Values.k.Data, 'int32') && isequal(d.Values.k.Data, int32((1:10) .* (-1).^(0:9))'), "k");
expect(islogical(d.Values.mask.Data) && isequal(d.Values.mask.Data, (mod(0:9, 2) == 0)'), "mask");
expect(isequal(d.Values.M.Axes, ["a" "b"]) && isequal(size(d.Values.M.Data), [3 4]), "M shape");
expect(isequal(d.Values.M.Data, 10*I(:,:,1) + J(:,:,1)), "M");
expect(~isreal(d.Values.Z.Data) && isequal(d.Values.Z.Data, complex(I(:,:,1) + 1, J(:,:,1) + 1)), "Z");
expect(isequal(d.Values.T.Data, 100*I + 10*J + K), "T");
expect(isempty(d.Values.q.Axes) && d.Values.q.Data == 42.5, "q");
expect(isequal(d.Axes.state.Elements, ["ground" "état 1" "量子"]), "state elements");
expect(isequal(double(d.Axes.state.Data'), [0 1 2]), "state data");
expect(isequal(d.Values.S.Data, [0.5 1.5 2.5]'), "S");
[I2, R2, C2] = ndgrid(0:2, 0:1, 0:1);
expect(isequal(d.Values.C.Axes, "a") && isequal(d.Values.C.PointShape, [2 2]), "C axes");
expect(isequal(d.Values.C.Elements{1}, ["I" "Q"]) && isempty(d.Values.C.Elements{2}), "C elements");
expect(~isfield(d.Axes, "C_dim1") && d.Axes.a.Role == "", "roles");
expect(isequal(d.Values.C.Data, 100*I2 + 10*R2 + C2), "C");
m = d.Meta;
expect(m.sample == "chip – é", "meta sample");
expect(m.T_mK == 12, "meta T_mK");
expect(isequal(m.names, ["a" "b"]), "meta names");
expect(isequal(double(m.vec(:)'), [1 2 3]), "meta vec");
expect(isequal(double(m.mat), [0 1 2; 3 4 5]), "meta mat");
expect(m.vna.ifbw_Hz == 1000 && m.vna.averages == 4, "meta vna");
expect(string(d.Plot.kind) == "heatmap" && isequal(string(d.Plot.values), "M"), "plot");
expect(d.StyleName == "thesis", "style_name");
expect(isscalar(d.Matplotlib) && strlength(d.Matplotlib) > 0, "matplotlib version");
end

function expect(cond, what)
if ~cond
    error('crosslang:mismatch', 'mismatch: %s', what);
end
end
