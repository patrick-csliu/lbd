function lbd_write_attr(loc, name, val)
% Write an attribute: strings as variable-length UTF-8, numbers per spec.
name = char(name);
if ischar(val) || isstring(val) || iscellstr(val)
    t = H5T.copy('H5T_C_S1');
    H5T.set_size(t, 'H5T_VARIABLE');
    H5T.set_cset(t, H5ML.get_constant_value('H5T_CSET_UTF8'));
    if ischar(val) || (isstring(val) && isscalar(val))
        sp = H5S.create('H5S_SCALAR');
        buf = {char(val)};
    else
        s = string(val);
        sp = H5S.create_simple(1, numel(s), []);
        buf = cellstr(s(:));
    end
    a = H5A.create(loc, name, t, sp, 'H5P_DEFAULT');
    H5A.write(a, t, buf);
    H5A.close(a); H5S.close(sp); H5T.close(t);
    return
end
if islogical(val), val = int64(val); end
if isscalar(val)
    nd = 0;
elseif isvector(val)
    nd = 1;
else
    nd = ndims(val);
end
[buf, dims] = lbd_layout(val, nd);
[ft, mt, toClose] = lbd_h5_types(val);
if nd == 0
    sp = H5S.create('H5S_SCALAR');
else
    sp = H5S.create_simple(nd, dims, []);
end
a = H5A.create(loc, name, ft, sp, 'H5P_DEFAULT');
H5A.write(a, mt, buf);
H5A.close(a); H5S.close(sp);
cellfun(@H5T.close, toClose);
end
