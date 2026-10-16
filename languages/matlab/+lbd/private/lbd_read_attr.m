function val = lbd_read_attr(loc, name)
% Read one attribute. Strings become MATLAB strings; arrays use logical order.
a = H5A.open(loc, char(name));
c = onCleanup(@() H5A.close(a));
t = H5A.get_type(a);
isStr = H5T.get_class(t) == H5ML.get_constant_value('H5T_STRING');
H5T.close(t);
sp = H5A.get_space(a);
nd = H5S.get_simple_extent_dims(sp);
H5S.close(sp);
raw = H5A.read(a);
if isStr
    if iscell(raw)
        val = string(raw(:))';
    elseif nd == 0
        val = string(raw(:)');
    else
        % fixed-length string array: one string per column
        val = string(cellstr(raw'))';
    end
    val = erase(val, char(0));
else
    val = lbd_from_file_order(raw, nd);
end
end
