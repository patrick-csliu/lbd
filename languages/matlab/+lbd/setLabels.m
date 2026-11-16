function L = setLabels(path, opts)
%LBD.SETLABELS  Change the labels of an existing file; the data is not touched or rewritten.
%   lbd.setLabels("sweep.lbd", Tags="calibration", Star=true)
%   lbd.setLabels("sweep.lbd", Tags=["checked" "Chip 3/Cooldown 7"], Replace=true)
%   lbd.setLabels("sweep.lbd", Project="")             % no project
%   Only what is given changes. Tags and Users are added to the file's, or with Replace=true
%   replace them. Works on any .lbd file, with or without LBD Viewer; its Library shows the
%   new labels at its next check. Returns the file's labels now (as lbd.labels).
arguments
    path (1,1) string
    opts.Star
    opts.Project
    opts.Users
    opts.Tags
    opts.Comment
    opts.Replace (1,1) logical = false
end
replace = opts.Replace;
given = rmfield(opts, 'Replace');
if isempty(fieldnames(given))
    error('lbd:labels', 'setLabels needs at least one of Star=, Project=, Users=, Tags=, Comment=');
end
lbd_labels_check(given);                         % every label checked before the file is opened
L = lbd_labels_edit(path, "setLabels", @change);

    function L = change(L)
        for key = string(fieldnames(given))'
            if any(key == ["Users" "Tags"]) && ~replace
                L.(key) = [L.(key) string(given.(key))];
            else
                L.(key) = given.(key);
            end
        end
        L = lbd_labels_check(L, [], true);
    end
end
