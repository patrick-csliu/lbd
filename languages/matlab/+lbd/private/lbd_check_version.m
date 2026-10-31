function lbd_check_version(ver, base)
tok = regexp(ver, '^(\d+)\.(\d+)$', 'tokens', 'once');
if isempty(tok)
    error('lbd:invalid', '%s: invalid lbd_version "%s"', base, ver);
end
major = str2double(tok{1}); minor = str2double(tok{2});
v = lbd.version();
sup = str2double(split(v.lbd_version, "."));
latestMinor = [2 0];            % the newest minor version known, per major version (1.2, 2.0)
if major > sup(1)
    error('lbd:version', ['%s uses LBD format %s, but this lbd package (%s) only supports formats ' ...
        'up to %d.x. Please update lbd.'], base, ver, v.package, sup(1));
elseif major < 1
    error('lbd:invalid', '%s: LBD format %s doesn''t exist (the first version is 1.0)', base, ver);
elseif minor > latestMinor(major)
    warning('lbd:newerVersion', ['%s uses LBD format %s, newer than %d.%d; some content may be ' ...
        'ignored. Consider updating lbd.'], base, ver, major, latestMinor(major));
end
end
