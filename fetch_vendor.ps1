<#
.SYNOPSIS
    Downloads the external executables listed in vendor.json into vendor\.

.DESCRIPTION
    For each component of vendor.json (Deno, FFmpeg):
    - if every file is already in vendor\ with the expected SHA-256, nothing is
      downloaded;
    - otherwise the archive is downloaded from its pinned URL, its SHA-256 is
      checked, the needed files are extracted and checked one by one, then
      copied to vendor\, replacing any other version.
    The license of each component is saved in vendor\licenses\<name>\.
    Any hash mismatch stops the script without changing vendor\.

.PARAMETER VendorDir
    Destination folder. Defaults to vendor\ next to this script.

.PARAMETER Force
    Download again even if the files are already up to date.

.EXAMPLE
    .\fetch_vendor.ps1
#>
[CmdletBinding()]
param(
    [string]$VendorDir,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
# $PSScriptRoot is not set yet in parameter defaults on Windows PowerShell 5.1.
if (-not $VendorDir) {
    $VendorDir = Join-Path $PSScriptRoot "vendor"
}
# Windows PowerShell 5.1: enable TLS 1.2 and avoid the very slow progress bar.
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$ProgressPreference = "SilentlyContinue"
Add-Type -AssemblyName System.IO.Compression.FileSystem

$manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot "vendor.json") -Raw | ConvertFrom-Json

function Get-Sha256([string]$Path) {
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Test-File([string]$Path, [string]$Sha256) {
    return (Test-Path -LiteralPath $Path -PathType Leaf) -and ((Get-Sha256 $Path) -eq $Sha256)
}

function Assert-Hash([string]$Path, [string]$Sha256, [string]$What) {
    $actual = Get-Sha256 $Path
    if ($actual -ne $Sha256) {
        throw "SHA-256 mismatch for $What`n  expected $Sha256`n  got      $actual"
    }
}

New-Item -ItemType Directory -Force -Path $VendorDir | Out-Null
$failed = $false

foreach ($component in $manifest.components) {
    $label = "$($component.name) $($component.version)"
    $licenseDir = Join-Path $VendorDir "licenses\$($component.name)"
    $licensePath = Join-Path $licenseDir $component.license_file.name

    $upToDate = -not $Force -and (Test-File $licensePath $component.license_file.sha256)
    foreach ($file in $component.files) {
        if (-not (Test-File (Join-Path $VendorDir $file.name) $file.sha256)) { $upToDate = $false }
    }
    if ($upToDate) {
        Write-Host "  $label is up to date."
        continue
    }

    Write-Host "  $label : downloading $($component.archive.url)"
    $staging = Join-Path ([IO.Path]::GetTempPath()) ("vendor-" + [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $staging | Out-Null
    try {
        $archive = Join-Path $staging "archive.zip"
        Invoke-WebRequest -Uri $component.archive.url -OutFile $archive -UseBasicParsing
        Assert-Hash $archive $component.archive.sha256 "the $label archive"

        # Extract and check everything in the staging folder first, so that a
        # bad download never replaces working files in vendor\.
        $zip = [IO.Compression.ZipFile]::OpenRead($archive)
        try {
            $extract = {
                param([string]$EntryPath, [string]$Destination, [string]$Sha256)
                $entry = $zip.GetEntry($EntryPath)
                if ($null -eq $entry) { throw "$EntryPath not found in the $label archive" }
                [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $Destination, $true)
                Assert-Hash $Destination $Sha256 "$EntryPath ($label)"
            }
            foreach ($file in $component.files) {
                & $extract $file.archive_path (Join-Path $staging $file.name) $file.sha256
            }
            $stagedLicense = Join-Path $staging "license"
            if ($component.license_file.archive_path) {
                & $extract $component.license_file.archive_path $stagedLicense $component.license_file.sha256
            }
        }
        finally {
            $zip.Dispose()
        }
        if ($component.license_file.url) {
            Invoke-WebRequest -Uri $component.license_file.url -OutFile $stagedLicense -UseBasicParsing
            Assert-Hash $stagedLicense $component.license_file.sha256 "the $label license"
        }

        foreach ($file in $component.files) {
            Copy-Item -LiteralPath (Join-Path $staging $file.name) -Destination (Join-Path $VendorDir $file.name) -Force
        }
        New-Item -ItemType Directory -Force -Path $licenseDir | Out-Null
        Copy-Item -LiteralPath $stagedLicense -Destination $licensePath -Force
        Write-Host "  $label installed and verified." -ForegroundColor Green
    }
    catch {
        Write-Host "ERROR: $label : $($_.Exception.Message)" -ForegroundColor Red
        $failed = $true
    }
    finally {
        Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
    }
}

if ($failed) {
    exit 1
}
