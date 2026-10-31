function ver = lbd_version_needed(d)
%LBD_VERSION_NEEDED  The lowest format version that holds d's content (spec section 6): 2.0
%with an axis group, 1.2 without.
if isempty(fieldnames(d.Groups))
    ver = "1.2";
else
    ver = "2.0";
end
end
