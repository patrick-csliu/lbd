function names = lbd_attr_names(loc)
% Names of all attributes on an object (MATLAB has no H5A.exists).
n = H5A.get_num_attrs(loc);
names = strings(1, n);
for i = 0:n-1
    a = H5A.open_by_idx(loc, '.', 'H5_INDEX_NAME', 'H5_ITER_INC', i, 'H5P_DEFAULT', 'H5P_DEFAULT');
    names(i+1) = string(H5A.get_name(a));
    H5A.close(a);
end
end
