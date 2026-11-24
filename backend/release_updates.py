# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Check only the latest stable upstream release. Desktop and observer share the workspace cache."""
from contextlib import closing
import json
import re
import sqlite3
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from backend import __version__

REPOSITORY = 'dpscience/TwinPALS2.0-public'
API = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
TAG = re.compile(r'v?(0|[1-9]\d{0,8})\.(0|[1-9]\d{0,8})\.(0|[1-9]\d{0,8})', re.ASCII)


def latest_tag():
    request = Request(API, headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'TwinPALS/' + __version__})
    try:
        with urlopen(request, timeout=4) as response:
            value = json.loads(response.read(512 * 1024))
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    if not isinstance(value, dict) or value.get('draft') is not False or value.get('prerelease') is not False:
        return None
    tag = value.get('tag_name')
    return tag if isinstance(tag, str) and TAG.fullmatch(tag) else None


def release_status(data, *, refresh=False, manual=False):
    tag = None
    state = 'unchecked'
    checked = 0
    cache = data / 'release-check.sqlite'
    if refresh or cache.is_file():
        try:
            with closing(sqlite3.connect(cache, timeout=7)) as db, db:
                if refresh:
                    db.execute('BEGIN IMMEDIATE')
                    db.execute('CREATE TABLE IF NOT EXISTS latest (id INTEGER PRIMARY KEY, checked INTEGER, state TEXT, tag TEXT)')
                row = db.execute('SELECT checked,state,tag FROM latest WHERE id=1').fetchone()
                if row:
                    checked, state, tag = row
                now = int(time.time())
                if refresh and (not row or not 0 <= now - checked < (15 if manual else 86400)):
                    try:
                        tag = latest_tag()
                        state = 'checked'
                    except (OSError, ValueError):
                        state = 'offline'
                    checked = now
                    db.execute('INSERT OR REPLACE INTO latest VALUES (1,?,?,?)', (checked, state, tag))
        except sqlite3.Error:
            state = 'offline'
    match = TAG.fullmatch(tag or '')
    latest = '.'.join(match.groups()) if match else None
    available = bool(latest and tuple(map(int, latest.split('.'))) > tuple(map(int, __version__.split('.'))))
    return dict(installed=__version__, latest=latest, available=available, state=state,
                url=f'https://github.com/{REPOSITORY}/releases/tag/{tag}' if match else None)

