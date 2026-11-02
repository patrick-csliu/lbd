function beat = lbd_live_beat(action, beat, varargin)
%LBD_LIVE_BEAT The heartbeat file name.lbd.live of a measurement (spec section 7, plan 9).
%   beat = lbd_live_beat("new", [], writingPath, dataset, program)
%   beat = lbd_live_beat("record", beat, puts)      a write's puts (name, idx), counted
%   [tf]  = lbd_live_beat("due", beat)              rewrite now?
%   beat = lbd_live_beat("write", beat)             rewrite the file (a failure is said once)
%   lbd_live_beat("remove", beat)                   the measurement finished
%
%   Each value's sweep dimensions written one position at a time (the "stepped" ones, e.g.
%   power) get a small array of how much of each position was written; the dimensions given
%   whole in a write (a trace along frequency) count as per_write. So every point is counted
%   once, without a mask as large as the value. Times are seconds on this computer's clock;
%   other computers judge by when they saw the file change, never by comparing clocks.
BEAT_EVERY = 30;    % seconds: rewritten at least this often
LIVE_EVERY = 5;     % and at most this often when the progress changed
RATE_WINDOW = 300;  % seconds of recent progress the rate is taken from
MASK_LIMIT = 1e7;   % stepped positions counted one by one up to this many
switch action
    case "new"
        [writingPath, d, program] = varargin{:};
        beat = struct();
        beat.Path = extractBefore(writingPath, strlength(writingPath) - strlength(".writing") + 1) + ".live";
        beat.D = d;
        beat.Program = program;
        try
            beat.Computer = string(java.net.InetAddress.getLocalHost().getHostName());
        catch
            beat.Computer = string(getenv('COMPUTERNAME'));
        end
        beat.Clock = tic;
        beat.Started = nowText();
        beat.Values = struct();
        beat.Changed = true;
        beat.LastWritten = [];
        beat.LastCall = [];
        beat.LongestGap = 0;
        beat.Failed = false;
    case "record"
        puts = varargin{1};
        t = toc(beat.Clock);
        if ~isempty(beat.LastCall), beat.LongestGap = max(beat.LongestGap, t - beat.LastCall); end
        beat.LastCall = t;
        for k = 1:numel(puts)
            p = puts{k};
            name = char(p.name);
            if ~isfield(beat.Values, name)
                beat.Values.(name) = newValue(beat.D, beat.D.Values.(name));
            end
            beat.Values.(name) = addWrite(beat.Values.(name), p.idx, t, MASK_LIMIT, RATE_WINDOW);
        end
        beat.Changed = true;
    case "due"
        t = toc(beat.Clock);
        beat = isempty(beat.LastWritten) || t - beat.LastWritten >= BEAT_EVERY || ...
            (beat.Changed && t - beat.LastWritten >= LIVE_EVERY);
    case "write"
        beat.LastWritten = toc(beat.Clock);
        beat.Changed = false;
        s = struct('lbd_live', 1, 'computer', beat.Computer, 'process', feature('getpid'), ...
            'program', beat.Program, 'started', beat.Started, 'updated', nowText(), ...
            'beat_every', BEAT_EVERY, 'longest_gap', round(beat.LongestGap, 3), 'values', struct());
        for name = string(fieldnames(beat.Values))'
            s.values.(name) = info(beat.Values.(name));
        end
        tmp = beat.Path + ".tmp";
        try
            fid = fopen(tmp, 'w', 'n', 'UTF-8');
            if fid < 0, error('lbd:live', 'can''t create %s', tmp); end
            fwrite(fid, jsonencode(s), 'char');
            fclose(fid);
            [ok, msg] = movefile(tmp, beat.Path, 'f');
            if ~ok, error('lbd:live', '%s', msg); end
        catch err
            if ~beat.Failed
                beat.Failed = true;
                [~, n, e] = fileparts(beat.Path);
                warning('lbd:live', ['%s (how far the measurement is, for other computers) can''t be written: %s; ' ...
                    'the measurement goes on'], n + e, err.message);
            end
            if isfile(tmp), delete(tmp); end
        end
    case "remove"
        for p = [beat.Path, beat.Path + ".tmp"]
            if isfile(p), delete(p); end
        end
end
end

function t = nowText()
t = string(datetime('now', 'TimeZone', 'local', 'Format', "yyyy-MM-dd'T'HH:mm:ssxxx"));
end

