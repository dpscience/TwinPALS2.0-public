# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""One connected application window; a persistent event stream owns the lease."""
import threading
import time
import secrets


class ClientGate:
    def __init__(self):
        self.lock=threading.RLock();self.token=None;self.previous=None;self.released=0.

    def acquire(self):
        with self.lock:
            if self.token is not None:return None
            self.token=secrets.token_urlsafe(32);return self.token

    def owns(self,token):
        with self.lock:return bool(token) and self.token==token

    def release(self,token):
        with self.lock:
            if self.token==token:
                self.previous=token;self.released=time.monotonic();self.token=None

    def can_close(self,token):
        with self.lock:
            return self.owns(token) or (bool(token) and self.token is None and token==self.previous and time.monotonic()-self.released<5)
