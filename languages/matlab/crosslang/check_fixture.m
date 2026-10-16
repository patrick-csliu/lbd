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
if failed
    error('crosslang:failed', 'MATLAB cross-language check failed');
end
end

function checkOne(p)
d = lbd.load(p);
[I, J, K] = ndgrid(0:2, 0:3, 0:1);
expect(d.Title == "Fixture – ünïcode", "title: " + d.Title);
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
