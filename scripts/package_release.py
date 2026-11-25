# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Build and verify the complete portable Windows TwinPALS distribution.

The frontend and native runtime must already be built. No downloads are made.
Run with the project's .venv Python. Existing user data is never copied into a
release ZIP, overwritten, or removed by this script.
"""

from __future__ import annotations

import argparse
import ast
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import ssl
import struct
import subprocess
import sys
import tempfile
import uuid
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.mcp_server import VERSION as MCP_VERSION
MANIFEST = "release-manifest.json"
FIXED_ZIP_TIME = (2020, 1, 1, 0, 0, 0)
PROTECTED_TOP_LEVEL = {"data", "backups", "logs", ".venv", "backend", "frontend",
                       "native", ".runtime", "seed", "scripts", "tests", "docs", "research", "legal"}


def sha256(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            result.update(block)
    return result.hexdigest()


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True,
                               allow_nan=False) + "\n", encoding="utf-8")


def version() -> str:
    tree = ast.parse((ROOT / "backend/__init__.py").read_text(encoding="utf-8-sig"))
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__version__" for t in statement.targets):
            value = ast.literal_eval(statement.value)
            if isinstance(value, str) and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?", value):
                return value
    raise ValueError("backend.__version__ must be a literal semantic-version string")


def is_link(path: Path) -> bool:
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def checked_relative(value: str) -> Path:
    path = PurePosixPath(value)
    if (not value or path.is_absolute() or path.as_posix() != value or "\\" in value
            or any(p in (".", "..") or ":" in p or p.endswith((".", " "))
                   or PureWindowsPath(p).is_reserved() for p in path.parts)):
        raise ValueError(f"Unsafe package-relative path: {value!r}")
    return Path(*path.parts)


def contained(root: Path, relative: str) -> Path:
    target = root / checked_relative(relative)
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Path escapes package root: {relative}")
    current = target
    while current != root:
        if is_link(current):
            raise ValueError(f"Linked package path is unsupported: {current}")
        current = current.parent
    return target


def files(root: Path):
    if is_link(root):
        raise ValueError(f"Linked source directory is unsupported: {root}")
    for path in sorted(root.rglob("*"), key=lambda p: p.relative_to(root).as_posix()):
        if is_link(path):
            raise ValueError(f"Linked source is unsupported: {path}")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix not in (".pyc", ".pyo"):
            yield path


def copy_tree(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise ValueError(f"Required directory is missing: {source}")
    for path in files(source):
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def require_file(path: Path) -> None:
    if not path.is_file() or is_link(path):
        raise ValueError(f"Required regular file is missing: {path}")


def load_manifest(directory: Path) -> dict:
    require_file(directory / MANIFEST)
    value = json.loads((directory / MANIFEST).read_text(encoding="utf-8"))
    if value.get("format") != "twinpals-portable-release" or value.get("format_version") != 1:
        raise ValueError("Existing directory has no recognized TwinPALS release ownership manifest")
    entries = value.get("files")
    if not isinstance(entries, dict) or not entries:
        raise ValueError("Release ownership manifest has no file entries")
    for relative in entries:
        path = checked_relative(relative)
        if path.parts[0].casefold() in ("data", "backups", "logs") or relative == MANIFEST:
            raise ValueError(f"Manifest must not own user data or itself: {relative}")
    return value


def factory_database(directory: Path, destination: Path) -> dict:
    """Build from bundled factory inputs, never from a user's working database."""
    from backend.material_database import MaterialDatabase
    MaterialDatabase(destination, directory / 'seed/factory_catalogue.json')
    return {'bytes': destination.stat().st_size, 'sha256': sha256(destination)}


