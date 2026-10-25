<#
.SYNOPSIS
    Builds dist\SpotifyDownloader\SpotifyDownloader.exe with PyInstaller.

.DESCRIPTION
    1. Checks that vendor\ contains working deno.exe, ffmpeg.exe and ffprobe.exe.
    2. Checks that the installed Python packages match requirements.txt, then
       runs the tests in tests\ (skip them with -SkipTests).
    3. Sets aside the user files of the previous build (config.json,
       spotify_cache.json), which PyInstaller deletes with the output folder.
    4. Runs PyInstaller, then puts the user files back, even if the build fails.
    5. Checks the output and runs the packaged worker's self-check.

.PARAMETER Python
    Python interpreter to build with. Defaults to venv\Scripts\python.exe,
    then .venv\Scripts\python.exe.

.PARAMETER SkipTests
    Build without running the tests.

.EXAMPLE
    .\build.ps1
#>
[CmdletBinding()]
param(
    [string]$Python,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$AppName = "SpotifyDownloader"
$OutputDir = Join-Path $PSScriptRoot "dist\$AppName"
$VendorFiles = @("deno.exe", "ffmpeg.exe", "ffprobe.exe")
# Files written next to the executable at run time, see config_manager.py.
$UserFiles = @("config.json", "config.json.broken", "spotify_cache.json")
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

# --- 1. Vendor binaries ----------------------------------------------------------
Write-Step "Checking vendor binaries"
foreach ($name in $VendorFiles) {
    $path = Join-Path "vendor" $name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        Stop-Build "Missing $path. See 'Prepare the vendor directory' in README.md."
    }
    if ((Get-Item -LiteralPath $path).Length -eq 0) {
        Stop-Build "$path is empty."
    }
    # Running it proves it is a working executable for this machine.
    $versionFlag = if ($name -eq "deno.exe") { "--version" } else { "-version" }
    $output = & $path $versionFlag
    if ($LASTEXITCODE -ne 0) {
        Stop-Build "$path does not run ('$versionFlag' exited with code $LASTEXITCODE)."
    }
    Write-Host ("  {0,-11} {1}" -f $name, ($output | Select-Object -First 1))
}

# --- 2. Python packages --------------------------------------------------------
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

# --- 3. Set aside the user files -------------------------------------------------
Write-Step "Keeping user files from the previous build"
$backupDir = Join-Path ([IO.Path]::GetTempPath()) ("$AppName-build-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
$kept = @()
foreach ($name in $UserFiles) {
    $source = Join-Path $OutputDir $name
    if (Test-Path -LiteralPath $source -PathType Leaf) {
        New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
        Copy-Item -LiteralPath $source -Destination $backupDir
        $kept += $name
        Write-Host "  kept $name"
    }
}
if ($kept.Count -eq 0) {
    Write-Host "  No previous user files."
}

# --- 4. Build, then put the user files back ----------------------------------------
Write-Step "Running PyInstaller"
$arguments = @(
    "-m", "PyInstaller", "--clean", "--noconfirm", "--windowed",
    "--icon", "assets\spotifydownloader.ico",
    "--name", $AppName
)
foreach ($package in $CollectAll) {
    $arguments += @("--collect-all", $package)
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
        New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
        foreach ($name in $kept) {
            Copy-Item -LiteralPath (Join-Path $backupDir $name) -Destination $OutputDir -Force
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

# --- 5. Check the result -----------------------------------------------------------
Write-Step "Checking the build"
$exe = Join-Path $OutputDir "$AppName.exe"
$expectedFiles = @($exe, (Join-Path $OutputDir "_internal\assets\spotifydownloader.ico"))
foreach ($name in $VendorFiles) {
    $expectedFiles += Join-Path $OutputDir "_internal\vendor\$name"
}
foreach ($path in $expectedFiles) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        Stop-Build "Missing from the build: $path"
    }
}
Write-Host "  Executable, icon and vendor binaries are present."

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

Write-Host ""
Write-Host "Build complete: $exe" -ForegroundColor Green
