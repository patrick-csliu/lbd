function data = lbd_read_dataset(did)
sp = H5D.get_space(did);
nd = H5S.get_simple_extent_dims(sp);
H5S.close(sp);
data = lbd_from_file_order(H5D.read(did), nd);
end
