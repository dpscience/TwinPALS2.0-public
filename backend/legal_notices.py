# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Serve only the reviewed public notices, independently of client or study state."""

from fastapi.staticfiles import StaticFiles


def mount_legal_notices(app, root):
    public = root / "legal" / "public"
    if public.is_dir():
        app.mount("/legal", StaticFiles(directory=public), name="legal-notices")
