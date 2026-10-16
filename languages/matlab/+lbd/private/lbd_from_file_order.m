function data = lbd_from_file_order(data, nd)
% Undo the C-order layout after a read (spec section 2). Handles complex compounds.
if isstruct(data) && isfield(data, 'r') && isfield(data, 'i')
    % Reshape the parts first: MATLAB drops an all-zero imaginary part when
    % reshaping a complex array, which would silently turn complex data real.
    data = complex(reorder(data.r, nd), reorder(data.i, nd));
else
    data = reorder(data, nd);
end
end

function data = reorder(data, nd)
if nd == 1
    data = data(:);
elseif nd >= 2
    data = permute(data, nd:-1:1);
end
end
