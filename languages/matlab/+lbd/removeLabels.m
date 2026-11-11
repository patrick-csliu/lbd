function L = removeLabels(path, opts)
%LBD.REMOVELABELS  Remove tags and users from an existing file's labels; the data is not touched.
%   lbd.removeLabels("sweep.lbd", Tags="calibration")
%   A label the file doesn't have is ignored. Returns the file's labels now (as lbd.labels).
arguments
    path (1,1) string
    opts.Tags string = strings(1, 0)
    opts.Users string = strings(1, 0)
end
probe = lbd_labels_check(struct('Tags', opts.Tags, 'Users', opts.Users));   % checked first
L = lbd_labels_edit(path, "removeLabels", @change);

    function L = change(L)
        L.Tags = setdiff(L.Tags, probe.Tags, 'stable');
        L.Users = setdiff(L.Users, probe.Users, 'stable');
        if isempty(L.Tags), L.Tags = strings(1, 0); end
        if isempty(L.Users), L.Users = strings(1, 0); end
    end
end
