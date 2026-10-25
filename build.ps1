<#
.SYNOPSIS
    Builds dist\SpotifyDownloader\SpotifyDownloader.exe with PyInstaller.

.DESCRIPTION
    1. Reads the version from version.py and checks that CHANGELOG.md has a
       section for it.
    2. Downloads or checks the vendor executables with fetch_vendor.ps1.
    3. Checks that the installed Python packages match requirements.txt, then
       runs the tests in tests\ (skip them with -SkipTests).
    4. Sets aside the user files of the previous build (data\config.json,
       data\spotify_cache.json), which PyInstaller deletes with the output
       folder.
    5. Runs PyInstaller, with the version in the executable's file properties,
       then puts the user files back, even if the build fails.
    6. Adds LICENSE, CHANGELOG.md, THIRD_PARTY_NOTICES.md and the third-party
       license texts in docs\ next to the executable.
    7. Checks the output and runs the packaged worker's self-check.
    8. With -Package, writes dist\SpotifyDownloader-<version>-win64.zip
       (without the user files) and its SHA-256.

.PARAMETER Python
    Python interpreter to build with. Defaults to venv\Scripts\python.exe,
    then .venv\Scripts\python.exe.

.PARAMETER SkipTests
    Build without running the tests.

.PARAMETER Package
    Also create the release archive.

.EXAMPLE
    .\build.ps1 -Package
#>
[CmdletBinding()]
param(
    [string]$Python,
    [switch]$SkipTests,
    [switch]$Package
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$AppName = "SpotifyDownloader"
$ProductName = "Spotify Playlist Downloader"
$OutputDir = Join-Path $PSScriptRoot "dist\$AppName"
$VendorFiles = @("deno.exe", "ffmpeg.exe", "ffprobe.exe")
# Files written at run time in data\ (see config_manager.py), relative to the
# output folder. Versions before data\ wrote them next to the executable; they
# are kept too, and the application moves them on its next start.
$UserFileNames = @("config.json", "config.json.broken", "spotify_cache.json")
$UserFiles = @($UserFileNames | ForEach-Object { "data\$_" }) + $UserFileNames
$Documents = @("LICENSE", "CHANGELOG.md", "THIRD_PARTY_NOTICES.md")
$DocsDir = Join-Path $OutputDir "docs"
$CollectAll = @("spotdl", "yt_dlp", "syncedlyrics", "pykakasi", "ytmusicapi", "babel")

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "== $Message" -ForegroundColor Cyan
}

function Stop-Build([string]$Message) {
    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit 1
}

function Get-NormalizedName([string]$Name) {
    return ($Name -replace "[-_.]+", "-").ToLowerInvariant()
}

# --- Python ------------------------------------------------------------------
if (-not $Python) {
    $Python = @("venv\Scripts\python.exe", ".venv\Scripts\python.exe") |
        Where-Object { Test-Path -LiteralPath $_ } |
        Select-Object -First 1
}
if (-not $Python -or -not (Test-Path -LiteralPath $Python)) {
    Stop-Build "No virtual environment found (venv or .venv). Create one as described in README.md, or pass -Python."
}
Write-Host "Python: $Python"

# --- 1. Version -----------------------------------------------------------------
Write-Step "Checking the version"
$version = "$(& $Python -c 'from version import __version__; print(__version__)')".Trim()
if ($version -notmatch "^(\d+)\.(\d+)\.(\d+)([-+][0-9A-Za-z.-]+)?$") {
    Stop-Build "version.py: '$version' is not a MAJOR.MINOR.PATCH version."
}
$fileVersion = @([int]$Matches[1], [int]$Matches[2], [int]$Matches[3], 0)
$changelogHeading = "## [$version]"
if (-not (Select-String -LiteralPath "CHANGELOG.md" -SimpleMatch -Pattern $changelogHeading -Quiet)) {
    Stop-Build "CHANGELOG.md has no '$changelogHeading' section. Describe the changes of this version first."
}
Write-Host "  Version $version, described in CHANGELOG.md."

# --- 2. Vendor executables ------------------------------------------------------
Write-Step "Fetching and checking vendor executables (vendor.json)"
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "fetch_vendor.ps1")
if ($LASTEXITCODE -ne 0) {
    Stop-Build "Could not get the vendor executables listed in vendor.json."
}

