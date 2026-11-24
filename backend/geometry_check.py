# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Run native construction and overlap checks without transporting events."""
import json
import subprocess
import tempfile
from pathlib import Path
from .native_runtime import engine_environment, engine_path


def validate_geometry(root, resolved):
    config={**resolved,'source_role':'na22_prompt' if resolved['source']=='na22' else 'co60','threads':1}
    with tempfile.TemporaryDirectory(prefix='twinpals-geometry-') as directory:
        path=Path(directory)/'geometry.json'
        path.write_text(json.dumps(config),encoding='utf-8')
        try:
            result=subprocess.run([str(engine_path(root)),'--validate','--config',str(path),'--output',directory],
                capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30,
                env=engine_environment(root),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except subprocess.TimeoutExpired as exc:
            raise ValueError('Geometry check timed out. Check the dimensions and native runtime.') from exc
        messages=[]
        for line in result.stdout.splitlines():
            try: messages.append(json.loads(line))
            except ValueError: pass
        if result.returncode or not any(m.get('type')=='validation' and m.get('valid') is True for m in messages):
            failure=next((m['message'] for m in reversed(messages) if m.get('type')=='error'),'Native geometry check failed')
            details=[line.strip() for line in result.stderr.splitlines() if 'Overlap is detected' in line or 'overlap at local point' in line]
            if details: failure+='\n'+'\n'.join(details)+'\nAdjust detector distance, sample dimensions or shielding to remove the overlap.'
            raise ValueError(failure)
    return {'engine':'Geant4','overlap_samples':2000}
