function names = lbd_link_names(gid)
% Names of all links in a group, as a string row vector.
info = H5G.get_info(gid);
names = strings(1, info.nlinks);
for i = 1:info.nlinks
    names(i) = string(H5L.get_name_by_idx(gid, '.', 'H5_INDEX_NAME', 'H5_ITER_INC', i-1, 'H5P_DEFAULT'));
end
end
