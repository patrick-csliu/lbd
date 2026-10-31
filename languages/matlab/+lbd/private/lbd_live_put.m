function lbd_live_put(fid, path, idx, data, shape)
% Write DATA at the place IDX (one entry per logical dimension: an index, a range, or ':') of
% the dataset at PATH, whose logical size is SHAPE.
did = H5D.open(fid, char(path));
cleanup = onCleanup(@() H5D.close(did));
nd = numel(shape);
wasComplex = ~isreal(data);
[~, mt, toClose] = lbd_h5_types(data);
cleanTypes = onCleanup(@() cellfun(@H5T.close, toClose));
if nd == 0
    [buf, ~] = lbd_layout(data, 0);
    H5D.write(did, mt, 'H5S_ALL', 'H5S_ALL', 'H5P_DEFAULT', buf);
    return
end
start = zeros(1, nd);
count = zeros(1, nd);
for i = 1:nd
    if ischar(idx{i}) || isstring(idx{i})
        count(i) = shape(i);
    else
        start(i) = idx{i}(1) - 1;
        count(i) = numel(idx{i});
    end
end
block = reshape(data, [count 1]);
if wasComplex, block = complex(block); end       % reshape may drop an all-zero imaginary part
[buf, ~] = lbd_layout(block, nd);
fs = H5D.get_space(did);
cleanFile = onCleanup(@() H5S.close(fs));
H5S.select_hyperslab(fs, 'H5S_SELECT_SET', start, [], count, []);
ms = H5S.create_simple(nd, count, []);
cleanMem = onCleanup(@() H5S.close(ms));
H5D.write(did, mt, ms, fs, 'H5P_DEFAULT', buf);
end
