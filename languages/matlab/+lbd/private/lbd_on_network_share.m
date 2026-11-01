function tf = lbd_on_network_share(path)
%LBD_ON_NETWORK_SHARE Whether PATH (a file or folder) is on a network share (Windows: a UNC
%   path or a network drive; elsewhere false). Only for a warning: never fails.
tf = false;
if ~ispc
    return
end
try
    p = char(path);
    if startsWith(p, '\\') || startsWith(p, '//')        % \\server\share\...
        tf = true;
        return
    end
    if numel(p) < 2 || p(2) ~= ':'                       % relative: from the current folder
        p = fullfile(pwd, p);
        if startsWith(p, '\\')
            tf = true;
            return
        end
    end
    drive = System.IO.DriveInfo(p(1:2));
    tf = string(drive.DriveType) == "Network";
catch
    tf = false;
end
end
