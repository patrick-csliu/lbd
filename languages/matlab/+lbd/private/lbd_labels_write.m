function lbd_labels_write(fid, L, raiseVersion)
%LBD_LABELS_WRITE  Write /labels (spec section 1.9), replacing it. Nothing for labels never set;
%labels set and all removed again are written empty with their time, so the removal counts.
%RAISEVERSION: an existing file, whose lbd_version is raised to one with labels.
if nargin < 3, raiseVersion = false; end
if H5L.exists(fid, 'labels', 'H5P_DEFAULT'), H5L.delete(fid, 'labels', 'H5P_DEFAULT'); end
if ~lbd_labels_has(L), return; end
if raiseVersion
    ver = lbd_attr_or(fid, 'lbd_version', "");
    new = lbd_labels_version(ver);
    if new ~= ver
        H5A.delete(fid, 'lbd_version');
        lbd_write_attr(fid, 'lbd_version', new);
    end
end
written = L.Written;
if written == ""
    written = string(datetime('now', 'TimeZone', 'UTC', 'Format', "yyyy-MM-dd'T'HH:mm:ss.SSS'Z'"));
end
gid = H5G.create(fid, 'labels', 'H5P_DEFAULT', 'H5P_DEFAULT', 'H5P_DEFAULT');
closer = onCleanup(@() H5G.close(gid));
lbd_write_attr(gid, 'star', int8(L.Star));
if L.Project ~= "", lbd_write_attr(gid, 'project', L.Project); end
lbd_write_attr(gid, 'users', string(jsonencode(cellstr(L.Users))));
lbd_write_attr(gid, 'tags', string(jsonencode(cellstr(L.Tags))));
lbd_write_attr(gid, 'comment', L.Comment);
lbd_write_attr(gid, 'written', written);
end