def install_initial_data(staged: Path, output: Path, manifest: dict) -> None:
    for relative, expected in manifest.get('initial_data', {}).items():
        if relative not in ('data/catalogue.tpdb',):
            raise ValueError('Only factory catalogue databases may initialize mutable data')
        target = contained(output, relative)
        if target.exists():
            continue  # User's database is never an owned release file.
        source = contained(staged, relative)
        require_file(source)
        if source.stat().st_size != expected['bytes'] or sha256(source) != expected['sha256']:
            raise ValueError('Factory database differs from its initialization manifest')
        target.parent.mkdir(parents=True, exist_ok=True)
        with source.open('rb') as reader, target.open('xb') as writer:
            shutil.copyfileobj(reader, writer)


def verify_folder(directory: Path) -> dict:
    directory = directory.resolve()
    manifest = load_manifest(directory)
    checked_directories = {directory}
    pending = []
    for relative, expected in manifest["files"].items():
        path = directory / checked_relative(relative)
        unchecked = []
        parent = path.parent
        while parent not in checked_directories:
            unchecked.append(parent)
            parent = parent.parent
        for parent in reversed(unchecked):
            if is_link(parent):
                raise ValueError(f"Linked package path is unsupported: {parent}")
            if not parent.is_dir() or not parent.resolve().is_relative_to(directory):
                raise ValueError(f"Package parent is missing or escapes package root: {parent}")
            checked_directories.add(parent)
        # Strict relative paths plus checked, non-linked ancestors establish
        # containment. require_file still rejects a link at each leaf. Cache
        # only ancestors within this call; never reuse checks across updates.
        pending.append((relative, path, expected))
    def verify_leaf(item):
        relative, path, expected = item
        require_file(path)
        if path.stat().st_size != expected["bytes"] or sha256(path) != expected["sha256"]:
            raise ValueError(f"Release file differs from its manifest: {relative}")
    # Thousands of small Geant4 tables make serialized Windows opens expensive.
    # Verify the same bytes and leaf-link rules with a bounded I/O worker pool;
    # parent containment is still checked once above within this invocation.
    with ThreadPoolExecutor(max_workers=min(8, len(pending))) as executor:
        for _ in executor.map(verify_leaf, pending):
            pass
    return manifest


def target_path(raw: str) -> Path:
    result = Path(raw)
    if not result.is_absolute():
        result = ROOT / result
    result = result.resolve()
    if not result.is_relative_to(ROOT) or result == ROOT:
        raise ValueError("Build outputs must remain inside the project directory")
    first = result.relative_to(ROOT).parts[0].casefold()
    if first in PROTECTED_TOP_LEVEL:
        raise ValueError(f"Refusing to use a source/runtime/user-data directory as an output: {result}")
    return result


def native_runtime(destination: Path) -> None:
    runtime = ROOT / ".runtime"
    require_file(runtime / "bin/twinpals-worker.exe")
    require_file(runtime / "bin/twinpals-analog.dll")
    require_file(runtime / "geant4-env.json")
    require_file(runtime / "geant4-runtime-manifest.json")
    require_file(runtime / "geant4-licenses/Geant4-LICENSE.txt")
    binary_target = destination / ".runtime/bin"
    binary_target.mkdir(parents=True)
    for path in sorted((runtime / "bin").iterdir()):
        if path.is_file() and (path.suffix.lower() == ".dll" or path.name == "twinpals-worker.exe"):
            if is_link(path):
                raise ValueError(f"Linked native binary is unsupported: {path}")
            shutil.copy2(path, binary_target / path.name)
    if not list(binary_target.glob("*.dll")):
        raise ValueError("Native runtime DLLs are missing")
    settings = json.loads((runtime / "geant4-env.json").read_text(encoding="utf-8-sig"))
    portable_settings, data_sources = {}, set()
    data_root = (runtime / "geant4-data").resolve()
    for key, value in settings.items():
        if not isinstance(value, str) or not (key.startswith("G4") or key == "GEANT4_DATA_DIR"):
            raise ValueError(f"Unsupported native runtime environment field: {key}")
        source = Path(value)
        source = (source if source.is_absolute() else ROOT / source).resolve()
        if not source.is_relative_to(data_root) or not source.is_dir():
            raise ValueError(f"Native dataset must exist inside .runtime/geant4-data: {key}")
        relative = source.relative_to(ROOT)
        portable_settings[key] = relative.as_posix()
        if source != data_root:
            data_sources.add(source)
    for key in ("G4LEDATA", "G4ENSDFSTATEDATA", "G4LEVELGAMMADATA"):
        if key not in portable_settings:
            raise ValueError(f"Required native dataset is not configured: {key}")
    for source in sorted(data_sources):
        copy_tree(source, destination / source.relative_to(ROOT))
    write_json(destination / ".runtime/geant4-env.json", portable_settings)
    copy_tree(runtime / "geant4-licenses", destination / ".runtime/geant4-licenses")
    manifest = json.loads((runtime / "geant4-runtime-manifest.json").read_text(encoding="utf-8"))
    # The portable manifest reports runtime identities. Local engineering receipts stay in the checkout.
    for key in tuple(manifest):
        if key.startswith("verification") or key in ("validation_reports", "cpu_count"):
            del manifest[key]
    manifest["environment"] = portable_settings
    write_json(destination / ".runtime/geant4-runtime-manifest.json", manifest)


