function text = lbd_created_text(value)
%LBD_CREATED_TEXT  Created as stored: ISO-8601 text with a UTC offset.
%   A datetime without a time zone is taken in this computer's time zone. A text is kept as
%   written; one without an offset gets this computer's offset. Anything else is an error.
bad = sprintf(['created must be a date and time: a datetime, or ISO-8601 text such as ' ...
    '"2026-10-13T16:09:00+08:00", not %s'], lbd_show(value));
if isdatetime(value) && isscalar(value) && ~isnat(value)
    if isempty(value.TimeZone), value.TimeZone = 'local'; end
    value.Format = "yyyy-MM-dd'T'HH:mm:ssxxx";
    text = string(value);
    return
end
if ~((isstring(value) && isscalar(value)) || ischar(value))
    error('lbd:invalid', '%s', bad);
end
t = strtrim(string(value));
tok = regexp(t, '^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$', ...
    'tokens', 'once');
if isempty(tok)
    error('lbd:invalid', '%s', bad);
end
n = str2double(tok(1:5));
if n(2) < 1 || n(2) > 12 || n(3) < 1 || n(3) > eomday(n(1), n(2)) || n(4) > 23 || n(5) > 59
    error('lbd:invalid', '%s', bad);
end
if strlength(tok(end)) > 0                  % the offset (MATLAB leaves out the nested seconds token)
    text = t;
else                                        % no offset: this computer's at that time
    local = datetime(n(1), n(2), n(3), n(4), n(5), 0, 'TimeZone', 'local', 'Format', "xxx");
    text = t + string(local);
end
end

function s = lbd_show(value)
if isstring(value) || ischar(value)
    s = sprintf('"%s"', string(value));
elseif isnumeric(value) && isscalar(value)
    s = num2str(value);
else
    s = class(value);
end
end
