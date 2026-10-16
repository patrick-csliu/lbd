function [shape, dtype] = lbd_describe_dataset(did)
% Logical shape (row vector, C order) and LBD dtype name of a dataset.
sp = H5D.get_space(did);
[nd, dims] = H5S.get_simple_extent_dims(sp);
H5S.close(sp);
if nd == 0
    shape = zeros(1, 0);
else
    shape = double(dims(:)');
end
if lbd_attr_or(did, 'lbd_bool', 0) == 1
    dtype = "bool";
    return
end
t = H5D.get_type(did);
dtype = typeName(t);
H5T.close(t);
end

function name = typeName(t)
cls = H5T.get_class(t);
sz = H5T.get_size(t);
if cls == H5ML.get_constant_value('H5T_FLOAT')
    name = "float" + string(8*sz);
elseif cls == H5ML.get_constant_value('H5T_INTEGER')
    if H5T.get_sign(t) == H5ML.get_constant_value('H5T_SGN_NONE')
        name = "uint" + string(8*sz);
    else
        name = "int" + string(8*sz);
    end
elseif cls == H5ML.get_constant_value('H5T_COMPOUND')
    name = "complex" + string(8*sz);
else
    error('lbd:invalid', 'a value uses an HDF5 type LBD does not support (class %d)', cls);
end
end