def public_materials(destination: Path) -> None:
    from legal_catalog import build as build_catalog, copy_corresponding_source

    for name in ("LICENSE", "NOTICE.md", "CITATION.cff", "README.md"):
        source = ROOT / name
        if name == "README.md" and (ROOT / "maintenance/public/README.md").is_file():
            source = ROOT / "maintenance/public/README.md"
        shutil.copy2(source, destination / name)
    for name in ("STREAM_FORMAT.md", "MODULE2_STREAM.md", "PORTABLE_RELEASE.md", "BUILD.md",
                 "COMPONENTS.md", "mcp/README.md", "mcp/CLIENTS.md"):
        target = destination / "docs" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "docs" / name, target)
    for name in ("factory_catalogue.json", "geant4_materials.json", "README.md"):
        target = destination / "seed" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "seed" / name, target)
    copy_tree(ROOT/"docs/screenshots", destination/"docs/screenshots")
    copy_tree(ROOT/"docs/mcp/knowledge", destination/"docs/mcp/knowledge")
    build_catalog(destination / "legal/public", destination / "TwinPALS.exe")
    copy_corresponding_source(destination / "legal/sources")
    shutil.copy2(ROOT / "legal/UPSTREAM.md", destination / "legal/UPSTREAM.md")


def write_launcher(destination: Path) -> None:
    content = (
        "@echo off\r\nsetlocal\r\n"
        "cd /d \"%~dp0\"\r\n"
        "if not exist \"%~dp0TwinPALS.exe\" (\r\n"
        "  echo TwinPALS.exe is missing. Extract the complete release folder first.\r\n"
        "  pause\r\n  exit /b 1\r\n)\r\n"
        "\"%~dp0TwinPALS.exe\" --no-browser %*\r\n"
        "set \"TwinPALSExitCode=%ERRORLEVEL%\"\r\n"
        "if not \"%TwinPALSExitCode%\"==\"0\" (\r\n"
        "  echo TwinPALS stopped with error %TwinPALSExitCode%.\r\n  pause\r\n)\r\n"
        "exit /b %TwinPALSExitCode%\r\n"
    )
    (destination / "Start-TwinPALS.cmd").write_bytes(content.encode("ascii"))


