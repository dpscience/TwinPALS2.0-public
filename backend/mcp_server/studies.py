# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Immutable study definitions and the durable queue. One coordinator owns scheduling."""
import copy
import hashlib
import json
import os
import secrets
import sqlite3
import sys
import time
import uuid
from contextlib import closing
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from backend import __version__
from backend.execution import cpu_settings
from backend.m1_models import Profile as DetectorProfile
from backend.m1_store import atomic_json
from backend.m2_models import Profile as DigitizerProfile
from backend.m3_models import Profile as LifetimeProfile
from . import VERSION

MODELS = {1: DetectorProfile, 2: DigitizerProfile, 3: LifetimeProfile}
TERMINAL = {'completed', 'partial', 'cancelled', 'failed', 'blocked'}
KEY = r'^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$'


class Parameters(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Query(Parameters):
    name: str = Field(pattern=KEY)
    path: str = Field(description='Scientific workbench endpoint, for example /api/m3/analysis.')
    method: Literal['GET', 'POST'] = 'POST'
    body: dict = Field(default_factory=dict)


class Step(Parameters):
    key: str = Field(pattern=KEY)
    module: Literal[1, 2, 3]
    input_from: str | None = Field(default=None, description='Key of the preceding module in this study.')
    operation: Literal['run', 'import'] = 'run'
    inputs: list[str] = Field(default_factory=list, max_length=2)
    profile: dict | None = Field(default=None, description='Complete editable profile. Omit for the saved settings.')
    changes: dict = Field(default_factory=dict, description='JSON Pointer to value overrides, e.g. {"/run/events":1000}.')
    workers: int | None = Field(default=None, ge=1, le=256)
    queries: list[Query] = Field(default_factory=list, max_length=50)


class Study(Parameters):
    request_id: str = Field(min_length=1, max_length=180, description='Stable client-generated idempotency key. Reuse on reconnect.')
    name: str = Field(min_length=1, max_length=180)
    objective: str = Field(default='', max_length=8000)
    max_parallel: int = Field(default=3, ge=1, le=32)
    cpu_budget: int | None = Field(default=None, ge=1, le=256)
    steps: list[Step] = Field(min_length=1, max_length=500)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


@lru_cache(maxsize=1)
def scientific_runtime():
    import numpy
    from backend.app import application_root
    root=application_root()
    def file_hash(path):
        with path.open('rb') as data:
            return hashlib.file_digest(data,'sha256').hexdigest()
    files={name:file_hash(root/'.runtime/bin'/name) for name in ('twinpals-worker.exe','twinpals-analog.dll')
           if (root/'.runtime/bin'/name).is_file()}
    application=(file_hash(Path(sys.executable)) if getattr(sys,'frozen',False) else
                 digest({path.name:file_hash(path) for path in sorted((root/'backend').glob('*.py'))}))
    return dict(twinpals=__version__,mcp=VERSION,python=sys.version.split()[0],numpy=numpy.__version__,
                application_sha256=application,native_sha256=files)


def parts(pointer):
    if pointer == '':
        return []
    if not pointer.startswith('/'):
        raise ValueError('Use a JSON Pointer beginning with /.')
    return [p.replace('~1', '/').replace('~0', '~') for p in pointer[1:].split('/')]


def member(obj, key):
    if isinstance(obj, list):
        if not key.isdecimal():
            raise ValueError('A list requires a nonnegative index.')
        return int(key)
    return key


def select(obj, pointer):
    for key in parts(pointer):
        obj = obj[member(obj, key)]
    return obj


def prepare_profile(step, defaults):
    profile = copy.deepcopy(step.profile if step.profile is not None else defaults[step.module])
    for pointer, value in step.changes.items():
        keys = parts(pointer)
        if not keys:
            raise ValueError('Use profile to replace a complete profile.')
        obj = profile
        for key in keys[:-1]:
            obj = obj[member(obj, key)]
        key = member(obj, keys[-1])
        if isinstance(obj, dict) and key not in obj:
            raise ValueError(f'Unknown setting {pointer}')
        obj[key] = value
    profile = MODELS[step.module].model_validate(profile).model_dump(mode='json')
    if step.operation == 'run' and step.module < 3:
        seeded = profile['run'] if step.module == 1 else profile
        if seeded['auto_seed']:
            seeded['seed'] = secrets.randbelow(2147483646) + 1
        seeded['auto_seed'] = False
    return profile


def fingerprint(path):
    """Cheap, explicit identity for 300 GB streams. Full hashes are available separately."""
    path = Path(path).resolve(strict=True)
    h = hashlib.sha256()
    with path.open('rb') as stream:
        stat = os.fstat(stream.fileno())
        h.update(stream.read(65536))
        if stat.st_size > 65536:
            stream.seek(max(65536, stat.st_size-65536))
            h.update(stream.read(65536))
    return dict(path=str(path), bytes=stat.st_size, mtime_ns=stat.st_mtime_ns, edge_sha256=h.hexdigest())


class Queue:
    def __init__(self, data):
        self.data = Path(data).resolve()
        self.root = self.data / 'studies'
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'queue.sqlite'
        with closing(self.connect()) as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS studies (
                    id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, digest TEXT NOT NULL,
                    name TEXT NOT NULL, created REAL NOT NULL, parallel INTEGER NOT NULL, budget INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, study TEXT NOT NULL REFERENCES studies(id), name TEXT NOT NULL,
                    module INTEGER NOT NULL, parent TEXT, workers INTEGER NOT NULL, status TEXT NOT NULL,
                    attempt INTEGER NOT NULL DEFAULT 0, progress REAL NOT NULL DEFAULT 0, message TEXT NOT NULL DEFAULT '',
                    updated REAL NOT NULL, UNIQUE(study,name));
                CREATE TABLE IF NOT EXISTS activity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL, study TEXT, run TEXT, message TEXT NOT NULL);
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=20, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('pragma foreign_keys=ON')
        db.execute('pragma synchronous=FULL')
        return db

    def rows(self, sql, *args):
        with closing(self.connect()) as db:
            return [dict(r) for r in db.execute(sql, args)]

    def get_run(self, run):
        rows = self.rows('SELECT * FROM runs WHERE id=?', run)
        if not rows:
            raise ValueError('Unknown run ID.')
        return rows[0]

    def study(self, study):
        rows = self.rows('SELECT * FROM studies WHERE id=?', study)
        if not rows:
            raise ValueError('Unknown study ID.')
        return {**rows[0], 'runs': self.rows('SELECT * FROM runs WHERE study=? ORDER BY rowid', study)}

    def manifest(self, study):
        self.study(study)
        return json.loads((self.root/study/'manifest.json').read_bytes())

    def folder(self, run):
        return self.root/run['study']/run['id']/f"attempt-{run['attempt']:03d}"

    def event(self, message, study=None, run=None):
        with closing(self.connect()) as db:
            db.execute('INSERT INTO activity(at,study,run,message) VALUES(?,?,?,?)', (time.time(),study,run,message))

    def submit(self, spec, store):
        supplied = Study.model_validate(spec)
        signature = digest(supplied.model_dump())
        # Check the idempotency key before accessing any mutable external input.
        with closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT * FROM studies WHERE request_id=?', (supplied.request_id,)).fetchone()
            if previous:
                if previous['digest'] != signature:
                    raise ValueError('The request ID already belongs to a different study definition.')
                return self.study(previous['id'])
            study = uuid.uuid4().hex
            directory = self.root/study
            defaults = {1:store.profile, 2:store.module2, 3:store.module3}
            cap = cpu_settings()['recommended_threads']
            budget = min(supplied.cpu_budget or cap, os.cpu_count() or 1, 256)
            leaves=len(supplied.steps)-len({st.input_from for st in supplied.steps if st.input_from})
            auto_workers=max(1,budget//max(1,min(supplied.max_parallel,leaves)))
            runs, seen = [], {}
            for step in supplied.steps:
                if step.key in seen:
                    raise ValueError(f'Duplicate step key {step.key}.')
                parent = seen.get(step.input_from)
                if step.input_from is not None and (not parent or parent['module'] != step.module-1 or step.inputs or step.operation=='import'):
                    raise ValueError('input_from must refer to an earlier step of the preceding module and replaces external inputs.')
                if step.operation=='import' and step.module==3:
                    raise ValueError('Use run to analyze a pulse stream in Module 3.')
                profile = prepare_profile(step, defaults)
                paths = step.inputs or ([] if parent or step.module==1 else profile['input_paths'])
                if not parent:
                    limits = (1,2) if step.module==1 and step.operation=='import' else (1,1) if step.operation=='import' or step.module==3 else (2,2) if step.module==2 else (0,0)
                    if not limits[0]<=len(paths)<=limits[1] or any(not p.strip() for p in paths):
                        raise ValueError(f'Choose {limits[0]} to {limits[1]} input streams for {step.key}.')
                if len({q.name for q in step.queries})!=len(step.queries):
                    raise ValueError('Each saved query needs a distinct name.')
                workers = step.workers or auto_workers
                if workers>budget:
                    raise ValueError(f'{step.key} requests more CPUs than the study budget.')
                workers=min(workers,32 if step.module==3 else 256)
                item = dict(id=uuid.uuid4().hex, key=step.key, module=step.module, operation=step.operation,
                            parent=parent['id'] if parent else None, profile=profile,
                            inputs=[fingerprint(self.data/p) for p in paths], workers=workers,
                            queries=[q.model_dump() for q in step.queries])
                runs.append(item)
                seen[step.key]=item
            directory.mkdir()
            with closing(sqlite3.connect(store.database.path)) as src, closing(sqlite3.connect(directory/'catalogue.tpdb')) as dest:
                src.backup(dest)
            with (directory/'catalogue.tpdb').open('rb') as catalogue:
                catalogue_hash=hashlib.file_digest(catalogue,'sha256').hexdigest()
            manifest=dict(format='twinpals-study',version=1,application_version=__version__,mcp_version=VERSION,
                          id=study,name=supplied.name,objective=supplied.objective,request_id=supplied.request_id,
                          request_sha256=signature,catalogue_sha256=catalogue_hash,runtime=scientific_runtime(),
                          cpu_budget=budget,max_parallel=supplied.max_parallel,steps=runs)
            atomic_json(directory/'manifest.json',manifest)
            now=time.time()
            db.execute('INSERT INTO studies VALUES(?,?,?,?,?,?,?)',(study,supplied.request_id,signature,supplied.name,now,supplied.max_parallel,budget))
            for item in runs:
                db.execute('INSERT INTO runs(id,study,name,module,parent,workers,status,updated) VALUES(?,?,?,?,?,?,?,?)',
                           (item['id'],study,item['key'],item['module'],item['parent'],item['workers'],'queued',now))
            db.execute('INSERT INTO activity(at,study,message) VALUES(?,?,?)',(now,study,'Study submitted'))
            db.commit()
        return self.study(study)