function vp = newValue(d, v)
vp.Names = strings(1, numel(v.Dims));
vp.Lengths = NaN(1, numel(v.Dims));
for i = 1:numel(v.Dims)
    a = d.Axes.(v.Dims{i}(end));
    vp.Names(i) = v.Dims{i}(end);
    if ~(a.Grows || strlength(a.Group) > 0), vp.Lengths(i) = numel(a.Data); end
end
vp.Total = NaN;
if all(~isnan(vp.Lengths)), vp.Total = prod(vp.Lengths); end
vp.Points = 0;
vp.Stepped = [];
vp.Started = false;
vp.PerWrite = 1;
vp.Mask = [];
vp.Axes = struct('index', {}, 'steps', {}, 'first', {}, 'last', {});
vp.Samples = zeros(0, 2);
end

function n = cells(k, len)
if ischar(k) || isstring(k)        % ':' every position
    n = len;
    if isnan(n), n = 0; end
else
    n = numel(k);
end
end

function vp = addWrite(vp, idx, t, maskLimit, window)
nd = numel(vp.Lengths);
sweep = idx(1:nd);
scalar = cellfun(@(k) isnumeric(k) && isscalar(k), sweep);
if ~vp.Started
    vp.Started = true;
    vp.Stepped = find(scalar);
    if ~isnan(vp.Total)
        vp.PerWrite = prod(vp.Lengths(setdiff(1:nd, vp.Stepped)));
        shape = vp.Lengths(vp.Stepped);
        if prod(shape) <= maskLimit
            vp.Mask = zeros([shape 1 1], 'single');
        end
    end
    for i = 1:nd
        vp.Axes(i) = struct('index', NaN, 'steps', 0, 'first', NaN, 'last', NaN);
    end
end
c = arrayfun(@(i) cells(sweep{i}, vp.Lengths(i)), 1:nd);
written = prod(c);
if ~isempty(vp.Mask)
    sel = sweep(vp.Stepped);
    others = prod(c(setdiff(1:nd, vp.Stepped)));
    if isempty(sel), sel = {1}; end
    before = sum(vp.Mask(sel{:}), 'all');
    vp.Mask(sel{:}) = min(vp.Mask(sel{:}) + others / max(vp.PerWrite, 1), 1);
    vp.Points = min(round(vp.Points + (sum(vp.Mask(sel{:}), 'all') - before) * vp.PerWrite), vp.Total);
elseif ~isnan(vp.Total)
    vp.Points = min(vp.Points + written, vp.Total);
else
    vp.Points = vp.Points + written;
end
for i = vp.Stepped
    k = sweep{i};
    if ~(isnumeric(k) && isscalar(k)) || isnan(vp.Lengths(i)), continue; end
    a = vp.Axes(i);
    if ~isequal(a.index, k - 1)          % kept from 0, as in the file's other languages
        if isnan(a.index), a.first = t; else, a.steps = a.steps + 1; a.last = t; end
        a.index = k - 1;
    end
    vp.Axes(i) = a;
end
vp.Samples(end+1, :) = [t vp.Points];
while size(vp.Samples, 1) > 2 && t - vp.Samples(2, 1) > window
    vp.Samples(1, :) = [];
end
end

function s = info(vp)
rate = NaN;
if size(vp.Samples, 1) >= 2 && vp.Samples(end, 1) > vp.Samples(1, 1)
    rate = round((vp.Samples(end, 2) - vp.Samples(1, 2)) / (vp.Samples(end, 1) - vp.Samples(1, 1)), 6);
end
axes = struct('name', {}, 'index', {}, 'length', {}, 'step_seconds', {});
for i = vp.Stepped
    a = vp.Axes(i);
    if isnan(vp.Lengths(i)) || isnan(a.index), continue; end
    step = NaN;
    if a.steps > 0, step = round((a.last - a.first) / a.steps, 3); end
    axes(end+1) = struct('name', vp.Names(i), 'index', a.index, 'length', vp.Lengths(i), 'step_seconds', step); %#ok<AGROW>
end
s = struct('points', vp.Points, 'total', vp.Total, 'per_write', vp.PerWrite, 'rate', rate, ...
    'axes', {num2cell(axes)});       % a cell: always a JSON list, even of one axis
end