# --- 3. Python packages and tests ------------------------------------------------
Write-Step "Checking Python packages against requirements.txt"
$installed = @{}
foreach ($line in (& $Python -m pip freeze --all)) {
    if ($line -match "^([^=\s]+)==(\S+)$") {
        $installed[(Get-NormalizedName $Matches[1])] = $Matches[2]
    }
}
if ($LASTEXITCODE -ne 0 -or $installed.Count -eq 0) {
    Stop-Build "Could not list the installed packages with pip."
}
$problems = @()
foreach ($line in (Get-Content -LiteralPath "requirements.txt")) {
    $requirement = ($line -split "#")[0].Trim()
    if (-not $requirement) { continue }
    if ($requirement -notmatch "^([^=\s]+)==(\S+)$") {
        $problems += "  not pinned with ==: $requirement"
        continue
    }
    $name = $Matches[1]
    $expected = $Matches[2]
    $actual = $installed[(Get-NormalizedName $name)]
    if ($actual -ne $expected) {
        $found = if ($actual) { $actual } else { "not installed" }
        $problems += "  $name expected $expected, found $found"
    }
}
if ($problems.Count -gt 0) {
    $problems | ForEach-Object { Write-Host $_ -ForegroundColor Yellow }
    Stop-Build "Installed packages do not match requirements.txt. Run: $Python -m pip install -r requirements.txt"
}
Write-Host "  All pinned packages are installed with the expected versions."

Write-Step "Running the tests"
if ($SkipTests) {
    Write-Host "  Skipped (-SkipTests)." -ForegroundColor Yellow
}
else {
    # unittest reports on stderr; that is not an error by itself.
    $ErrorActionPreference = "Continue"
    & $Python -m unittest discover -s tests
    $testExitCode = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    if ($testExitCode -ne 0) {
        Stop-Build "Tests failed. Fix them, or build anyway with -SkipTests."
    }
}

# --- 4. Set aside the user files -------------------------------------------------
Write-Step "Keeping user files from the previous build"
$backupDir = Join-Path ([IO.Path]::GetTempPath()) ("$AppName-build-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
$kept = @()
foreach ($name in $UserFiles) {
    $source = Join-Path $OutputDir $name
    if (Test-Path -LiteralPath $source -PathType Leaf) {
        $backup = Join-Path $backupDir $name
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $backup) | Out-Null
        Copy-Item -LiteralPath $source -Destination $backup
        $kept += $name
        Write-Host "  kept $name"
    }
}
if ($kept.Count -eq 0) {
    Write-Host "  No previous user files."
}

# --- 5. Build, then put the user files back ----------------------------------------
Write-Step "Running PyInstaller"
# Windows file properties (Details tab) of the executable.
$versionTuple = $fileVersion -join ", "
$versionInfo = @"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($versionTuple), prodvers=($versionTuple), mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('FileDescription', '$ProductName'),
      StringStruct('FileVersion', '$version'),
      StringStruct('InternalName', '$AppName'),
      StringStruct('LegalCopyright', 'Copyright (c) $((Get-Date).Year). MIT License.'),
      StringStruct('OriginalFilename', '$AppName.exe'),
      StringStruct('ProductName', '$ProductName'),
      StringStruct('ProductVersion', '$version')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"@
New-Item -ItemType Directory -Force -Path "build" | Out-Null
$versionFile = Join-Path $PSScriptRoot "build\version_info.txt"
# No byte order mark: PyInstaller evaluates this file as Python.
[IO.File]::WriteAllText($versionFile, $versionInfo)

$arguments = @(
    "-m", "PyInstaller", "--clean", "--noconfirm", "--windowed",
    "--icon", "assets\spotifydownloader.ico",
    "--version-file", $versionFile,
    "--name", $AppName
)
# Not $package: PowerShell names are case-insensitive and -Package is a switch.
foreach ($collected in $CollectAll) {
    $arguments += @("--collect-all", $collected)
}
foreach ($name in $VendorFiles) {
    $arguments += @("--add-binary", "vendor\$name;vendor")
}
$arguments += @("--add-data", "assets\spotifydownloader.ico;assets", "app.py")

$buildExitCode = 1
try {
    # PyInstaller logs to stderr; that is not an error by itself.
    $ErrorActionPreference = "Continue"
    & $Python @arguments
    $buildExitCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = "Stop"
    if ($kept.Count -gt 0) {
        foreach ($name in $kept) {
            $destination = Join-Path $OutputDir $name
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
            Copy-Item -LiteralPath (Join-Path $backupDir $name) -Destination $destination -Force
        }
        Write-Host ""
        Write-Host "Restored $($kept -join ', ') to $OutputDir"
        if ($buildExitCode -eq 0) {
            Remove-Item -LiteralPath $backupDir -Recurse -Force
        }
        else {
            Write-Host "A copy is also kept in $backupDir"
        }
    }
}
if ($buildExitCode -ne 0) {
    Stop-Build "PyInstaller failed with exit code $buildExitCode."
}

