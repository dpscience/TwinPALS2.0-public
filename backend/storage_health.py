# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Small free-space reserve for orderly stream shutdown, not a size forecast."""
import errno
from pathlib import Path
import shutil
import tempfile

RESERVE_BYTES=256*1024*1024


class StorageSpaceError(ValueError):
    pass


def exhausted(error):
    if isinstance(error,OSError) and (error.errno in (errno.ENOSPC,getattr(errno,'EDQUOT',122)) or getattr(error,'winerror',None) in (39,112)):
        return True
    text=str(error).lower()
    return any(s in text for s in ('no space left on device','disk quota exceeded','not enough space on the disk','disk is full'))


def space_message(detail=''):
    return ('Insufficient disk space for stream output or temporary live-analysis files. '
            + (detail+' ' if detail else '')
            + 'Free space on the output drive and the Windows temporary-files drive. '
            'Existing stream files are kept; .part files can be reopened after freeing space. '
            'A new simulation must be started explicitly.')


def ensure_capacity(paths):
    checked=set()
    for candidate in [*paths,Path(tempfile.gettempdir())]:
        path=Path(candidate)
        while not path.exists() and path!=path.parent:path=path.parent
        device=path.stat().st_dev
        if device in checked:continue
        checked.add(device)
        free=shutil.disk_usage(path).free
        if free<RESERVE_BYTES:
            raise StorageSpaceError(space_message(f'{path.anchor or path}: {free/1024**2:.0f} MiB free; 256 MiB are reserved for orderly shutdown.'))
