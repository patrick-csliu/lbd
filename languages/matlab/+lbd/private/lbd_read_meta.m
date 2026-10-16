function s = lbd_read_meta(gid, where)
% Read attributes and sub-groups of a group into a (nested) struct.
% Keys that are not valid MATLAB names are renamed (warning lbd:metaKey); keys that collide after
% renaming, and HDF5 datasets inside /meta (LBD stores metadata as attributes), give a warning
% instead of being lost silently.
if nargin < 2, where = "/meta"; end
s = struct();
origin = struct();
for name = lbd_attr_names(gid)
    [s, origin] = put(s, origin, name, lbd_read_attr(gid, name), where);
end
for name = lbd_link_names(gid)
    oid = H5O.open(gid, char(name), 'H5P_DEFAULT');
    oinfo = H5O.get_info(oid);
    H5O.close(oid);
    if oinfo.type == H5ML.get_constant_value('H5O_TYPE_GROUP')
        sub = H5G.open(gid, char(name));
        [s, origin] = put(s, origin, name, lbd_read_meta(sub, where + "/" + name), where);
        H5G.close(sub);
    else
        warning('lbd:metaDataset', '%s/%s is a dataset; LBD metadata are attributes, so it is skipped', ...
            where, name);
    end
end
end

function [s, origin] = put(s, origin, name, value, where)
f = matlab.lang.makeValidName(char(name));
if ~strcmp(f, char(name))
    warning('lbd:metaKey', 'meta key "%s" is not a valid MATLAB field name; read as "%s"', name, f);
end
if isfield(s, f)
    warning('lbd:metaCollision', ['%s: the keys "%s" and "%s" both become the field "%s"; ' ...
        'only "%s" is kept'], where, origin.(f), name, f, name);
end
s.(f) = value;
origin.(f) = char(name);
end
