# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

param([int]$Parallel = 4)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$nativeRoot = Join-Path $projectRoot 'native'
$geantRoot = Join-Path $projectRoot '.runtime\geant4-11.4.0-win64'
$binaryRoot = Join-Path $projectRoot '.runtime\bin'
$geantConfig = Join-Path $geantRoot 'lib\cmake\Geant4'
if (-not (Test-Path -LiteralPath (Join-Path $geantConfig 'Geant4Config.cmake'))) {
    throw 'Pinned local Geant4 11.4.0 is missing. Provision the official Windows archive in .runtime first.'
}
New-Item -ItemType Directory -Path $binaryRoot -Force | Out-Null
& cmake -S $nativeRoot -B (Join-Path $nativeRoot 'build') -G 'Visual Studio 17 2022' -A x64 "-DGeant4_DIR=$geantConfig"
if ($LASTEXITCODE -ne 0) { throw 'Native CMake configuration failed.' }
& cmake --build (Join-Path $nativeRoot 'build') --config Release --parallel $Parallel
if ($LASTEXITCODE -ne 0) { throw 'Native build failed.' }
Get-ChildItem -LiteralPath (Join-Path $geantRoot 'bin') -Filter '*.dll' | ForEach-Object {
    $runtimeTarget = Join-Path $binaryRoot $_.Name
    # An unchanged runtime may be loaded by the user's open application.
    if (-not (Test-Path -LiteralPath $runtimeTarget) -or
        (Get-FileHash -LiteralPath $_.FullName).Hash -ne (Get-FileHash -LiteralPath $runtimeTarget).Hash) {
        Copy-Item -LiteralPath $_.FullName -Destination $runtimeTarget -Force
    }
}
& (Join-Path $binaryRoot 'twinpals-worker.exe') --version
if ($LASTEXITCODE -ne 0) { throw 'Native version smoke check failed.' }
