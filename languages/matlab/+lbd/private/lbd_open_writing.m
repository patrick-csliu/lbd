function fid = lbd_open_writing(path)
% Open a file being written (spec section 7): SWMR read, HDF5's file locking off where MATLAB can.
fapl = H5P.create('H5P_FILE_ACCESS');
cleanup = onCleanup(@() H5P.close(fapl));
H5P.set_libver_bounds(fapl, 'H5F_LIBVER_LATEST', 'H5F_LIBVER_LATEST');
try
    H5P.set_file_locking(fapl, false, true);
catch err
    % MATLAB's HDF5 interface may lack the switch; SWMR reading works with locking on as well
    if ~strcmp(err.identifier, 'MATLAB:undefinedVarOrClass'), rethrow(err); end
end
fid = H5F.open(path, 64, fapl);              % H5F_ACC_RDONLY | H5F_ACC_SWMR_READ
end
