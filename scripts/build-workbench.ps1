# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663
param([int]$Parallel = 4, [string]$Python, [string]$Geant4Cache, [switch]$OfflineGeant4)
$ErrorActionPreference = 'Stop'
Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    if (-not (Test-Path .venv/Scripts/python.exe)) {
        if ($Python) { & $Python -m venv .venv }
        elseif (Get-Command py -ErrorAction SilentlyContinue) { & py -3.12 -m venv .venv }
        else { & python -m venv .venv }
        if ($LASTEXITCODE) { throw 'Python 3.12 environment creation failed.' }
    }
    & .venv/Scripts/python.exe -c "import struct,sys; sys.exit(0 if sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8 else 1)"
    if ($LASTEXITCODE) { throw 'TwinPALS requires x64 CPython 3.12 in .venv.' }
    & .venv/Scripts/python.exe -m pip install -r requirements-dev.txt
    if ($LASTEXITCODE) { throw 'Python dependency installation failed.' }
    & npm.cmd --prefix frontend ci
    if ($LASTEXITCODE) { throw 'Frontend dependency installation failed.' }
    & npm.cmd --prefix frontend run build
    if ($LASTEXITCODE) { throw 'Frontend build failed.' }
    $restoreArgs = @()
    if ($Geant4Cache) { $restoreArgs += @('--cache', $Geant4Cache) }
    if ($OfflineGeant4) { $restoreArgs += '--offline' }
    & .venv/Scripts/python.exe scripts/restore_geant4.py @restoreArgs
    if ($LASTEXITCODE) { throw 'Geant4 restoration failed.' }
    & ./scripts/build-native.ps1 -Parallel $Parallel
    & .venv/Scripts/python.exe native/inspect_runtime.py --refresh-existing
    if ($LASTEXITCODE) { throw 'Native dependency verification failed.' }
} finally {
    Pop-Location
}
