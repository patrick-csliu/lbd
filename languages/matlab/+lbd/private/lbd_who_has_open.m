function who = lbd_who_has_open(path)
%LBD_WHO_HAS_OPEN The programs that have PATH open, as text ("" if unknown).
%   On Windows from the Restart Manager (what Explorer uses for "the file is open in ..."),
%   called through PowerShell; elsewhere from lsof. Only for a better message: never fails.
who = "";
try
    path = char(path);
    if ispc && ~(startsWith(path, '\') || (numel(path) > 1 && path(2) == ':'))
        path = fullfile(pwd, path);                     % relative: from the current folder
    end
    if ispc
        cmd = strrep(restartManagerScript(), "%PATH%", strrep(path, "'", "''"));
        cmd = strrep(cmd, "%ME%", string(feature('getpid')));
        encoded = matlab.net.base64encode(unicode2native(char(cmd), 'UTF-16LE'));
        [status, out] = system(['powershell -NoProfile -NonInteractive -EncodedCommand ' encoded ' 2>NUL']);
        if status == 0
            who = strtrim(string(out));
        end
    else
        [~, out] = system(sprintf('lsof -Fc "%s" 2>/dev/null', path));
        lines = splitlines(string(out));
        names = unique(extractAfter(lines(startsWith(lines, "c")), 1));
        who = strjoin(names, ", ");
    end
catch
    who = "";
end
end

function s = restartManagerScript()
s = join([
    "$ProgressPreference = 'SilentlyContinue'"
    "$t = @'"
    "using System; using System.Collections.Generic; using System.Runtime.InteropServices;"
    "public static class LbdRm {"
    "  [StructLayout(LayoutKind.Sequential)] public struct UP { public int pid; public System.Runtime.InteropServices.ComTypes.FILETIME t; }"
    "  [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] public struct PI { public UP p;"
    "    [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 256)] public string app;"
    "    [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 64)] public string svc;"
    "    public int type; public uint status; public uint ts; [MarshalAs(UnmanagedType.Bool)] public bool restartable; }"
    "  [DllImport(""rstrtmgr.dll"", CharSet = CharSet.Unicode)] static extern int RmStartSession(out uint h, int f, string key);"
    "  [DllImport(""rstrtmgr.dll"")] static extern int RmEndSession(uint h);"
    "  [DllImport(""rstrtmgr.dll"", CharSet = CharSet.Unicode)] static extern int RmRegisterResources(uint h, uint n, string[] f, uint na, IntPtr a, uint ns, IntPtr s);"
    "  [DllImport(""rstrtmgr.dll"")] static extern int RmGetList(uint h, out uint needed, ref uint n, [In, Out] PI[] info, ref uint reasons);"
    "  public static string Who(string path, int me) {"
    "    uint h; if (RmStartSession(out h, 0, new string('\0', 64)) != 0) return """";"
    "    try {"
    "      RmRegisterResources(h, 1, new string[] { path }, 0, IntPtr.Zero, 0, IntPtr.Zero);"
    "      uint needed, n = 0, r = 0; RmGetList(h, out needed, ref n, null, ref r);"
    "      if (needed == 0) return """";"
    "      var info = new PI[needed]; n = needed;"
    "      if (RmGetList(h, out needed, ref n, info, ref r) != 0) return """";"
    "      var names = new List<string>();"
    "      for (int i = 0; i < n; i++) if (info[i].p.pid != me) names.Add(info[i].app + "" (process "" + info[i].p.pid + "")"");"
    "      return string.Join("", "", names);"
    "    } finally { RmEndSession(h); }"
    "  }"
    "}"
    "'@"
    "Add-Type -TypeDefinition $t"
    "[LbdRm]::Who('%PATH%', %ME%)"
    ], newline);
end
