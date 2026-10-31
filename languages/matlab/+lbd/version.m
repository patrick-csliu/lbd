function v = version()
%LBD.VERSION  Package version and the newest LBD format version it reads and writes (a file is
%written with the lowest version its content needs).
v = struct('package', "1.3.0-dev", 'lbd_version', "2.0");
end
