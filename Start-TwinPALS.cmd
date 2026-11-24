@echo off
REM SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
REM SPDX-License-Identifier: MIT
REM Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo TwinPALS development runtime not found. See README.md or use the portable release folder.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -X utf8 -m backend %*
set "TwinPALSExitCode=%ERRORLEVEL%"
if not "%TwinPALSExitCode%"=="0" (
  echo TwinPALS stopped with error %TwinPALSExitCode%.
  pause
)
exit /b %TwinPALSExitCode%
