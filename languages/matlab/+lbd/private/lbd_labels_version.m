function ver = lbd_labels_version(ver)
%LBD_LABELS_VERSION  The format version of a file once it has labels: 1.3 from 1.0 to 1.2, 2.1
%from 2.0 (spec section 6); a newer version stays.
p = str2double(split(string(ver), "."));
first = [3 1];                   % the first minor version with labels, per major version
if p(2) < first(p(1))
    ver = sprintf("%d.%d", p(1), first(p(1)));
end
ver = string(ver);
end
