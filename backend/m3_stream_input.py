# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Sequential, shareable reads of large finalized waveform recordings."""
from concurrent.futures import ThreadPoolExecutor, wait
from contextlib import ExitStack, contextmanager
import os

ALIGNMENT = 64 * 1024


def _direct_handle(source):
    """Open a separate Windows file pointer on the same file, including after a rename."""
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    reopen = kernel.ReOpenFile
    reopen.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD]
    reopen.restype = wintypes.HANDLE
    handle = reopen(msvcrt.get_osfhandle(source.fileno()), 0x80000000, 7, 0x20000000)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        kernel.CloseHandle(wintypes.HANDLE(handle))
        raise
    return os.fdopen(descriptor, 'rb', buffering=0)


@contextmanager
def stream_input(reader):
    source = reader.file

    def buffered(at, destination):
        if source.tell() != at:
            source.seek(at)
        return source.readinto(destination)

    # A growing stream must see its writer's buffered tail. Small inputs and
    # filesystems without unbuffered reads use the existing portable reader.
    if os.name != 'nt' or reader.path.suffix == '.part' or reader.limit < 256 * 1024**2:
        yield buffered
        return
    with ExitStack() as resources:
        try:
            files = [resources.enter_context(_direct_handle(source)) for _ in range(3)]
        except OSError:
            yield buffered
            return
        pool = resources.enter_context(ThreadPoolExecutor(max_workers=3, thread_name_prefix='M3-disk'))
        supported = True

        def read_lane(file, at, target):
            file.seek(at)
            return file.readinto(target)

        def read(at, target):
            nonlocal supported
            size = len(target) // ALIGNMENT * ALIGNMENT
            if not supported or at % ALIGNMENT or target.ctypes.data % ALIGNMENT or size < 4 * 1024**2:
                return buffered(at, target)
            # Independent requests keep an SSD busy without a second copy of its data in RAM.
            lanes = min(len(files), max(1, size // (4 * 1024**2)))
            blocks = size // ALIGNMENT
            futures = []
            for lane in range(lanes):
                start = (blocks * lane // lanes) * ALIGNMENT
                end = (blocks * (lane + 1) // lanes) * ALIGNMENT
                futures.append(pool.submit(read_lane, files[lane], at + start, target[start:end]))
            wait(futures)
            try:
                if sum(f.result() for f in futures) == size:
                    return size
            except OSError:
                pass
            # An unusual sector geometry or a cloud-backed file can reject a direct
            # request. The bounded, checksummed stream remains readable through its original handle.
            supported = False
            return buffered(at, target)

        yield read
