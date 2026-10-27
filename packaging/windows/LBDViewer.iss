; Inno Setup script for LBD Viewer (per-user install, no admin rights needed).
; Built by scripts/build_windows.ps1:
;   ISCC /DAppVersion=0.1.0 /DDistDir=<out>\dist\LBDViewer /O<out> packaging\windows\LBDViewer.iss

#ifndef AppVersion
  #error Pass /DAppVersion=x.y.z (or x.y.z-dev)
#endif
; The Windows file version takes numbers only: 1.2.0-dev -> 1.2.0.
#define AppNumber Copy(AppVersion, 1, Pos("-", AppVersion + "-") - 1)
#ifndef DistDir
  #error Pass /DDistDir=<folder containing lbd-view.exe>
#endif

[Setup]
; Fixed AppId: Windows uses it to recognise upgrades. Never change it.
AppId={{99E94BF7-613F-40EE-9E44-A0E148634E8E}
AppName=LBD Viewer
AppVersion={#AppVersion}
VersionInfoVersion={#AppNumber}
AppPublisher=Patrick Liu
DefaultDirName={localappdata}\Programs\LBDViewer
DisableDirPage=auto
; The default folder is ours: don't ask "folder exists, install anyway?" when it is left over
; (e.g. an empty folder after an uninstall while the viewer was running).
DirExistsWarning=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputBaseFilename=LBD-Viewer-{#AppVersion}-windows-x64-setup
SetupIconFile=..\icons\lbd.ico
UninstallDisplayIcon={app}\lbd-view.exe
UninstallDisplayName=LBD Viewer
ChangesAssociations=yes
; The viewer has no window, so Windows' Restart Manager can't close it. Setup and the
; uninstaller stop it themselves (StopViewer below), and never restart it.
CloseApplications=no
RestartApplications=no
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Files]
; Replace the whole app folder on upgrade so no stale files remain.
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\sdk"
Type: filesandordirs; Name: "{app}\docs"

[UninstallDelete]
; Remove the whole folder, also files made after installing, so no empty folder is left behind.
Type: filesandordirs; Name: "{app}"
; The "running viewer" record (server.json); the viewer is stopped before uninstalling.
Type: filesandordirs; Name: "{localappdata}\Temp\lbd"

[Tasks]
; Asked on the "Additional shortcuts" page: Start menu yes, desktop no (also for a silent install).
; An upgrade remembers the earlier choices; the uninstaller removes the shortcuts made.
Name: "startmenu"; Description: "Add LBD Viewer to the &Start menu"; GroupDescription: "Shortcuts:"
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Icons]
Name: "{autoprograms}\LBD Viewer"; Filename: "{app}\lbd-view.exe"; Comment: "View LBD data files"; Tasks: startmenu
Name: "{autodesktop}\LBD Viewer"; Filename: "{app}\lbd-view.exe"; Comment: "View LBD data files"; Tasks: desktopicon

[Registry]
; .lbd -> LBDViewer.lbd (per user: HKA resolves to HKCU for a non-admin install)
; .lbd may also be registered by other programs, so remove our values and the keys only if empty.
Root: HKA; Subkey: "Software\Classes\.lbd"; ValueType: string; ValueName: ""; ValueData: "LBDViewer.lbd"; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKA; Subkey: "Software\Classes\.lbd"; ValueType: string; ValueName: "Content Type"; ValueData: "application/x-lbd"; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKA; Subkey: "Software\Classes\.lbd\OpenWithProgids"; ValueType: string; ValueName: "LBDViewer.lbd"; ValueData: ""; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKA; Subkey: "Software\Classes\LBDViewer.lbd"; ValueType: string; ValueName: ""; ValueData: "LBD data file"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\LBDViewer.lbd\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\lbd-view.exe,0"
Root: HKA; Subkey: "Software\Classes\LBDViewer.lbd\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\lbd-view.exe"" ""%1"""
; Applications\lbd-view.exe is ours alone: remove the whole key, not only SupportedTypes.
Root: HKA; Subkey: "Software\Classes\Applications\lbd-view.exe"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Applications\lbd-view.exe\SupportedTypes"; ValueType: string; ValueName: ".lbd"; ValueData: ""; Flags: uninsdeletekey

[Run]
Filename: "{app}\lbd-view.exe"; Description: "Open LBD Viewer now"; Flags: nowait postinstall skipifsilent

[Messages]
FinishedLabel=LBD Viewer is installed. Double-click any .lbd file to open it, or start LBD Viewer from its shortcut.%n%nTo write .lbd files from your own programs, open LBD Viewer and go to "Language modules".

[Code]
// Stop a running viewer from this installation (only lbd-view.exe processes whose program file
// is inside the install folder; other copies, e.g. a development one, are left alone).
procedure StopViewer(Dir: String);
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -NonInteractive -Command "Get-Process lbd-view -ErrorAction SilentlyContinue | ' +
    'Where-Object { $_.Path -like ''' + Dir + '\*'' } | Stop-Process -Force"',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(500);  // let Windows release the files
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopViewer(ExpandConstant('{app}'));
  Result := '';
end;

function InitializeUninstall(): Boolean;
begin
  StopViewer(ExpandConstant('{app}'));
  Result := True;
end;

// The default style uses Arial. Windows always has it, unless it was removed by hand.
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and not WizardSilent and not FileExists(ExpandConstant('{fonts}\arial.ttf')) then
    MsgBox('LBD''s default style uses the font Arial, which is not installed on this computer.' + #13#10#13#10 +
           'Figures in the default style need it: reinstall Arial (Windows Settings > Personalization > Fonts), ' +
           'or choose another font for the default style on LBD Viewer''s Styles page.',
           mbInformation, MB_OK);
end;

// Move a folder to the Recycle Bin (never delete it permanently), so a wrong answer can be undone.
procedure RecycleFolder(Dir: String);
var
  ResultCode: Integer;
begin
  if not DirExists(Dir) then
    exit;
  StringChangeEx(Dir, '''', '''''', True);  // quote for PowerShell
  Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -NonInteractive -Command "Add-Type -AssemblyName Microsoft.VisualBasic; ' +
    '[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory(''' + Dir + ''', ''OnlyErrorDialogs'', ''SendToRecycleBin'')"',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

// Keep the presets and settings (folder list)? Asked when the uninstall starts, before anything
// is removed, so the question is in front of the uninstall window. "Keep" is the question (users
// read "Also remove…? No" as "don't keep"), Yes = keep is the default, and a silent uninstall
// always keeps them (they are shared with the Python module lbd.plot).
var
  RemoveSettings: Boolean;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usUninstall) and not UninstallSilent then
    RemoveSettings := MsgBox('Keep your LBD presets and settings (the list of folders) for a later installation?' + #13#10 +
                             '(' + ExpandConstant('{userappdata}\lbd') + ')' + #13#10#13#10 +
                             'Yes: keep them.' + #13#10 +
                             'No: move them to the Recycle Bin.',
                             mbConfirmation, MB_YESNO or MB_DEFBUTTON1) = IDNO;
  if (CurUninstallStep = usPostUninstall) and RemoveSettings then
  begin
    RecycleFolder(ExpandConstant('{userappdata}\lbd'));    // presets, settings.json
    RecycleFolder(ExpandConstant('{localappdata}\lbd'));   // logs
  end;
end;
