function [buf, dims] = lbd_layout(data, nd)
% Arrange a MATLAB array for writing so that the HDF5 (C-order) dims equal the
% logical size, per spec section 2. Returns dims in C order (= logical order).
isComplex = ~isreal(data);
if isComplex
    re = real(data); im = imag(data);
else
    re = data; im = [];
end
if nd == 0
    dims = [];
elseif nd == 1
    dims = numel(data);
    re = re(:); im = im(:);
else
    dims = size(data, 1:nd);
    re = permute(re, nd:-1:1);
    if isComplex, im = permute(im, nd:-1:1); end
end
if isComplex
    buf = struct('r', re, 'i', im);
else
    buf = re;
end
end
