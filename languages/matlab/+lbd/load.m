function d = load(path, opts)
%LBD.LOAD  Read an LBD (.lbd) file.
%   d = lbd.load("sweep.lbd")
%   d = lbd.load("sweep.lbd", Values="S21")   % read data of listed values only;
%                                             % the others are described, Data = []
arguments
    path (1,1) string
    opts.Values string = string(missing)
end
loadAll = isscalar(opts.Values) && ismissing(opts.Values);
names = opts.Values;
if loadAll, names = string.empty; end
d = lbd.Dataset.fromFile(path, loadAll, names);
end
