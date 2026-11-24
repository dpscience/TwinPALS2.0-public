# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Names and bulk properties exported by our pinned Geant4 worker (--materials)."""
import json
import sys
from functools import lru_cache
from pathlib import Path

@lru_cache(maxsize=1)
def standard_catalogue():
    root = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]
    data = json.loads((root/'seed/geant4_materials.json').read_text(encoding='utf-8'))
    if data['format'] != 'twinpals-geant4-materials' or data['geant4_version'] != '11.4.0':
        raise ValueError('The bundled Geant4 material catalogue does not match this engine.')
    return {item['id']: item for item in data['items']}

