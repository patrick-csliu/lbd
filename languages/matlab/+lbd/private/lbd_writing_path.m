function p = lbd_writing_path(path)
% The ".writing" file for PATH (itself, or "name.lbd" + ".writing").
p = string(path);
[~, ~, ext] = fileparts(p);
if lower(ext) == ".writing"
    return
elseif lower(ext) == ".lbd"
    p = p + ".writing";
else
    error('lbd:invalid', '%s is not a file being written (name.lbd.writing)', p);
end
end
