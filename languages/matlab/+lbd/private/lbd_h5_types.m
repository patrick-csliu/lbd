function [fileType, memType, toClose] = lbd_h5_types(data)
% HDF5 file and memory types for a MATLAB numeric array. Complex -> compound {r, i}.
switch class(data)
    case 'double', f = 'H5T_IEEE_F64LE'; m = 'H5T_NATIVE_DOUBLE'; sz = 8;
    case 'single', f = 'H5T_IEEE_F32LE'; m = 'H5T_NATIVE_FLOAT'; sz = 4;
    case 'int8',   f = 'H5T_STD_I8LE';   m = 'H5T_NATIVE_INT8';  sz = 1;
    case 'int16',  f = 'H5T_STD_I16LE';  m = 'H5T_NATIVE_INT16'; sz = 2;
    case 'int32',  f = 'H5T_STD_I32LE';  m = 'H5T_NATIVE_INT32'; sz = 4;
    case 'int64',  f = 'H5T_STD_I64LE';  m = 'H5T_NATIVE_INT64'; sz = 8;
    case 'uint8',  f = 'H5T_STD_U8LE';   m = 'H5T_NATIVE_UINT8'; sz = 1;
    case 'uint16', f = 'H5T_STD_U16LE';  m = 'H5T_NATIVE_UINT16'; sz = 2;
    case 'uint32', f = 'H5T_STD_U32LE';  m = 'H5T_NATIVE_UINT32'; sz = 4;
    case 'uint64', f = 'H5T_STD_U64LE';  m = 'H5T_NATIVE_UINT64'; sz = 8;
    otherwise
        error('lbd:invalid', 'unsupported data class %s', class(data));
end
toClose = {};
if isreal(data)
    fileType = f; memType = m;
else
    if ~isfloat(data)
        error('lbd:invalid', 'complex integer data is not supported');
    end
    fileType = H5T.create('H5T_COMPOUND', 2*sz);
    H5T.insert(fileType, 'r', 0, f);
    H5T.insert(fileType, 'i', sz, f);
    memType = H5T.create('H5T_COMPOUND', 2*sz);
    H5T.insert(memType, 'r', 0, m);
    H5T.insert(memType, 'i', sz, m);
    toClose = {fileType, memType};
end
end
