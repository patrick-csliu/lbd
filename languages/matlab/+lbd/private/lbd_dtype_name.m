function name = lbd_dtype_name(data)
% LBD dtype name (shared with Python/Julia) for a MATLAB array.
switch class(data)
    case 'double', base = "float64";
    case 'single', base = "float32";
    case 'logical', name = "bool"; return
    case {'int8','int16','int32','int64','uint8','uint16','uint32','uint64'}
        name = string(class(data)); return
    otherwise
        error('lbd:invalid', 'unsupported data class %s', class(data));
end
if ~isreal(data)
    if base == "float64", name = "complex128"; else, name = "complex64"; end
else
    name = base;
end
end
