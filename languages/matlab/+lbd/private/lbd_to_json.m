function s = lbd_to_json(x, what)
% Plot/Style may be given as a struct or as JSON text; either way it must be a JSON object.
if nargin < 2, what = "value"; end
if ischar(x) || isstring(x)
    s = string(x);
    if ~isscalar(s)
        error('lbd:invalid', '%s must be one JSON text, not a string array', what);
    end
    try
        decoded = jsondecode(s);
    catch err
        error('lbd:invalid', '%s is not valid JSON: %s', what, err.message);
    end
    if ~isstruct(decoded) || ~isscalar(decoded)
        error('lbd:invalid', '%s must be a JSON object such as {"kind": "heatmap"}', what);
    end
elseif isstruct(x) && isscalar(x)
    s = string(jsonencode(x));
else
    error('lbd:invalid', '%s must be a struct or JSON object text, not a %s', what, class(x));
end
end
