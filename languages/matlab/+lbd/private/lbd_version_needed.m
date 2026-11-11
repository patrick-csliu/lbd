function ver = lbd_version_needed(d)
%LBD_VERSION_NEEDED  The lowest format version that holds d's content (spec section 6): 1.2 for a
%grid, 2.0 with an axis group; 1.3 and 2.1 with labels.
if isempty(fieldnames(d.Groups))
    ver = "1.2";
else
    ver = "2.0";
end
if lbd_labels_has(d.Labels)
    ver = lbd_labels_version(ver);
end
end
