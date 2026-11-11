function L = lbd_labels_empty()
%LBD_LABELS_EMPTY  No labels (spec section 1.9); Written "" : never set.
L = struct('Star', false, 'Project', "", 'Users', strings(1, 0), 'Tags', strings(1, 0), ...
    'Comment', "", 'Written', "");
end
