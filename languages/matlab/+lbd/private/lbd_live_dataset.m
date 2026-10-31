function did = lbd_live_dataset(loc, name, dtype, shape, grows, fill)
% A chunked dataset for lbd.Writer: logical SHAPE (C order), reading FILL (NaN, or 0) where
% nothing was written; GROWS: unlimited along its first dimension. Caller closes it.
sample = sampleOf(dtype);
[ft, mt, toClose] = lbd_h5_types(sample);
cleanTypes = onCleanup(@() cellfun(@H5T.close, toClose));
nd = numel(shape);
dcpl = H5P.create('H5P_DATASET_CREATE');
cleanPlist = onCleanup(@() H5P.close(dcpl));
if nd == 0
    sp = H5S.create('H5S_SCALAR');
else
    maxdims = num2cell(shape);
    if grows, maxdims{1} = 'H5S_UNLIMITED'; end
    sp = H5S.create_simple(nd, shape, maxdims);
    chunk = max(shape, 1);
    if grows, chunk(1) = max(1, floor(8192 / max(1, prod(chunk(2:end))))); end
    while prod(chunk) > 2^17 && any(chunk > 1)
        [~, k] = max(chunk);
        chunk(k) = ceil(chunk(k) / 2);
    end
    H5P.set_chunk(dcpl, chunk);
end
cleanSpace = onCleanup(@() H5S.close(sp));
if ~isreal(sample)
    H5P.set_fill_value(dcpl, mt, struct('r', cast(fill, class(sample)), 'i', cast(fill, class(sample))));
else
    H5P.set_fill_value(dcpl, mt, cast(fill, class(sample)));
end
did = H5D.create(loc, char(name), ft, sp, 'H5P_DEFAULT', dcpl, 'H5P_DEFAULT');
end

function x = sampleOf(dtype)
switch dtype
    case "float64", x = 0;
    case "float32", x = single(0);
    case "complex128", x = complex(0, 0);
    case "complex64", x = complex(single(0), single(0));
    case "bool", x = uint8(0);
    otherwise, x = zeros(1, char(dtype));
end
end
