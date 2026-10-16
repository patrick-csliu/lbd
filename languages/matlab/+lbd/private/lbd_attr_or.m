function val = lbd_attr_or(loc, name, default)
% Attribute value, or DEFAULT if the attribute doesn't exist.
if any(lbd_attr_names(loc) == string(name))
    val = lbd_read_attr(loc, name);
else
    val = default;
end
end
