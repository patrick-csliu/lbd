function L = lbd_labels_edit(path, what, change)
%LBD_LABELS_EDIT  Change the labels of an existing file in place: CHANGE(L) returns the new
%labels; they get the time now. The data is not touched. A file being written is refused.
path = string(path);
[~, name, ext] = fileparts(path);
base = name + ext;
if endsWith(lower(path), ".writing")
    error('lbd:writing', ['%s is still being written: %s can''t change it. Labels given to the ' ...
        'lbd.Writer (w.Labels) are written when it finishes; or change the finished file'], base, what);
end
if lower(ext) ~= ".lbd"
    warning('lbd:extension', '%s: LBD files should use the .lbd extension', base);
end
if ~isfile(path)
    error('lbd:notFound', 'no such file: %s', path);
end
fid = H5F.open(path, 'H5F_ACC_RDWR', 'H5P_DEFAULT');
closer = onCleanup(@() H5F.close(fid));
if lbd_attr_or(fid, 'lbd_format', "") ~= "LBD"
    error('lbd:invalid', '%s is not an LBD file (missing lbd_format="LBD")', base);
end
lbd_check_version(string(lbd_attr_or(fid, 'lbd_version', "")), base);
old = lbd_labels_read(fid, base);
L = change(old);
L.Written = string(datetime('now', 'TimeZone', 'UTC', 'Format', "yyyy-MM-dd'T'HH:mm:ss.SSS'Z'"));
lbd_labels_write(fid, L, true);
end
