function L = lbd_labels_check(v, old, keepTime)
%LBD_LABELS_CHECK  Labels as stored (spec section 1.9): V checked and cleaned, as a struct with
%Star, Project, Users, Tags, Comment and Written. Written becomes the time now when the labels
%differ from OLD, unless V gives another time (or KEEPTIME: labels read from a file).
if nargin < 2 || isempty(old), old = lbd_labels_empty(); end
if nargin < 3, keepTime = false; end
if isempty(v) && ~isstruct(v), v = struct(); end     % [] : no labels
if ~isstruct(v) || ~isscalar(v)
    error('lbd:labels', ['Labels must be a struct like struct("Tags", "calibration", "Star", true), ' ...
        'not a %s'], class(v));
end
known = ["Star" "Project" "Users" "Tags" "Comment" "Written"];
unknown = setdiff(string(fieldnames(v))', known);
if ~isempty(unknown)
    error('lbd:labels', 'Labels: unknown field(s) %s; the labels are Star, Project, Users, Tags, Comment', ...
        strjoin(unknown, ", "));
end
L = lbd_labels_empty();
if isfield(v, 'Star')
    s = v.Star;
    if ~isscalar(s) || ~(islogical(s) || (isnumeric(s) && (s == 0 || s == 1)))
        error('lbd:labels', 'Labels.Star must be true or false');
    end
    L.Star = logical(s);
end
if isfield(v, 'Project')
    p = v.Project;
    if isempty(p) || (isstring(p) && isscalar(p) && strlength(p) == 0)
        L.Project = "";
    elseif (ischar(p) && isrow(p)) || (isstring(p) && isscalar(p))
        L.Project = lbd_label_clean(p, "Labels.Project");
    else
        error('lbd:labels', 'Labels.Project must be one text (or "" for none)');
    end
end
for key = ["Users" "Tags"]
    if ~isfield(v, key), continue; end
    x = v.(key);
    if isempty(x)
        x = strings(1, 0);
    elseif ischar(x) && isrow(x)
        x = string(x);
    elseif iscellstr(x)
        x = string(x);
    elseif ~isstring(x)
        error('lbd:labels', 'Labels.%s must be texts, e.g. ["calibration" "checked"]', key);
    end
    x = arrayfun(@(t) lbd_label_clean(t, "Labels." + key), x(:)');
    if isempty(x), x = strings(1, 0); end
    x = unique(x, 'stable');
    [~, order] = sort(lower(x));
    L.(key) = x(order);
end
if isfield(v, 'Comment')
    c = v.Comment;
    if isempty(c) && ~isstring(c), c = ""; end
    if ~((ischar(c) && (isrow(c) || isempty(c))) || (isstring(c) && isscalar(c)))
        error('lbd:labels', 'Labels.Comment must be one text');
    end
    L.Comment = string(c);
end
given = "";
if isfield(v, 'Written') && ~isempty(v.Written), given = string(v.Written); end
content = @(x) {x.Star, x.Project, x.Users, x.Tags, x.Comment};
if keepTime || (given ~= "" && given ~= old.Written)
    L.Written = given;
elseif ~isequal(content(L), content(old))
    L.Written = string(datetime('now', 'TimeZone', 'UTC', 'Format', "yyyy-MM-dd'T'HH:mm:ss.SSS'Z'"));
else
    L.Written = old.Written;
end
end

function t = lbd_label_clean(t, what)
parts = strtrim(split(string(t), "/"));
if any(parts == "")
    error('lbd:labels', '%s: "%s" is empty or has an empty part; write labels like "Qubit A/Device 3"', what, t);
end
t = strjoin(parts', "/");
end