def install_owned(staged: Path, output: Path, replace_owned: bool) -> Path | None:
    """Install only manifest-owned files. Preserve user data and unexpected files."""
    output.parent.mkdir(parents=True, exist_ok=True)
    if is_link(output):
        raise ValueError("Release output must not be a link/junction")
    if not output.exists() or (output.is_dir() and not any(output.iterdir())):
        if output.exists():
            output.rmdir()  # Only the verified empty directory, never recursive.
        staged.rename(output)
        return None
    if not replace_owned:
        raise ValueError("Release directory is not empty. Choose another --output, or use --replace-owned for a verified previous release. User data was not touched.")
    previous = verify_folder(output)
    incoming = verify_folder(staged)
    old_paths, new_paths = set(previous["files"]), set(incoming["files"])
    unchanged = {relative for relative in old_paths & new_paths
                 if previous["files"][relative] == incoming["files"][relative]}
    changed_or_new = new_paths - unchanged
    for relative in changed_or_new:
        target = contained(output, relative)
        if target.exists() and relative not in old_paths:
            raise ValueError(f"Unowned release file would be overwritten: {relative}")
        for parent in target.parents:
            if parent == output:
                break
            if parent.exists() and not parent.is_dir():
                raise ValueError(f"Non-directory blocks incoming package: {parent}")
    backup = ROOT / "tmp" / ("release-backup-" + uuid.uuid4().hex)
    backup.mkdir(parents=True)
    backup_paths = old_paths - unchanged
    for relative in sorted(backup_paths | {MANIFEST}):
        source, target = contained(output, relative), contained(backup, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if relative != MANIFEST and (target.stat().st_size != previous["files"][relative]["bytes"]
                                      or sha256(target) != previous["files"][relative]["sha256"]):
            raise ValueError(f"Owned file changed while preparing its rollback backup: {relative}")
    write_json(backup / "rollback-metadata.json", {
        "format": "twinpals-owned-update-rollback", "format_version": 1,
        "backup_scope": "changed_or_removed_owned_files_and_previous_manifest",
        "staged_directory": str(staged), "unchanged_files": sorted(unchanged),
        "copied_files": sorted(changed_or_new), "removed_files": sorted(old_paths - new_paths),
        "note": "Identical files remain in the installation. The retained verified staging tree contains the identical bytes needed if an unchanged file must be repaired during rollback. This is a sparse update backup, not a standalone old release.",
    })
    copied = []
    try:
        for relative in sorted(changed_or_new):
            target = contained(output, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            copied.append(relative)
            shutil.copy2(contained(staged, relative), target)
        for relative in sorted(old_paths - new_paths):
            contained(output, relative).unlink()  # Verified manifest-owned file only.
        shutil.copy2(staged / MANIFEST, output / MANIFEST)
        verify_folder(output)
        install_initial_data(staged, output, incoming)
    except BaseException:
        for relative in copied:
            if relative not in old_paths:
                contained(output, relative).unlink(missing_ok=True)
        for relative in sorted(backup_paths | {MANIFEST}):
            target = contained(output, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(contained(backup, relative), target)
        for relative in sorted(unchanged):
            target = contained(output, relative)
            expected = previous["files"][relative]
            if target.is_file() and target.stat().st_size == expected["bytes"] and sha256(target) == expected["sha256"]:
                continue
            # Both manifests verified these staging bytes as exactly the old
            # contents. Do not overwrite a file unless that identity still holds.
            source = contained(staged, relative)
            require_file(source)
            if source.stat().st_size != expected["bytes"] or sha256(source) != expected["sha256"]:
                raise RuntimeError(f"Rollback source no longer matches the verified unchanged file: {relative}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        verify_folder(output)
        raise
    return backup


def make_zip(directory: Path, target: Path, release_version: str) -> None:
    manifest = verify_folder(directory)
    if target.exists():
        raise ValueError(f"ZIP already exists; choose a new --zip-path to preserve it: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + "." + uuid.uuid4().hex + ".partial")
    prefix = "release/"
    try:
        with tempfile.TemporaryDirectory(prefix='factory-db-',dir=ROOT/'tmp') as factory, zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
            for relative in sorted(set(manifest["files"]) | {MANIFEST}):
                path = contained(directory, relative)
                entry = zipfile.ZipInfo(prefix + relative, FIXED_ZIP_TIME)
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.create_system = 3
                entry.external_attr = 0o100644 << 16
                with path.open("rb") as source, archive.open(entry, "w", force_zip64=True) as destination:
                    shutil.copyfileobj(source, destination, length=1024 * 1024)
            for relative, expected in manifest.get('initial_data', {}).items():
                if relative not in ('data/catalogue.tpdb',):
                    raise ValueError('Unsupported mutable factory data')
                database = Path(factory) / Path(relative).name
                if factory_database(directory, database) != expected:
                    raise ValueError('Bundled seed no longer produces the verified factory database')
                entry = zipfile.ZipInfo(prefix + relative, FIXED_ZIP_TIME)
                entry.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(entry, database.read_bytes())
        verify_zip(temporary)
        temporary.rename(target)
        target.with_suffix(target.suffix + ".sha256").write_text(sha256(target) + "  " + target.name + "\n", encoding="ascii")
    finally:
        temporary.unlink(missing_ok=True)


def verify_zip(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if not names or len(set(names)) != len(names):
            raise ValueError("Release ZIP is empty or has duplicate members")
        prefixes = set()
        for name in names:
            relative = checked_relative(name)
            if len(relative.parts) < 2:
                raise ValueError("Release ZIP must contain one complete top-level folder")
            prefixes.add(relative.parts[0])
        if len(prefixes) != 1:
            raise ValueError("Release ZIP has multiple top-level folders")
        prefix = prefixes.pop() + "/"
        manifest = json.loads(archive.read(prefix + MANIFEST))
        if manifest.get("format") != "twinpals-portable-release":
            raise ValueError("Unsupported release ZIP manifest")
        expected_names = {prefix + relative for relative in manifest["files"]} | {prefix + MANIFEST} | {prefix+relative for relative in manifest.get('initial_data',{})}
        if set(names) != expected_names:
            raise ValueError("Release ZIP membership differs from its manifest")
        for relative, expected in manifest["files"].items():
            if checked_relative(relative).parts[0].casefold() in ("data", "backups", "logs"):
                raise ValueError("Release ZIP must not contain user data")
            result, count = hashlib.sha256(), 0
            with archive.open(prefix + relative) as source:
                while block := source.read(1024 * 1024):
                    result.update(block)
                    count += len(block)
            if count != expected["bytes"] or result.hexdigest() != expected["sha256"]:
                raise ValueError(f"Release ZIP hash mismatch: {relative}")
        for relative, expected in manifest.get('initial_data',{}).items():
            if relative not in ('data/catalogue.tpdb',):
                raise ValueError('Unsupported mutable factory data')
            value=archive.read(prefix+relative)
            if len(value)!=expected['bytes'] or hashlib.sha256(value).hexdigest()!=expected['sha256']:
                raise ValueError('Factory database ZIP hash mismatch')
        # Reading every member above also verifies each ZIP CRC without extracting.
        return manifest


def build(args) -> None:
    if os.name != "nt":
        raise ValueError("The portable Windows build must run on Windows")
    if struct.calcsize("P") != 8:
        raise ValueError("The Windows x64 release requires a 64-bit build interpreter")
    output = target_path(args.output)
    release_version = version()
    from backend.mcp_server.knowledge import source_metadata
    source_metadata(version=release_version,official=args.public_release)
    zip_path = target_path(args.zip_path or f"dist/TwinPALS-{release_version}-windows-x64.zip")
    from build_installer import build_installer, compiler, output_for, require_new
    iscc = compiler()
    installer_path = output_for(zip_path)
    require_new(installer_path)
    if not args.no_zip and zip_path.exists():
        raise ValueError("Versioned ZIP already exists; preserve it or choose --zip-path explicitly")
    if output.exists() and any(output.iterdir()):
        if not args.replace_owned:
            raise ValueError("Output is not empty; choose another --output or explicitly use --replace-owned")
        verify_folder(output)
    for relative in ("backend/launcher.py", "frontend/dist/index.html", "frontend/package-lock.json",
                     "seed/factory_catalogue.json", "README.md", ".runtime/bin/twinpals-worker.exe",
                     ".runtime/geant4-env.json", ".runtime/geant4-runtime-manifest.json"):
        require_file(ROOT / relative)
    metadata.version("pyinstaller")
    (ROOT / "tmp").mkdir(exist_ok=True)
    if not args.skip_tests:
        test_temp=ROOT / "tmp" / ("release-tests-"+uuid.uuid4().hex)
        subprocess.run([sys.executable, "-m", "pytest", "-q", "--basetemp", str(test_temp)], cwd=ROOT, check=True)
    build_root = ROOT / "tmp" / ("release-build-" + uuid.uuid4().hex)
    build_root.mkdir(parents=True)
    numeric_version = tuple(int(n) for n in re.split(r"[-+]", release_version)[0].split(".")) + (0,)
    version_file = build_root / "windows-version-info.txt"
    version_file.write_text(
        "VSVersionInfo(ffi=FixedFileInfo(filevers=" + repr(numeric_version)
        + ", prodvers=" + repr(numeric_version)
        + ", mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)), "
        "kids=[StringFileInfo([StringTable('040904B0', ["
        "StringStruct('FileDescription', 'TwinPALS'), "
        "StringStruct('FileVersion', " + repr(release_version) + "), "
        "StringStruct('InternalName', 'TwinPALS'), StringStruct('OriginalFilename', 'TwinPALS.exe'), "
        "StringStruct('LegalCopyright', 'Copyright (c) 2026 Danny Petschke <twinpals@proton.me>'), "
        "StringStruct('ProductName', 'TwinPALS 2.0'), StringStruct('ProductVersion', "
        + repr(release_version) + ")])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])])\n",
        encoding="utf-8")
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--console", "--hide-console", "hide-early",
               "--name", "TwinPALS", "--paths", str(ROOT), "--distpath", str(build_root / "dist"),
               "--workpath", str(build_root / "work"), "--specpath", str(build_root),
               "--version-file", str(version_file), "--icon", str(ROOT/"frontend/public/favicon.ico"),
               "--exclude-module", "pytest", "--exclude-module", "_pytest", "--exclude-module", "PIL",
               "--exclude-module", "setuptools", "--exclude-module", "psutil", "--exclude-module", "pygments",
               "--collect-submodules", "uvicorn", "--copy-metadata", "fastapi", "--copy-metadata", "pydantic",
               "--copy-metadata", "uvicorn", str(ROOT / "backend/launcher.py")]
    with (build_root / "pyinstaller.log").open("w", encoding="utf-8") as log:
        result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f"PyInstaller failed; inspect {build_root / 'pyinstaller.log'}")
    staged = build_root / "dist/TwinPALS"
    require_file(staged / "TwinPALS.exe")
    # Some Windows Python distributions load a certificate rejection list
    # next to ssl.py every time a TLS context is created. PyInstaller freezes
    # the module, but does not collect this adjacent runtime data.
    tls_policy = Path(ssl.__file__).with_name("codex-rejected-cas.pem")
    if tls_policy.is_file():
        require_file(tls_policy)
        shutil.copy2(tls_policy, staged / "_internal" / tls_policy.name)
    subprocess.run([str(staged / "TwinPALS.exe"), "--verify-tls"], check=True, timeout=30)
    # Both launchers use one frozen interpreter and one scientific runtime.
    shutil.copy2(staged / "TwinPALS.exe", staged / "TwinPALS-MCP.exe")
    compiler=Path(os.environ["SystemRoot"])/"Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    subprocess.run([str(compiler), "/nologo", "/codepage:65001", "/target:winexe", "/optimize+", "/platform:x64",
                    "/win32manifest:"+str(ROOT/"native/windows/TwinPALSTray.manifest"),
                    "/win32icon:"+str(ROOT/"frontend/public/favicon.ico"),
                    "/reference:System.Windows.Forms.dll", "/reference:System.Drawing.dll",
                    "/reference:System.Web.Extensions.dll", "/out:"+str(staged/"_internal/TwinPALS.Tray.exe"),
                    str(ROOT/"native/windows/TwinPALSTray.cs")], check=True)
    if not (staged / "_internal").is_dir():
        raise ValueError("PyInstaller did not produce the complete onedir _internal runtime")
    # The native file picker is imported on demand by the application. A build
    # with an inaccessible Tcl installation can otherwise silently omit it.
    for relative in ("_tkinter.pyd", "_tcl_data/init.tcl", "_tk_data/tk.tcl"):
        require_file(staged / "_internal" / relative)
    copy_tree(ROOT / "frontend/dist", staged / "frontend/dist")
    native_runtime(staged)
    public_materials(staged)
    write_launcher(staged)
    (staged / "VERSION.txt").write_text(release_version + "\n", encoding="ascii")
    initial_databases = {f'data/{name}':factory_database(staged,staged/'data'/name) for name in ('catalogue.tpdb',)}
    manifest = {"format": "twinpals-portable-release", "format_version": 1, "application": "TwinPALS",
                "version": release_version, "platform": "windows-x64", "layout": "pyinstaller-onedir",
                "mcp_version": MCP_VERSION,
                "python_version": sys.version.split()[0], "pyinstaller_version": metadata.version("pyinstaller"),
                "validation": {"tests": "not_run_by_packager" if args.skip_tests else "passed",
                               "isolated_launch_and_simulation": "required_separately"},
                "initial_data": initial_databases,
                "files": {p.relative_to(staged).as_posix(): {"bytes": p.stat().st_size, "sha256": sha256(p)} for p in files(staged) if p.relative_to(staged).parts[0]!='data'}}
    write_json(staged / MANIFEST, manifest)
    verify_folder(staged)
    backup = install_owned(staged, output, args.replace_owned)
    verify_folder(output)
    build_installer(output, installer_path, iscc)
    print(f"Windows installer: {installer_path}")
    if not args.no_zip:
        make_zip(output, zip_path, release_version)
    print(f"Portable folder: {output}\nVersion: {release_version}\nOwned files verified: {len(manifest['files'])}")
    if not args.no_zip:
        print(f"Verified ZIP: {zip_path}")
    if backup:
        print(f"Sparse previous owned-file backup: {backup}; unchanged files and user data stayed in place")
    print(f"Build log: {build_root / 'pyinstaller.log'}")
    print("Isolated EXE/launcher and real simulation checks remain required before delivery.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="release", help="Project-relative portable folder")
    parser.add_argument("--zip-path", help="Project-relative versioned ZIP path; existing ZIPs are preserved")
    parser.add_argument("--no-zip", action="store_true")
    parser.add_argument("--public-release", action="store_true", help="Require the confirmed repository and exact official release link before building")
    parser.add_argument("--skip-tests", action="store_true", help="Use only after independent test execution; recorded in the manifest")
    parser.add_argument("--replace-owned", action="store_true", help="Back up and replace only verified manifest-owned package files")
    parser.add_argument("--verify-folder", type=Path, help="Verify an existing portable folder without building")
    parser.add_argument("--verify-zip", type=Path, help="Verify a release ZIP without extracting or building")
    args = parser.parse_args()
    try:
        if args.verify_folder or args.verify_zip:
            if args.verify_folder:
                result = verify_folder(args.verify_folder)
                print(f"Folder verified: TwinPALS {result['version']}, {len(result['files'])} files")
            if args.verify_zip:
                result = verify_zip(args.verify_zip)
                print(f"ZIP verified: TwinPALS {result['version']}, {len(result['files'])} files")
        else:
            build(args)
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError, metadata.PackageNotFoundError, zipfile.BadZipFile) as error:
        print(f"Packaging failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
