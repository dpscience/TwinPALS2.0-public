# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Record the native runtime provenance and recursively verify PE DLL imports.

Development-only utility; requires dumpbin from the locally installed MSVC tools.
It does not modify binaries, install packages, or change the system environment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"


def digest(path, algorithm="sha256"):
    result = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024*1024), b""):
            result.update(block)
    return result.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dumpbin", type=Path)
    parser.add_argument("--refresh-existing", action="store_true",
                        help="Refresh binary provenance and imports, preserving the documented stream/physics contract")
    args = parser.parse_args()
    candidates = sorted(Path(os.environ.get("ProgramFiles", "C:/Program Files")).glob(
        "Microsoft Visual Studio/2022/*/VC/Tools/MSVC/*/bin/Hostx64/x64/dumpbin.exe"))
    dumpbin = args.dumpbin or (candidates[-1] if candidates else None)
    if not dumpbin or not dumpbin.is_file():
        raise RuntimeError("MSVC dumpbin is required to verify the native DLL dependency tree")
    binary_root = RUNTIME / "bin"
    binaries = {p.name.lower(): p for p in binary_root.iterdir() if p.suffix.lower() in (".exe", ".dll")}
    imported = {}
    for name, path in sorted(binaries.items()):
        output = subprocess.run([str(dumpbin), "/DEPENDENTS", str(path)], capture_output=True,
                                text=True, check=True).stdout
        imported[name] = sorted(set(re.findall(r"^\s+([A-Za-z0-9_.-]+\.dll)\s*$", output, re.M | re.I)), key=str.lower)
    pending, reachable, systems, missing = ["twinpals-worker.exe"], set(), set(), set()
    system_root = Path(os.environ["SystemRoot"]) / "System32"
    while pending:
        current = pending.pop()
        if current in reachable:
            continue
        reachable.add(current)
        for dependency in imported[current]:
            normalized = dependency.lower()
            if normalized in binaries:
                pending.append(normalized)
            elif normalized.startswith(("api-ms-win-", "ext-ms-win-")):
                systems.add(dependency)
            elif normalized.startswith(("msvcp", "vcruntime", "concrt")):
                missing.add(dependency)  # never silently rely on a machine-wide VC runtime
            elif (system_root / dependency).is_file():
                systems.add(dependency)
            else:
                missing.add(dependency)
    if missing:
        raise RuntimeError(f"Unbundled non-system dependencies: {sorted(missing)}")
    if args.refresh_existing:
        target = RUNTIME / "geant4-runtime-manifest.json"
        manifest = json.loads(target.read_text(encoding="utf-8"))
        version = json.loads(subprocess.run([str(binary_root / "twinpals-worker.exe"), "--version"],
                                           capture_output=True, text=True, check=True).stdout)
        manifest.update(version)
        manifest["accessed_date"] = datetime.now(timezone.utc).date().isoformat()
        manifest["dependency_audit"].update(missing_non_system_dependencies=[],
            required_local_binaries=len(reachable), os_provided_imports=sorted(systems))
        manifest["binaries"] = [dict(path=path.relative_to(ROOT).as_posix(), bytes=path.stat().st_size,
            sha256=digest(path), required_by_worker=name in reachable, imports=imported[name])
            for name,path in sorted(binaries.items())]
        target.write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
        print(json.dumps(dict(status="passed", worker_version=version["worker_version"],
            binaries_audited=len(binaries), required_local_binaries=len(reachable),
            missing_non_system_dependencies=[], manifest_sha256=digest(target)), indent=2))
        return
    archives = []
    sources = [
        ("WIN64-VC17.11.4-11.zip", "https://geant4-data.web.cern.ch/releases/lib4.11.4/WIN64-VC17.11.4-11.zip", None, None),
        ("G4EMLOW.8.8.tar.gz", "https://geant4-data.web.cern.ch/datasets/G4EMLOW.8.8.tar.gz", "G4EMLOW8.8", "328330009df633f7e9b3a9f445745298"),
        ("G4ENSDFSTATE.3.0.tar.gz", "https://geant4-data.web.cern.ch/datasets/G4ENSDFSTATE.3.0.tar.gz", "G4ENSDFSTATE3.0", "c500728534ce3e9fb2fefa0112eb3a74"),
        ("G4PhotonEvaporation.6.1.2.tar.gz", "https://geant4-data.web.cern.ch/datasets/G4PhotonEvaporation.6.1.2.tar.gz", "PhotonEvaporation6.1.2", "d80ba9bdefcf9e23487a26adfa273304"),
    ]
    for name, url, dataset, expected_md5 in sources:
        path = RUNTIME / "geant4-downloads" / name
        entry = dict(archive=name, source_url=url, bytes=path.stat().st_size, sha256=digest(path))
        if dataset:
            actual_md5 = digest(path, "md5")
            assert actual_md5 == expected_md5, name
            entry.update(dataset_directory=f".runtime/geant4-data/{dataset}",
                         published_md5=expected_md5, md5_verified=True)
        archives.append(entry)
    license_dir = RUNTIME / "geant4-licenses"
    license_files = [dict(path=p.relative_to(ROOT).as_posix(), sha256=digest(p))
                     for p in sorted(license_dir.iterdir()) if p.is_file()]
    third_party = [
        dict(component="Geant4 11.4.0", license="Geant4 Software License",
             notice=".runtime/geant4-licenses/Geant4-LICENSE.txt",
             corresponding_source="https://github.com/Geant4/geant4/tree/v11.4.0"),
        dict(component="CLHEP bundled with Geant4", license="LGPL-3.0 with incorporated GPL-3.0 terms",
             notices=[".runtime/geant4-licenses/CLHEP-COPYING.LESSER.txt", ".runtime/geant4-licenses/CLHEP-LICENSE.txt"],
             corresponding_source="https://github.com/Geant4/geant4/tree/v11.4.0/source/externals/clhep",
             linkage="Unmodified replaceable G4clhep.dll; native worker is dynamically linked"),
        dict(component="PTL", license="MIT", notice=".runtime/geant4-licenses/PTL-LICENSE.txt",
             corresponding_source="https://github.com/Geant4/geant4/tree/v11.4.0/source/externals/ptl"),
        dict(component="Expat", license="MIT", notice=".runtime/geant4-licenses/Expat-COPYING.txt",
             corresponding_source="https://github.com/Geant4/geant4/tree/v11.4.0/source/externals/expat"),
        dict(component="zlib 1.3.1", license="zlib", notice=".runtime/geant4-licenses/zlib-LICENSE.txt",
             corresponding_source="https://github.com/Geant4/geant4/tree/v11.4.0/source/externals/zlib"),
        dict(component="G4tools", notice=".runtime/geant4-licenses/G4tools-LICENSE.txt"),
        dict(component="nlohmann-json 3.11.3", license="MIT", notice=".runtime/geant4-licenses/nlohmann-json-LICENSE.txt",
             corresponding_source="https://github.com/nlohmann/json/tree/v3.11.3"),
        dict(component="Microsoft Visual C++ runtime 14.44.35211.0 x64", license="Microsoft Visual Studio license terms",
             origin="Unmodified release DLLs bundled in the official Geant4 Windows archive",
             redist_list="https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution",
             guidance="https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files",
             redistribution_condition="Redistribution is subject to the applicable Microsoft license terms for licensed Visual Studio users. No debug runtime DLLs are included."),
        dict(component="G4EMLOW8.8", notice=".runtime/geant4-licenses/G4EMLOW8.8-README.txt",
             restriction="DATA ARE *NOT* FOR COMMERCIAL USE AND MUST BE USED WITHIN GEANT4",
             restriction_source="Original upstream dataset README; no unrestricted-commercial-use claim is made"),
        dict(component="G4ENSDFSTATE3.0", notice=".runtime/geant4-licenses/G4ENSDFSTATE3.0-README.txt",
             data_provenance="ENSDF; original upstream README is preserved; no standalone data license inferred"),
        dict(component="PhotonEvaporation6.1.2", notice=".runtime/geant4-licenses/PhotonEvaporation6.1.2-README.txt",
             data_provenance="ENSDF; original upstream README is preserved; no standalone data license inferred"),
    ]
    reports = []
    for name in ("report.json", "release-regression.json", "source-statistics.json", "multithreading.json"):
        path = ROOT / "native" / "validation" / name
        if path.is_file():
            reports.append(dict(path=path.relative_to(ROOT).as_posix(), sha256=digest(path),
                                report=json.loads(path.read_text(encoding="utf-8"))))
    version = json.loads(subprocess.run([str(binary_root / "twinpals-worker.exe"), "--version"],
                                       capture_output=True, text=True, check=True).stdout)
    manifest = dict(schema="twinpals-native-runtime-v1", accessed_date="2026-10-17", **version,
        platform="Windows x64", minimum_os_model="Windows 10/11 x64 with OS Universal CRT",
        build=dict(generator="Visual Studio 17 2022", configuration="Release", toolset="MSVC 14.43.34808",
                   compiler="19.43.34810", windows_sdk="10.0.22621.0", cmake="4.0.1"),
        official_release_page="https://geant4.web.cern.ch/download/11.4.0.html",
        event_time_kernel=dict(field="primaries[].photoelectron_times_ns", channels=2,
                               semantics="Every QE-selected detection time relative to event zero, before electronic TTS; tracking order, not sorted",
                               missing_hit_value=[[], []], includes_all_generated_events=True),
        parallelism=dict(model="Native G4MTRunManager with worker-local actions and shared immutable geometry/configuration",
                         per_event_seed_mode=0, event_modulo=1, rng="CLHEP::MixMaxRng",
                         ordered_event_file=True, compact_live_stdout=True,
                         pending_serialized_bytes_limit=64*1024*1024, pending_events_limit="max(8,4*threads)",
                         event_record_bytes_limit=32*1024*1024,
                         memory_limit_scope="Reorder queue only; worker-local physics state and one current event/serialization per worker require additional memory",
                         reproducibility="Bitwise event equality tested at 1/2/4 threads for this pinned build. Earlier sequential Ranecu event streams differ."),
        version_limit="Pinned baseline 11.4.0; no claim of incorporating or validating later 11.4.x patches",
        archives=archives, environment=json.loads((RUNTIME / "geant4-env.json").read_text(encoding="utf-8-sig")),
        dependency_audit=dict(method="Recursive MSVC dumpbin /DEPENDENTS; bundled DLLs before Windows system APIs",
                              missing_non_system_dependencies=[], required_local_binaries=len(reachable),
                              os_provided_imports=sorted(systems),
                              dynamic_loading_limit="Static PE import closure only; the integration runs also exercise Geant4 data initialization and optical transport"),
        binaries=[dict(path=path.relative_to(ROOT).as_posix(), bytes=path.stat().st_size, sha256=digest(path),
                       required_by_worker=name in reachable, imports=imported[name]) for name,path in sorted(binaries.items())],
        licenses=license_files, third_party=third_party, validation_reports=reports)
    target = RUNTIME / "geant4-runtime-manifest.json"
    target.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    verified = json.loads(target.read_text(encoding="utf-8"))
    assert verified["dependency_audit"]["missing_non_system_dependencies"] == []
    print(json.dumps(dict(manifest=str(target), binaries=len(binaries), required=len(reachable),
                          os_imports=len(systems), missing=[])))


if __name__ == "__main__":
    main()
