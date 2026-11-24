# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

param(
    [string]$OutputDirectory = 'release',
    [string]$ZipPath = '',
    [switch]$NoZip,
    [switch]$SkipTests,
    [switch]$PublicRelease,
    [switch]$ReplaceOwned
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$buildPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$packager = Join-Path $PSScriptRoot 'package_release.py'
if (-not (Test-Path -LiteralPath $buildPython -PathType Leaf)) {
    throw 'Build interpreter missing: install requirements-dev.txt into the project .venv first. The resulting portable application does not require an external Python installation.'
}
$packageArguments = @($packager, '--output', $OutputDirectory)
if ($ZipPath) { $packageArguments += @('--zip-path', $ZipPath) }
if ($NoZip) { $packageArguments += '--no-zip' }
if ($SkipTests) { $packageArguments += '--skip-tests' }
if ($PublicRelease) { $packageArguments += '--public-release' }
if ($ReplaceOwned) { $packageArguments += '--replace-owned' }
Push-Location -LiteralPath $projectRoot
try {
    & $buildPython @packageArguments
    if ($LASTEXITCODE -ne 0) { throw "Portable release build failed with exit code $LASTEXITCODE." }
} finally {
    Pop-Location
}
