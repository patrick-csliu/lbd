function lbd_check_version(ver, base)
tok = regexp(ver, '^(\d+)\.(\d+)$', 'tokens', 'once');
if isempty(tok)
    error('lbd:invalid', '%s: invalid lbd_version "%s"', base, ver);
end
major = str2double(tok{1}); minor = str2double(tok{2});
v = lbd.version();
sup = str2double(split(v.lbd_version, "."));
if major > sup(1)
    error('lbd:version', ['%s uses LBD format %s, but this lbd package (%s) only supports %d.x. ' ...
        'Please update lbd.'], base, ver, v.package, sup(1));
elseif major == sup(1) && minor > sup(2)
    warning('lbd:newerVersion', ['%s uses LBD format %s, newer than %s; some content may be ignored. ' ...
        'Consider updating lbd.'], base, ver, v.lbd_version);
end
end
