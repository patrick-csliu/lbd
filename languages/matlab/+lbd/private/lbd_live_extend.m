function lbd_live_extend(fid, path, n, dim)
% Grow the dataset at PATH to N along its logical dimension DIM (default 1).
if nargin < 4, dim = 1; end
did = H5D.open(fid, char(path));
cleanup = onCleanup(@() H5D.close(did));
sp = H5D.get_space(did);
[~, dims] = H5S.get_simple_extent_dims(sp);
H5S.close(sp);
dims(dim) = n;
H5D.set_extent(did, dims);
end
