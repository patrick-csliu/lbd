function lbd_live_put(fid, path, idx, data, shape)
% Write DATA at the place IDX (one entry per logical dimension: an index, a range, a list of
% indices, or ':') of the dataset at PATH, whose logical size is SHAPE.
nd = numel(shape);
for i = 1:nd                     % indices that aren't one run (points of a group): run by run
    if isnumeric(idx{i}) && numel(idx{i}) > 1 && any(diff(idx{i}(:)) ~= 1)
        count = zeros(1, nd);
        for k = 1:nd
            if ischar(idx{k}) || isstring(idx{k}), count(k) = shape(k); else, count(k) = numel(idx{k}); end
        end
        wasComplex = ~isreal(data);
        block = reshape(data, [count 1]);
        if wasComplex, block = complex(block); end
        list = idx{i}(:);
        starts = [1; find(diff(list) ~= 1) + 1];
        stops = [starts(2:end) - 1; numel(list)];
        for r = 1:numel(starts)
            sub = idx;
            sub{i} = list(starts(r):stops(r));
            pick = repmat({':'}, 1, max(nd, 2));
            pick{i} = starts(r):stops(r);
            part = block(pick{:});
            if wasComplex, part = complex(part); end
            lbd_live_put(fid, path, sub, part, shape);
        end
        return
    end
end
did = H5D.open(fid, char(path));
cleanup = onCleanup(@() H5D.close(did));
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
