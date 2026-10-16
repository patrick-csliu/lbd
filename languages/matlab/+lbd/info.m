function d = info(path)
%LBD.INFO  Read everything in an LBD file except value data. Cheap, even for large files.
arguments
    path (1,1) string
end
d = lbd.Dataset.fromFile(path, false, string.empty);
end
