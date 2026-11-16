function L = labels(path)
%LBD.LABELS  The labels stored in a file: a struct with Star, Project, Users, Tags, Comment and
%Written (when they were set, UTC); every field empty (Written "") if the file has none.
%   L = lbd.labels("sweep.lbd"); L.Tags
%   Reads only the file's description, not its data.
arguments
    path (1,1) string
end
[~, name, ext] = fileparts(path);
base = name + ext;
if ~isfile(path)
    error('lbd:notFound', 'no such file: %s', path);
end
fid = H5F.open(path, 'H5F_ACC_RDONLY', 'H5P_DEFAULT');
closer = onCleanup(@() H5F.close(fid));
if lbd_attr_or(fid, 'lbd_format', "") ~= "LBD"
    error('lbd:invalid', '%s is not an LBD file (missing lbd_format="LBD")', base);
end
lbd_check_version(string(lbd_attr_or(fid, 'lbd_version', "")), base);
L = lbd_labels_read(fid, base);
end
