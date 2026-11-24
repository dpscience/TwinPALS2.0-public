# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Provision pinned Geant4 build inputs from a verified, reusable archive cache."""

import argparse
import hashlib
import json
import os
import shutil
import tarfile
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "third_party/geant4"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate_member(name, top):
    path = PurePosixPath(name)
    if not path.parts or path.parts[0] != top or ".." in path.parts or "\\" in name or ":" in name:
        raise ValueError(f"Unexpected archive member: {name}")


def cached_archive(entry, cache, offline):
    archive = cache / entry["archive"]
    if archive.is_file() and digest(archive) == entry["sha256"]:
        return archive
    if offline:
        raise ValueError(f"Offline cache is missing the verified archive {archive}")
    cache.mkdir(parents=True, exist_ok=True)
    temporary = cache / (archive.name + "." + uuid.uuid4().hex + ".part")
    try:
        print(f"Downloading {archive.name}", flush=True)
        with urlopen(entry["source"], timeout=120) as response, temporary.open("xb") as output:
            shutil.copyfileobj(response, output, length=1024*1024)
        if digest(temporary) != entry["sha256"]:
            raise ValueError(f"Downloaded archive has the wrong SHA-256: {archive.name}")
        os.replace(temporary, archive)
    finally:
        temporary.unlink(missing_ok=True)
    return archive


def restore(entry, archive, runtime, temp):
    target = runtime / entry["target"]
    target.parent.mkdir(parents=True, exist_ok=True)
    if entry["kind"] == "source":
        if target.exists():
            if digest(target) != entry["sha256"]:
                raise ValueError(f"Different corresponding source already exists: {target}")
        else:
            staged = temp / archive.name
            shutil.copyfile(archive, staged)
            os.replace(staged, target)
        return
    marker = runtime / "bundle-receipts" / entry["sha256"]
    if marker.is_file() and (target / entry["probe"]).is_file():
        return
    unpack = temp / "extract"
    unpack.mkdir(exist_ok=True)
    if entry["kind"] == "sdk":
        with zipfile.ZipFile(archive) as z:
            for name in z.namelist():
                validate_member(name, target.name)
            z.extractall(unpack)
    else:
        with tarfile.open(archive, "r:gz") as tar:
            for member in tar:
                validate_member(member.name, target.name)
                if not (member.isdir() or member.isfile()):
                    raise ValueError(f"Unexpected archive entry: {member.name}")
                tar.extract(member, unpack, filter="data")
    extracted = unpack / target.name
    if not (extracted / entry["probe"]).is_file():
        raise ValueError(f"Missing expected content: {entry['probe']}")
    if target.exists():
        for file in extracted.rglob("*"):
            if file.is_file():
                existing = target / file.relative_to(extracted)
                if not existing.is_file() or digest(existing) != digest(file):
                    raise ValueError(f"Existing installation differs: {existing}")
    else:
        extracted.rename(target)
    marker.parent.mkdir(exist_ok=True)
    marker.write_text(archive.name, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify archives without provisioning a runtime")
    default_cache = Path(os.environ.get("LOCALAPPDATA", ROOT / ".runtime")) / "TwinPALS/build-cache/geant4"
    parser.add_argument("--cache", type=Path, default=os.environ.get("TWINPALS_GEANT4_CACHE", default_cache))
    parser.add_argument("--offline", action="store_true", help="Require all six verified archives in the cache")
    args = parser.parse_args()
    manifest = json.loads((BUNDLE / "bundle.json").read_text(encoding="utf-8"))
    runtime = ROOT / ".runtime"
    if not args.check:
        runtime.mkdir(exist_ok=True)
    for entry in manifest["archives"]:
        archive = cached_archive(entry, args.cache, args.offline)
        if not args.check:
            work = runtime / (".restore-" + uuid.uuid4().hex)
            work.mkdir()
            try:
                restore(entry, archive, runtime, work)
            finally:
                shutil.rmtree(work)
        print(f"Verified {entry['archive']}", flush=True)
    for name, record in manifest["notices"].items():
        source = ROOT / "legal/public/texts" / record["file"]
        if digest(source) != record["sha256"]:
            raise ValueError(f"Notice digest mismatch: {name}")
        if not args.check:
            (runtime / "geant4-licenses").mkdir(exist_ok=True)
            shutil.copyfile(source, runtime / "geant4-licenses" / name)
    if not args.check:
        (runtime / "geant4-env.json").write_text(json.dumps(manifest["environment"], indent=2), encoding="utf-8")
        target = runtime / "geant4-runtime-manifest.json"
        if not target.exists():
            shutil.copyfile(BUNDLE / "runtime-template.json", target)


if __name__ == "__main__":
    main()
