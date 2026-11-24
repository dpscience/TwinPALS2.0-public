# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Compile an Inno installer from the verified immutable portable payload."""
import os
from contextlib import contextmanager
from pathlib import Path, PureWindowsPath
import shutil
import subprocess
import uuid


def compiler():
    override = os.environ.get('TWINPALS_ISCC')
    if override:
        paths = [Path(override)]
    else:
        paths = [Path(p) / 'Inno Setup 7' / 'ISCC.exe' for p in (
            Path(os.environ.get('LOCALAPPDATA', '.')) / 'Programs',
            os.environ.get('ProgramFiles', '.'), os.environ.get('ProgramFiles(x86)', '.'))]
        if found := shutil.which('ISCC'):
            paths.append(Path(found))
    for path in paths:
        if path.is_file():
            return path.resolve()
    raise ValueError('Install Inno Setup 7 or set TWINPALS_ISCC to its ISCC.exe.')


def output_for(archive):
    return archive.with_name(archive.stem + '-setup.exe')


def require_new(target):
    if target.exists() or target.with_suffix(target.suffix + '.sha256').exists():
        raise ValueError(f'Choose a new installer output path to preserve existing artifacts: {target}')


@contextmanager
def staging_directory(parent):
    # Files keep their Windows ACL on rename. Inherit the release directory's
    # permissions so the installer and checksum remain readable when shared.
    stage = parent / ('inno-' + uuid.uuid4().hex)
    stage.mkdir()
    try:
        yield stage
    finally:
        shutil.rmtree(stage)


def build_installer(folder, target, iscc):
    from package_release import MANIFEST, ROOT, sha256, verify_folder
    manifest = verify_folder(folder)
    require_new(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    # The generated include enumerates immutable files. Runtime-created databases,
    # logs and user files are never enumerated by walking a used installation.
    with staging_directory(target.parent) as stage:
        include = stage / 'payload.iss'
        with include.open('w', encoding='utf-8-sig') as entries:
            for relative in sorted([*manifest['files'], MANIFEST]):
                name = PureWindowsPath(relative)
                source = folder / name
                if any(c in str(source) for c in ('{', '}', '"', '*', '?', '\r', '\n')):
                    raise ValueError(f'Unsupported Inno source path: {source}')
                parent = '' if name.parent == PureWindowsPath('.') else '\\' + str(name.parent)
                entries.write(f'Source: "{source}"; DestDir: "{{app}}{parent}"; Flags: ignoreversion\n')
        subprocess.run([str(iscc), '/Q', '/DProductVersion=' + manifest['version'],
                        '/DPayloadList=' + str(include), '/O' + str(stage),
                        str(ROOT / 'native/windows/installer/TwinPALS.iss')], check=True)
        exe = stage / 'TwinPALS-setup.exe'
        digest = sha256(exe)
        check = stage / 'digest'
        check.write_text(digest + '  ' + target.name + '\n', encoding='ascii')
        exe.rename(target)
        try:
            check.rename(target.with_suffix(target.suffix + '.sha256'))
        except OSError:
            target.unlink()
            raise
    return digest

