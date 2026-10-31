function read_live(path)
% Read a measurement while it is written (tests/crosslang/README.md, "Reading while measuring").
path = string(path);
writing = path + ".writing";
fclose(fopen(fullfile(fileparts(path), "ready-matlab"), 'w'));
started = tic;
while ~isfile(writing) && ~isfile(path)
    if toc(started) > 120
        error('crosslang:live', 'matlab: %s never appeared', writing);
    end
    pause(0.05);
end
state = warning('off', 'lbd:writing');
restore = onCleanup(@() warning(state));
rows = [];
failures = 0;
while isfile(writing)
    try
        d = lbd.load(writing);
    catch err                              % opened before SWMR started, or renamed meanwhile
        failures = failures + 1;
        if failures > 50 && isfile(writing), rethrow(err); end
        pause(0.05);
        continue
    end
    failures = 0;
    rows(end+1) = check(d, false); %#ok<AGROW>
    pause(0.1);
end
n = check(lbd.load(path), true);
growing = rows(rows > 0 & rows < n);
if numel(growing) < 2
    error('crosslang:live', 'only %d live reads; the measurement wasn''t seen while it grew', numel(rows));
end
fprintf('  matlab read a Python measurement live: %d reads, %d ... %d rows, then %d: OK\n', ...
    numel(rows), min(growing), max(growing), n);
end

function n = check(d, final)
s = d.Values.S21.Data;
measured = ~all(isnan(s), 2)';
if ~issorted(fliplr(measured))
    error('crosslang:live', 'measured rows are not a run from the start');
end
for i = find(measured)
    if ~all(s(i, :) == complex(i, i))
        error('crosslang:live', 'row %d is wrong', i);
    end
end
n = numel(d.Axes.time.Data);
if ~isequal(d.Values.T.Data(:), 10 * (0:n-1)')
    error('crosslang:live', 'T is wrong');
end
if final && ~all(measured)
    error('crosslang:live', 'not every row in the finished file');
end
end
