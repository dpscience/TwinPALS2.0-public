# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""One running application per writable workspace, including across ports."""
import os
from pathlib import Path


class WorkspaceLock:
    def __init__(self,root:Path):
        root.mkdir(parents=True,exist_ok=True)
        self.stream=(root/".server.lock").open("a+b")
        self.stream.seek(0,2)
        if not self.stream.tell():
            self.stream.write(b"0")
            self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name=="nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as exc:
            self.stream.close()
            raise RuntimeError("This TwinPALS folder is already open in another server. Use its printed URL or choose --data-dir for a separate folder.") from exc

    def close(self):
        if self.stream.closed:
            return
        self.stream.seek(0)
        if os.name=="nt":
            import msvcrt
            msvcrt.locking(self.stream.fileno(),msvcrt.LK_UNLCK,1)
        else:
            import fcntl
            fcntl.flock(self.stream.fileno(),fcntl.LOCK_UN)
        self.stream.close()
