# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""In-process API tests own a lease; actual SSE ownership is tested in browsers."""
from fastapi.testclient import TestClient as BaseClient


class TestClient(BaseClient):
    __test__ = False

    def __enter__(self):
        super().__enter__()
        self.token = self.app.state.clients.acquire()
        assert self.token, 'Test application already has a client'
        self.headers['X-TwinPALS-Client'] = self.token
        return self

    def __exit__(self, *args):
        self.app.state.clients.release(self.token)
        return super().__exit__(*args)
