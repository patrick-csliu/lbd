function lbd_live_extend(fid, path, n)
% Grow the dataset at PATH to N along its first (logical) dimension.
did = H5D.open(fid, char(path));
cleanup = onCleanup(@() H5D.close(did));
sp = H5D.get_space(did);
[~, dims] = H5S.get_simple_extent_dims(sp);
H5S.close(sp);
dims(1) = n;
H5D.set_extent(did, dims);
end
