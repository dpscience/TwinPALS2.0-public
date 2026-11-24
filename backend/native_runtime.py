# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Discover the pinned, portable native Geant4 runtime."""
import json
import os
from pathlib import Path
import subprocess
from .execution import cpu_settings


def engine_path(root):
    override=os.environ.get("TWINPALS_ENGINE")
    if override:
        return Path(override).resolve()
    for candidate in [root/".runtime/bin/twinpals-worker.exe",root/"native/build/Release/twinpals-worker.exe",root/"native/build/twinpals-worker"]:
        if candidate.is_file():
            return candidate
    return root/".runtime/bin/twinpals-worker.exe"


def engine_environment(root):
    env=os.environ.copy()
    # Geant4 would otherwise silently override the recorded UI selection.
    env.pop("G4FORCENUMBEROFTHREADS",None)
    # Explicit, project-local configuration written by the native build process.
    for name in [".runtime/geant4-env.json", ".runtime/bin/environment.json"]:
        path=root/name
        if path.is_file():
            settings=json.loads(path.read_text(encoding="utf-8-sig"))
            for key, value in settings.items():
                if key.startswith("G4") or key in ("PATH", "GEANT4_DATA_DIR"):
                    path_value=str((root/value).resolve()) if not Path(value).is_absolute() else value
                    env[key]=path_value+os.pathsep+env.get("PATH","") if key=="PATH" else path_value
    bins=[root/".runtime/bin"]
    bins.extend((root/".runtime").glob("geant4*/bin"))
    env["PATH"]=os.pathsep.join(str(p) for p in bins if p.is_dir())+os.pathsep+env.get("PATH","")
    return env


def engine_status(root):
    path=engine_path(root)
    if not path.is_file():
        return {"available":False,"path":str(path),"version":None,"message":"Geant4 worker is not built. See scripts/build-native.ps1. No synthetic fallback is used."}
    try:
        result=subprocess.run([str(path),"--version"],capture_output=True,text=True,timeout=15,env=engine_environment(root),creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        if result.returncode:
            return {"available":False,"path":str(path),"version":None,"message":f"Worker dependency check failed ({result.returncode}): {result.stderr[-600:]}"}
        try:
            details=json.loads(result.stdout)
        except json.JSONDecodeError:
            details={"version":result.stdout.strip()[-300:]}
        return {"available":True,"path":str(path),"version":details.get("version"),"worker_version":details.get("worker_version"),"multithreaded":details.get("multithreaded",False),**cpu_settings(),"message":"Native Geant4 worker available; run preflight verifies geometry and data."}
    except (OSError,subprocess.TimeoutExpired) as exc:
        return {"available":False,"path":str(path),"version":None,"message":str(exc)}

