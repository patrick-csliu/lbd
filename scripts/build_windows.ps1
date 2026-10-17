<#
Build the Windows installer of LBD Viewer.

    powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1

Needs: uv, Node.js (npm) and Inno Setup 6 (ISCC.exe). The documentation site (mkdocs) is built
into <app>\docs, which the viewer serves as its Help. Each language in languages/ builds its SDK
files with the tools its language.toml names (e.g. MATLAB for LBD.mltbx); without them, or with
-Skip <id>, its fallback files are shipped instead. -Prebuilt matlab=<dir> uses files built
elsewhere (GitHub's release workflow builds LBD.mltbx in a MATLAB job).
Everything is built outside the repository (default %LOCALAPPDATA%\lbd-build), so nothing
large lands in a synced folder. Result: <OutDir>\LBD-Viewer-<version>-windows-x64-setup.exe
#>
param(
    [string]$OutDir = (Join-Path $env:LOCALAPPDATA "lbd-build"),
    [string[]]$Skip = @(),
    [string[]]$Prebuilt = @(),   # ID=DIR: use DIR's files instead of building that language
    [switch]$SkipInstaller
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo
$env:UV_PROJECT_ENVIRONMENT = Join-Path $OutDir "venv"

function Step([string]$Name) { Write-Host "==> $Name" -ForegroundColor Cyan }
function Check([string]$What) { if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE)" } }

Step "Checking versions"
$Version = (& uv run python scripts/check_versions.py).Trim()
Check "version check"
Write-Host "    version $Version"

Step "Python build environment ($env:UV_PROJECT_ENVIRONMENT)"
& uv sync --all-packages --group docs
Check "uv sync"

Step "Web UI"
Push-Location (Join-Path "viewer" "web")
try {
    & npm ci
    Check "npm ci"
    & npm run build
    Check "npm run build"
} finally { Pop-Location }

Step "Icons"
& uv run python packaging/make_icons.py
Check "icons"

Step "PyInstaller"
$Dist = Join-Path $OutDir "dist"
& uv run pyinstaller packaging/lbd-view.spec --noconfirm --log-level WARN `
    --distpath $Dist --workpath (Join-Path $OutDir "work")
Check "pyinstaller"
$App = Join-Path $Dist "LBDViewer"

Step "Language modules (sdk)"
$StageArgs = @("run", "python", "packaging/stage_sdk.py", "--dest", (Join-Path $App "sdk"))
if ($Skip.Count -gt 0) { $StageArgs += "--skip"; $StageArgs += $Skip }
if ($Prebuilt.Count -gt 0) { $StageArgs += "--prebuilt"; $StageArgs += $Prebuilt }
& uv @StageArgs
Check "stage_sdk"

Step "Documentation (Help)"
$Site = Join-Path $OutDir "site"
& uv run mkdocs build --strict --quiet --site-dir $Site
Check "mkdocs build"
$Docs = Join-Path $App "docs"
if (Test-Path $Docs) { Remove-Item -Recurse -Force $Docs }
Copy-Item -Recurse $Site $Docs
Copy-Item (Join-Path $Repo "LICENSE") $App   # MIT: the notice ships with every copy

if ($SkipInstaller) {
    Write-Host "Skipped the installer. App folder: $App" -ForegroundColor Yellow
    exit 0
}

Step "Inno Setup"
$Iscc = @(
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) {
    $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($cmd) { $Iscc = $cmd.Source }
}
if (-not $Iscc) {
    throw "Inno Setup 6 (ISCC.exe) not found. Install it from https://jrsoftware.org/isdl.php, or rerun with -SkipInstaller."
}
& $Iscc "/DAppVersion=$Version" "/DDistDir=$App" "/O$OutDir" "/Q" "packaging\windows\LBDViewer.iss"
Check "ISCC"

$Setup = Join-Path $OutDir "LBD-Viewer-$Version-windows-x64-setup.exe"
Write-Host "Done: $Setup" -ForegroundColor Green
