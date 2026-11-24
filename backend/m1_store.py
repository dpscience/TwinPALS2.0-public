# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Private automatic application state and reference-only Module 1 files."""
import copy
import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
import threading
import time
import uuid
from .instance import WorkspaceLock
from .m1_models import Profile, material_references
from .m3_models import Profile as LifetimeProfile
from pydantic import ValidationError
from .material_database import MaterialDatabase, CATEGORY_LABELS
from .view_settings import view_settings


class Conflict(ValueError):
    pass


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':'))


def read_json(path):
    path = Path(path)
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError('JSON file exceeds 64 MiB')
    return json.loads(path.read_text(encoding='utf-8-sig'), parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Non-finite JSON number')))


def atomic_json(path, value, overwrite=True):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(encode(value) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            # Windows readers/scanners may briefly deny replacement. Retry the
            # same atomic operation; never remove the destination as a fallback.
            for attempt,delay in enumerate((0,.02,.05,.1,.2)):
                if delay: time.sleep(delay)
                try:
                    os.replace(temporary, path)
                    break
                except PermissionError as exc:
                    if getattr(exc,'winerror',None) not in (5,32,33) or attempt==4:raise
        else:
            # Windows rename refuses an existing destination, including a race.
            if os.name == 'nt': temporary.rename(path)
            else:
                os.link(temporary, path)
                temporary.unlink()
    except FileExistsError as exc:
        raise Conflict('File already exists. Confirm replacement first.') from exc
    finally:
        temporary.unlink(missing_ok=True)


class ApplicationStore:
    def __init__(self, path, seed, catalogue_path=None):
        self.root=Path(path).resolve()
        self.lock=threading.RLock()
        self.folder_lock=WorkspaceLock(self.root)
        self.path=self.root/'app-state.json'
        self.client_sequences={}
        self.startup_notice=None
        try:
            self.database=MaterialDatabase(catalogue_path or self.root/'catalogue.tpdb',seed)
            from .photomultiplier import PulseCatalogue
            self.components=PulseCatalogue(self.database)
            if self.path.exists():
                try:
                    self._load()
                except ValueError:
                    # Private autosave is not an explicitly imported user file.
                    # Keep its exact bytes before replacing unsupported/damaged
                    # state. This is a fresh start, not an old-format adapter.
                    backup=self._backup_unreadable_state()
                    self._defaults()
                    self._write(backup_previous=False)
                    self.startup_notice={
                        'message':'The saved application settings could not be loaded by this version. TwinPALS started with the default setup and view settings. Your previous settings were saved unchanged in the backup below. Material entries and simulation files were not removed.',
                        'backup_path':str(backup),
                    }
                    logging.getLogger(__name__).warning('%s\nBackup: %s',self.startup_notice['message'],backup)
            else:
                self._defaults()
                self._write()
        except BaseException:
            self.folder_lock.close();raise

    @property
    def entries(self): return self.database.entries()

    def close(self): self.folder_lock.close()

    def _defaults(self):
        self.profile=Profile().model_dump(mode='json');self.ui=view_settings();self.revision=1
        from .m2_models import Profile as PulseProfile
        self.module2=PulseProfile().model_dump(mode='json');self.module3=LifetimeProfile().model_dump()

    def _load(self):
        value=read_json(self.path)
        if not isinstance(value,dict) or value.get('format')!='twinpals-private-state' or type(value.get('version')) is not int or value['version']!=4:
            raise ValueError('Unsupported private application state format')
        modules=value.get('modules')
        if (not isinstance(modules,dict) or set(modules)!={'module1','module2','module3'} or not isinstance(value.get('ui'),dict)
                or type(value.get('revision')) is not int or value['revision']<1):
            raise ValueError('Invalid private application state structure')
        self.profile=self.draft(modules['module1'])
        self.module2=self.pulse_draft(modules['module2']);self.module3=LifetimeProfile.from_saved(modules['module3']).model_dump()
        self.ui=view_settings(value['ui'])
        self.revision=value['revision']

    def _backup_unreadable_state(self):
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup=self.path.with_name(f'app-state.backup-{stamp}-{uuid.uuid4().hex[:8]}.json')
        # Never rename/delete the original before both a durable backup and
        # atomic replacement succeed. A permission/disk error must stop safely.
        with self.path.open('rb') as source,backup.open('xb') as target:
            shutil.copyfileobj(source,target)
            target.flush()
            os.fsync(target.fileno())
        return backup

    def resolve_path(self,value):
        path=Path(value).expanduser()
        return (path if path.is_absolute() else self.root/path).resolve()

    @staticmethod
    def pulse_draft(raw):
        from .m2_models import Profile as PulseProfile
        try: return PulseProfile.model_validate(raw).model_dump(mode='json')
        except ValidationError as exc:
            if any(e['type'] not in ('greater_than','greater_than_equal','less_than','less_than_equal') for e in exc.errors()): raise
            return copy.deepcopy(raw)

    @staticmethod
    def draft(raw):
        # In-progress numeric input is durable even when it is not valid for a run.
        # Types, enum choices, field names and the current format remain strict.
        try: return Profile.model_validate(raw).model_dump(mode='json')
        except ValidationError as exc:
            if any(e['type'] not in ('greater_than','greater_than_equal','less_than','less_than_equal') for e in exc.errors()): raise
            return copy.deepcopy(raw)

    def freeze(self,raw):
        if not isinstance(raw,dict) or raw.get('format')!='twinpals-module1-profile' or raw.get('version')!=8:
            raise ValueError('This M1 file uses an unsupported format. Load a current reference-only .tpm1 file or create a new setup.')
        profile=Profile.model_validate(raw).model_dump(mode='json')
        available={e['id']:e for e in self.entries}
        issues=[]
        for key,category,field in material_references(profile):
            entry=available.get(key)
            if entry is None: issues.append(f'{field}: material "{key}" is missing from the material database. Choose an available {CATEGORY_LABELS[category].lower()} entry or add that ID in Material database.')
            elif entry['category']!=category: issues.append(f'{field}: "{entry["name"]}" belongs to {CATEGORY_LABELS[entry["category"]]}, not {CATEGORY_LABELS[category]}. Choose an entry from the correct category.')
        if issues: raise ValueError('\n'.join(issues))
        if any(not p.strip() or not p.lower().endswith('.tpstream') for p in profile['run']['output_paths']):
            raise ValueError('Setup → Run → Binary output streams: choose two filenames ending in .tpstream.')
        if profile['run']['output_paths'][0].casefold()==profile['run']['output_paths'][1].casefold():
            raise ValueError('Setup → Run → Binary output streams: the two primary types need different filenames. Change one output name.')
        return profile

    def _write(self,backup_previous=True):
        if backup_previous and self.path.exists(): atomic_json(self.path.with_name('app-state.previous.json'),read_json(self.path))
        atomic_json(self.path,dict(format='twinpals-private-state',version=4,revision=self.revision,modules={'module1':self.profile,'module2':self.module2,'module3':self.module3},ui=self.ui))

    def save(self,raw,ui,client_id,sequence,module2=None,module3=None):
        if not isinstance(client_id,str) or not 1<=len(client_id)<=100 or type(sequence) is not int or sequence<1:
            raise ValueError('Invalid autosave request. Reload the application.')
        with self.lock:
            if sequence<=self.client_sequences.get(client_id,0): return {'revision':self.revision,'saved':False}
            profile=self.draft(raw);values=view_settings(ui)
            pulse=self.pulse_draft(self.module2 if module2 is None else module2)
            lifetime=LifetimeProfile.model_validate(self.module3 if module3 is None else module3).model_dump()
            if profile==self.profile and values==self.ui and pulse==self.module2 and lifetime==self.module3:
                self.client_sequences[client_id]=sequence
                return {'revision':self.revision,'saved':True}
            previous=(self.profile,self.ui,self.revision,self.module2,self.module3)
            self.profile,self.ui,self.revision=profile,values,self.revision+1
            self.module2=pulse;self.module3=lifetime
            try: self._write()
            except BaseException:
                self.profile,self.ui,self.revision,self.module2,self.module3=previous;raise
            self.client_sequences[client_id]=sequence
            return {'revision':self.revision,'saved':True}

    def inspect(self,raw): return {'profile':self.freeze(raw)}

    def inspect_app_profile(self,raw):
        if not isinstance(raw,dict) or raw.get('format')!='twinpals-app-profile' or raw.get('version')!=3 or not isinstance(raw.get('modules'),dict) or set(raw['modules'])!={'module1','module2','module3'} or not isinstance(raw.get('ui'),dict):
            raise ValueError('Choose a TwinPALS profile (.tpprofile). Module 1 settings and material databases use separate files.')
        profile=self.draft(raw['modules']['module1']); ui=view_settings(raw.get('ui'))
        entries={e['id']:e for e in self.entries}
        for key,category,field in material_references(profile):
            if key not in entries or entries[key]['category']!=category:
                raise ValueError(f'{field}: material “{key}” is not available in {CATEGORY_LABELS[category]}. Import its material database before loading this profile.')
        pulse=self.pulse_draft(raw['modules']['module2'])
        components={e['id']:e for e in self.components.entries()}
        for key,category in [(pulse['digitization']['digitizer_id'],'digitizer')]:
            if key not in components or components[key]['category']!=category:
                raise ValueError(f'Module 2 component "{key}" is missing. Import its component entry before loading this profile.')
        return {'format':'twinpals-app-profile','version':3,'modules':{'module1':profile,'module2':pulse,'module3':LifetimeProfile.from_saved(raw['modules']['module3']).model_dump()},'ui':ui}

    def app_profile(self):
        return {'format':'twinpals-app-profile','version':3,'modules':{'module1':copy.deepcopy(self.profile),'module2':copy.deepcopy(self.module2),'module3':copy.deepcopy(self.module3)},'ui':copy.deepcopy(self.ui)}

    def apply_app_profile(self,raw):
        with self.lock:
            value=self.inspect_app_profile(raw)
            previous=(self.profile,self.ui,self.revision,self.module2,self.module3)
            self.profile,self.ui,self.revision=value['modules']['module1'],value['ui'],self.revision+1
            self.module2=value['modules']['module2'];self.module3=value['modules']['module3']
            try:self._write()
            except BaseException:
                self.profile,self.ui,self.revision,self.module2,self.module3=previous;raise
            return value

    def put_entry(self,raw,expected_revision):
        with self.lock: return self.database.put(raw,expected_revision)

    def delete_entry(self,key,expected_revision):
        with self.lock:
            fields=[field for ref,_,field in material_references(self.profile) if ref==key]
            if key in [self.module2['digitization']['digitizer_id']]: fields.append('Module 2 Setup')
            if fields: raise ValueError('This material is selected in '+', '.join(fields)+'. Choose another material there before deleting it.')
            self.database.delete(key,expected_revision)
