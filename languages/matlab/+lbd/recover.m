function path = recover(path)
%LBD.RECOVER  Make a stopped .writing file into an .lbd file with everything it holds.
%   lbd.recover("rabi.lbd.writing")   % returns "rabi.lbd"
%   A Writer that stopped before finishing (a crash, an error, a script ended without close)
%   leaves "name.lbd.writing"; this copies what was written into "name.lbd" (or "name (2).lbd"
%   ... if that is taken), checks the copy, and removes the .writing file. Points never
%   measured stay NaN (or masked). The file keeps its Id. Refused while it is still measuring.
arguments
    path (1,1) string
end
src = lbd_writing_path(path);
if lbd.writingStatus(src) == "measuring"
    error('lbd:held', '%s is still being written (its writer holds it); recover it only after the measurement stopped', src);
end
state = warning('off', 'lbd:writing');
restore = onCleanup(@() warning(state));
d = lbd.load(src);
clear restore
target = lbd_free_name(extractBefore(src, strlength(src) - strlength(".writing") + 1));
d.keepIdentityAt(target);
d.save(target);
check = lbd.info(target);
if check.Id ~= d.Id || ~isequal(sort(string(fieldnames(check.Values))), sort(string(fieldnames(d.Values))))
    error('lbd:invalid', 'recovering %s: the copy %s doesn''t match; %s is kept', src, target, src);
end
started = tic;
while isfile(src)
    try
        delete(src);
    catch err
        if toc(started) > 10, rethrow(err); end
    end
    if isfile(src)
        if toc(started) > 10
            who = lbd_who_has_open(src);
            if who == "", who = "another program"; end
            error('lbd:held', 'recovered %s, but can''t remove %s: %s keeps it open', target, src, who);
        end
        pause(0.1);
    end
end
path = target;
end
