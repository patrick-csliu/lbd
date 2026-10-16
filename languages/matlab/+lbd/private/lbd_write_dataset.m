function did = lbd_write_dataset(loc, name, data, nd, compression)
% Create and write one dataset. Caller closes the returned dataset id.
[buf, dims] = lbd_layout(data, nd);
[ft, mt, toClose] = lbd_h5_types(data);
cleanTypes = onCleanup(@() cellfun(@H5T.close, toClose));
if nd == 0
    sp = H5S.create('H5S_SCALAR');
else
    sp = H5S.create_simple(nd, dims, []);
end
cleanSpace = onCleanup(@() H5S.close(sp));
dcpl = 'H5P_DEFAULT';
if compression && nd > 0 && numel(data) >= 1024
    dcpl = H5P.create('H5P_DATASET_CREATE');
    H5P.set_chunk(dcpl, chunkDims(dims));
    H5P.set_deflate(dcpl, 4);
end
did = H5D.create(loc, char(name), ft, sp, dcpl);
if ~ischar(dcpl), H5P.close(dcpl); end
if numel(data) > 0
    H5D.write(did, mt, 'H5S_ALL', 'H5S_ALL', 'H5P_DEFAULT', buf);
end
end

function c = chunkDims(dims)
% Halve the largest dimension until a chunk holds at most 2^17 elements.
c = dims;
while prod(c) > 2^17 && any(c > 1)
    [~, k] = max(c);
    c(k) = ceil(c(k) / 2);
end
end