# --- 6. License files and documents ------------------------------------------------
Write-Step "Adding licenses and documents"
# In docs\, so that the folder of the executable stays uncluttered.
New-Item -ItemType Directory -Force -Path $DocsDir | Out-Null
foreach ($name in $Documents) {
    Copy-Item -LiteralPath $name -Destination $DocsDir -Force
}
$licensesDir = Join-Path $DocsDir "licenses"
Copy-Item -LiteralPath "vendor\licenses" -Destination $DocsDir -Recurse -Force
& $Python tools\collect_licenses.py requirements.txt (Join-Path $licensesDir "python")
if ($LASTEXITCODE -ne 0) {
    Stop-Build "Could not collect the Python package licenses."
}
Write-Host "  $($Documents -join ', ') and licenses\ added to docs\."

# --- 7. Check the result -----------------------------------------------------------
Write-Step "Checking the build"
$exe = Join-Path $OutputDir "$AppName.exe"
$expectedFiles = @($exe, (Join-Path $OutputDir "_internal\assets\spotifydownloader.ico"))
foreach ($name in $VendorFiles) {
    $expectedFiles += Join-Path $OutputDir "_internal\vendor\$name"
}
foreach ($name in $Documents) {
    $expectedFiles += Join-Path $DocsDir $name
}
$expectedFiles += @(
    (Join-Path $licensesDir "ffmpeg\LICENSE.txt"),
    (Join-Path $licensesDir "deno\LICENSE.md"),
    (Join-Path $licensesDir "python\SUMMARY.txt")
)
foreach ($path in $expectedFiles) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        Stop-Build "Missing from the build: $path"
    }
}
$exeVersion = (Get-Item -LiteralPath $exe).VersionInfo.ProductVersion
if ($exeVersion -ne $version) {
    Stop-Build "The executable reports version '$exeVersion' instead of '$version'."
}
Write-Host "  Executable (version $exeVersion), icon, vendor binaries, documents and licenses are present."

# The executable is windowed: start it with redirected output to read the result.
$selfCheckLog = Join-Path ([IO.Path]::GetTempPath()) "$AppName-self-check.txt"
$process = Start-Process -FilePath $exe -ArgumentList "--self-check" -Wait -PassThru `
    -NoNewWindow -RedirectStandardOutput $selfCheckLog
$selfCheckOutput = (Get-Content -LiteralPath $selfCheckLog -ErrorAction SilentlyContinue) -join " "
Remove-Item -LiteralPath $selfCheckLog -Force -ErrorAction SilentlyContinue
if ($process.ExitCode -ne 0) {
    Stop-Build "The packaged worker self-check failed (exit code $($process.ExitCode)): $selfCheckOutput"
}
Write-Host "  $selfCheckOutput"

# --- 8. Release archive ------------------------------------------------------------
if ($Package) {
    Write-Step "Creating the release archive"
    Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
    $archiveName = "$AppName-$version-win64"
    $archive = Join-Path $PSScriptRoot "dist\$archiveName.zip"
    Remove-Item -LiteralPath $archive, "$archive.sha256" -Force -ErrorAction SilentlyContinue
    $zip = [IO.Compression.ZipFile]::Open($archive, [IO.Compression.ZipArchiveMode]::Create)
    try {
        foreach ($file in (Get-ChildItem -LiteralPath $OutputDir -Recurse -File)) {
            $relative = $file.FullName.Substring($OutputDir.Length + 1)
            # Never ship the profiles or cache of the machine that built it.
            if ($UserFiles -contains $relative -or $relative -like "data\*") { continue }
            $entry = "$archiveName/" + ($relative -replace "\\", "/")
            [IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                $zip, $file.FullName, $entry, [IO.Compression.CompressionLevel]::Optimal) | Out-Null
        }
    }
    finally {
        $zip.Dispose()
    }
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToLowerInvariant()
    [IO.File]::WriteAllText("$archive.sha256", "$hash  $archiveName.zip`n")
    $sizeMb = [math]::Round((Get-Item -LiteralPath $archive).Length / 1MB)
    Write-Host "  $archive ($sizeMb MB)"
    Write-Host "  SHA-256 $hash"
}

Write-Host ""
Write-Host "Build complete: $exe (version $version)" -ForegroundColor Green
