% Called by scripts/check_doc_examples.py.
function run_matlab(jsonFile, langDir)
% Run every MATLAB doc block in its own workspace after a shared prelude.
addpath(langDir);
blocks = jsondecode(fileread(jsonFile));
work = tempname; mkdir(work); cd(work);
fails = 0;
for k = 1:numel(blocks)
    b = blocks(k);
    err = '';
    for withValues = [false true]
        err = runBlock(b.code, withValues);
        if isempty(err), break; end
    end
    if isempty(err)
        fprintf('ok   %s\n', b.where);
    else
        fails = fails + 1;
        fprintf('FAIL %s  %s\n', b.where, err);
    end
end
fprintf('%d/%d ok\n', numel(blocks) - fails, numel(blocks));
end

function err = runBlock(code__, withValues__)
err = '';
try
    f = linspace(4e9, 8e9, 401); p = -40:4:0; s21 = exp(1i * (p' * f) * 1e-10);
    t = linspace(0, 1e-6, 201); v = sin(2e7 * t); counts = 1:201;
    d = lbd.Dataset("prelude");
    d.addAxis("power", p, Unit="dBm"); d.addAxis("freq", f, Unit="Hz"); d.addAxis("t", t, Unit="s");
    d.addValue("S21", s21, ["power" "freq"]); d.addValue("trace", v, "t");
    d.save("sweep.lbd"); d.save("big.lbd"); d.save("run.lbd");
    if ~isfolder("data"), mkdir("data"); end
    d.save("data/a.lbd");
    if ~isfolder("out"), mkdir("out"); end
    T = [10 20]; measure = @(x) ones(1, 401); p = p; %#ok<ASGSL>
    if ~withValues__
        d = lbd.Dataset("fresh");
        d.addAxis("power", p, Unit="dBm"); d.addAxis("freq", f, Unit="Hz"); d.addAxis("t", t, Unit="s");
    end
    evalc(code__);
catch e
    err = e.message;
end
end
