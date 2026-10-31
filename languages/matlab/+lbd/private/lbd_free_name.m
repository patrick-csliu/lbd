function p = lbd_free_name(path)
% PATH, or "name (2).lbd", "name (3).lbd" ... if it is taken.
p = string(path);
[folder, name, ext] = fileparts(p);
k = 2;
while isfile(p)
    p = fullfile(folder, name + " (" + k + ")" + ext);
    k = k + 1;
end
end
