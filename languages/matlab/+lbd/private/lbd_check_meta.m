function lbd_check_meta(meta)
%LBD_CHECK_META  Refuse metadata that can't be stored (spec section 1.4), as d.Meta = ... gives
%it: written into a file in memory only, so a mistake shows when it is made, before measuring.
fapl = H5P.create('H5P_FILE_ACCESS');
H5P.set_fapl_core(fapl, 64 * 1024, false);
fid = H5F.create(char("lbd-meta-check-" + string(feature('getpid')) + "-" + string(randi(1e9))), ...
    'H5F_ACC_TRUNC', 'H5P_DEFAULT', fapl);
H5P.close(fapl);
cleanup = onCleanup(@() H5F.close(fid));
gid = H5G.create(fid, 'meta', 'H5P_DEFAULT', 'H5P_DEFAULT', 'H5P_DEFAULT');
groupCleanup = onCleanup(@() H5G.close(gid));
lbd_write_meta(gid, meta, "meta");
end
