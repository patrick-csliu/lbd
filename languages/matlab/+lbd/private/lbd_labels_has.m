function tf = lbd_labels_has(L)
%LBD_LABELS_HAS  Whether the file gets a /labels group: labels set, or set and all removed again.
tf = L.Star || L.Project ~= "" || ~isempty(L.Users) || ~isempty(L.Tags) || L.Comment ~= "" || L.Written ~= "";
end
