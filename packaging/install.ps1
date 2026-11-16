# Install (or upgrade) LBD Viewer on Windows from the latest release on GitHub.
#
#   irm https://github.com/patrick-csliu/lbd/releases/latest/download/install.ps1 | iex
#
# With options (the installer's shortcut choices; without them it keeps the earlier choices, or
# the defaults: Start menu yes, desktop no):
#
#   & ([scriptblock]::Create((irm https://github.com/patrick-csliu/lbd/releases/latest/download/install.ps1))) -DesktopShortcut
#
#   -DesktopShortcut   also make a desktop shortcut
#   -NoStartMenu       no Start menu shortcut
#
# What it does: downloads SHA256SUMS and the setup program of the latest release, checks the
# setup program's SHA-256 against SHA256SUMS, and runs it silently. Everything else (shortcuts,
# the .lbd file type, the entry in Settings > Apps, the uninstaller, upgrading, refusing an older
# version) is the installer's own work, as when you double-click it. Nothing is left behind: the
# download is deleted afterwards, also when something fails.
#
# For tests: LBD_RELEASE_BASE replaces the release's address (a URL, or a local folder holding
# SHA256SUMS and the setup program), and LBD_INSTALL_CHECK_ONLY=1 stops after the checksum check.

param(
    [switch]$DesktopShortcut,
    [switch]$NoStartMenu
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"     # Windows PowerShell 5.1 downloads slowly with a progress bar

function Say([string]$Text) { Write-Host "==> $Text" -ForegroundColor Cyan }
# A failure stops everything (a throw, not exit: with "| iex", exit would close the window).
function Fail([string]$Text) { throw [System.OperationCanceledException]::new($Text) }

$base = $env:LBD_RELEASE_BASE
if (-not $base) { $base = "https://github.com/patrick-csliu/lbd/releases/latest/download" }
$base = $base.TrimEnd("/", "\")

# Get one file of the release into $Dest (from the web, or a local folder for tests).
function Fetch([string]$Name, [string]$Dest) {
    if (Test-Path -LiteralPath $base -PathType Container) {
        $src = Join-Path $base $Name
        if (-not (Test-Path -LiteralPath $src)) { throw "$src doesn't exist" }
        Copy-Item -LiteralPath $src -Destination $Dest
        return
    }
    # Windows PowerShell 5.1 may not offer TLS 1.2 by itself; GitHub needs it.
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri "$base/$Name" -OutFile $Dest -UseBasicParsing
}

function Install-LBDViewer {
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ("lbd-install-" + [Guid]::NewGuid().ToString("N").Substring(0, 8))
    New-Item -ItemType Directory -Path $tmp | Out-Null
    try {
        Say "Fetching the list of files and checksums (SHA256SUMS) from $base"
        $sums = Join-Path $tmp "SHA256SUMS"
        try { Fetch "SHA256SUMS" $sums }
        catch { Fail "couldn't download SHA256SUMS ($($_.Exception.Message)). Check the internet connection (or proxy), then try again." }

        # Lines are "<sha256>  <file name>", as sha256sum writes them.
        $entry = Get-Content -LiteralPath $sums | ForEach-Object {
            if ($_ -match '^([0-9a-fA-F]{64})\s+\*?(LBD-Viewer-[^\s]+-windows-x64-setup\.exe)\s*$') {
                [pscustomobject]@{ Hash = $Matches[1].ToLower(); Name = $Matches[2] }
            }
        } | Select-Object -First 1
        if (-not $entry) { Fail "SHA256SUMS names no Windows setup program; this release has none for Windows." }

        Say "Downloading $($entry.Name)"
        $setup = Join-Path $tmp $entry.Name
        try { Fetch $entry.Name $setup }
        catch { Fail "couldn't download $($entry.Name) ($($_.Exception.Message)). Check the internet connection (or proxy), then try again." }

        Say "Checking its SHA-256 checksum"
        # .NET directly, not Get-FileHash: that cmdlet can be missing (e.g. Windows PowerShell started
        # from PowerShell 7, whose module path hides it)
        $sha = [System.Security.Cryptography.SHA256]::Create()
        $stream = [System.IO.File]::OpenRead($setup)
        try { $hash = ([System.BitConverter]::ToString($sha.ComputeHash($stream)) -replace '-', '').ToLower() }
        finally { $stream.Dispose(); $sha.Dispose() }
        if ($hash -ne $entry.Hash) {
            Fail "the checksum of $($entry.Name) doesn't match SHA256SUMS (expected $($entry.Hash), got $hash). The download is damaged or not the published file; it was deleted. Try again later."
        }
        Write-Host "    ok: $hash"
        if ($env:LBD_INSTALL_CHECK_ONLY -eq "1") { Say "Checked (LBD_INSTALL_CHECK_ONLY): not installing"; return }

        $arguments = @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/LOG=`"$tmp\setup.log`"")
        if ($DesktopShortcut -or $NoStartMenu) {
            $tasks = @($(if ($NoStartMenu) { "!startmenu" } else { "startmenu" }), $(if ($DesktopShortcut) { "desktopicon" } else { "!desktopicon" }))
            $arguments += "/TASKS=`"$($tasks -join ',')`""
        }
        Say "Installing (a running LBD Viewer is stopped first)"
        $p = Start-Process -FilePath $setup -ArgumentList $arguments -Wait -PassThru
        if ($p.ExitCode -ne 0) {
            $why = Get-Content -LiteralPath "$tmp\setup.log" -ErrorAction SilentlyContinue | Where-Object { $_ -match "Refused:|error" } | Select-Object -Last 3
            Fail "the installer ended with code $($p.ExitCode). $($why -join ' ')"
        }
        Say "Done. Start LBD Viewer from the Start menu, or double-click an .lbd file."
    }
    finally {
        Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }
}

$asFile = [bool]$MyInvocation.MyCommand.Path     # run as a file (powershell -File), not through iex
try {
    Install-LBDViewer
}
catch {
    $why = if ($_.Exception -is [System.OperationCanceledException]) { $_.Exception.Message } else { "$_" }
    Write-Host "LBD Viewer was not installed: $why" -ForegroundColor Red
    $global:LASTEXITCODE = 1
    if ($asFile) { exit 1 }
}
