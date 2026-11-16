function d = open(path, opts)
%LBD.OPEN  Open an LBD (.lbd) file to read only what is needed: the structure now, value data
%   when it is indexed. Each value's Data is an lbd.OnDisk: Data(4, :) reads row 4 only,
%   size(Data) reads nothing, Data(:, :) reads it all. coords, rows and toDense read only what
%   they need. Close it with d.close(); what was read stays usable.
%
%   d = lbd.open("big.lbd");
%   row = d.Values.S21.Data(4, :);
%   d.close();
%
%   Mode="r" (default): read only; write and save are refused. Mode="r+": write puts data into
%   the file at points that exist (no new points or axes), d.save() rewrites the description,
%   metadata and saved view in place, d.save("copy.lbd") copies the file piece by piece.
%   A file being written (.lbd.writing) opens with Mode="r", as it was at that moment.
arguments
    path (1,1) string
    opts.Mode (1,1) string = "r"
end
if ~any(opts.Mode == ["r" "r+"])
    error('lbd:invalid', 'Mode must be "r" (read) or "r+" (read and write), not "%s"', opts.Mode);
end
if endsWith(lower(path), ".writing") && opts.Mode ~= "r"
    [~, name, ext] = fileparts(path);
    error('lbd:invalid', '%s is being written by a measurement: open it with Mode="r"', name + ext);
end
d = lbd.Dataset.fromFile(path, false, string.empty);      % the structure; no value data
d.attachSource(lbd.LazySource(path, opts.Mode));
end
