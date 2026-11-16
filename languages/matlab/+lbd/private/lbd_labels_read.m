function L = lbd_labels_read(fid, base)
%LBD_LABELS_READ  The file's /labels (spec section 1.9) as a labels struct; no labels if it has
%none. A label that can't be read is left out with a warning; the others are read.
L = lbd_labels_empty();
if ~H5L.exists(fid, 'labels', 'H5P_DEFAULT'), return; end
oid = H5O.open(fid, 'labels', 'H5P_DEFAULT');
isGroup = H5I.get_type(oid) == H5ML.get_constant_value('H5I_GROUP');
H5O.close(oid);
if ~isGroup
    warning('lbd:badLabels', '%s: /labels is not a group; reading the file without its labels', base);
    return
end
gid = H5G.open(fid, 'labels');
closer = onCleanup(@() H5G.close(gid));
names = lbd_attr_names(gid);
v = struct();
for key = ["star" "project" "users" "tags" "comment"]
    if ~any(names == key), continue; end
    field = upper(extractBefore(key, 2)) + extractAfter(key, 1);
    try
        raw = lbd_read_attr(gid, key);
        switch key
            case "star"
                if ~isnumeric(raw) || ~isscalar(raw) || ~(raw == 0 || raw == 1)
                    error('lbd:labels', 'expected 0 or 1');
                end
                raw = logical(raw);
            case {"users" "tags"}
                items = jsondecode(char(raw));
                if isempty(items) && ~ischar(items)
                    items = strings(1, 0);
                elseif iscellstr(items) || ischar(items)
                    items = string(items);
                else
                    error('lbd:labels', 'expected a JSON list of labels');
                end
                raw = items(:)';
        end
        v.(field) = raw;
        lbd_labels_check(v, [], true);           % one bad label never hides the others
    catch err
        v = rmfield(v, field);
        warning('lbd:badLabel', '%s: the label ''%s'' can''t be read (%s); reading the file without it', ...
            base, key, err.message);
    end
end
if any(names == "written"), v.Written = string(lbd_read_attr(gid, 'written')); end
L = lbd_labels_check(v, [], true);
end
