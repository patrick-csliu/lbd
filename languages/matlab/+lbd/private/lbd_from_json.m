function x = lbd_from_json(text, base, key)
% A saved /plot attribute as a struct; invalid content gives a warning and is ignored.
x = [];
if strlength(text) == 0, return; end
try
    x = jsondecode(text);
catch
    warning('lbd:json', '%s: /plot/%s is not valid JSON; ignored', base, key);
    return
end
if ~isstruct(x) || ~isscalar(x)
    warning('lbd:json', '%s: /plot/%s must be a JSON object; ignored', base, key);
    x = [];
end
end
