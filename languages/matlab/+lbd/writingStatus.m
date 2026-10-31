function status = writingStatus(path)
%LBD.WRITINGSTATUS  Is a file being written still measuring?
%   lbd.writingStatus("rabi.lbd.writing")   % "measuring" or "stopped"
%   "measuring": its writer holds the guard lock; "stopped": it doesn't (it crashed, or the
%   script ended or was stopped before finishing) - lbd.recover makes it an .lbd file. Only
%   programs on this computer are seen: a file measured on another computer and synced here
%   is always "stopped". PATH may also be "name.lbd", meaning its .writing file.
arguments
    path (1,1) string
end
p = lbd_writing_path(path);
if ~isfile(p)
    error('lbd:notFound', 'no file being written: %s', p);
end
if ~isempty(lbd_own_writers("get", p))
    status = "measuring";
    return
end
shared = false;
try
    raf = java.io.RandomAccessFile(char(p), 'rw');
catch
    raf = java.io.RandomAccessFile(char(p), 'r');   % read-only: a shared lock tests it as well
    shared = true;
end
cleanup = onCleanup(@() raf.close());
try
    lock = raf.getChannel().tryLock(2^40, 1, shared);
catch err
    if contains(err.message, 'OverlappingFileLockException')
        status = "measuring";                        % held by a Writer in this MATLAB
        return
    end
    rethrow(err);
end
if isempty(lock)
    status = "measuring";
else
    lock.release();
    status = "stopped";
end
end
