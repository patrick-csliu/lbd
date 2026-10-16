function lbd_write_meta(gid, s, where)
% Write a struct as attributes of group GID; nested structs become sub-groups.
fields = fieldnames(s);
for k = 1:numel(fields)
    key = fields{k};
    v = s.(key);
    here = where + "/" + key;
    if isstruct(v)
        if ~isscalar(v)
            error('lbd:invalid', '%s: struct arrays can''t be stored in meta', here);
        end
        sub = H5G.create(gid, key, 'H5P_DEFAULT', 'H5P_DEFAULT', 'H5P_DEFAULT');
        lbd_write_meta(sub, v, here);
        H5G.close(sub);
    elseif isdatetime(v)
        lbd_write_attr(gid, key, string(v, "yyyy-MM-dd'T'HH:mm:ss"));
    elseif ischar(v) || isstring(v) || iscellstr(v)
        if ~ischar(v) && ~isvector(string(v))
            error('lbd:invalid', '%s: string arrays in meta must be 1-D', here);
        end
        if isstring(v) && any(ismissing(v))
            error('lbd:invalid', '%s: missing strings can''t be stored', here);
        end
        lbd_write_attr(gid, key, v);
    elseif isnumeric(v) || islogical(v)
        if isempty(v)
            error('lbd:invalid', '%s: empty values can''t be stored; remove the field instead', here);
        end
        lbd_write_attr(gid, key, v);
    else
        error('lbd:invalid', '%s: can''t store value of class %s in meta', here, class(v));
    end
end
end
