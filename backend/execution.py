# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Resolve portable CPU requests against the current workstation."""
import os


def cpu_settings():
    count = max(1, os.cpu_count() or 1)
    return {"cpu_count": count, "recommended_threads": max(1, min(count - 1, 32))}


def resolve_threads(requested, events):
    settings = cpu_settings()
    chosen = settings["recommended_threads"] if requested == 0 else requested
    return max(1, min(chosen, settings["cpu_count"], events, 256))


def import_workers(requested):
    if type(requested) is not int or not 0 <= requested <= 256:
        raise ValueError('Choose Auto or 1–256 import workers.')
    return resolve_threads(requested, 256)
