function fid = lbd_own_writers(op, path, fid)
% The files lbd.Writer is writing in this MATLAB, with their open HDF5 file: lbd.load reads
% them through it (HDF5 shares one handle per file within a process), and lbd.writingStatus
% says "measuring". OP: "add" (with FID), "remove", "get" (FID or []).
persistent open
if isempty(open), open = containers.Map('KeyType', 'char', 'ValueType', 'any'); end
key = char(java.io.File(char(path)).getAbsolutePath());
if ispc, key = lower(key); end
switch op
    case "add"
        open(key) = fid;
    case "remove"
        if isKey(open, key), remove(open, key); end
        fid = [];
    case "get"
        fid = [];
        if isKey(open, key), fid = open(key); end
end
end
