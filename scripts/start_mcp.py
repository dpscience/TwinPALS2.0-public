# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Run the source checkout's MCP entry point from any working directory."""
import multiprocessing
from pathlib import Path
import sys

if __name__ == '__main__':
    multiprocessing.freeze_support()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from backend.mcp_server.cli import main
    raise SystemExit(main())
