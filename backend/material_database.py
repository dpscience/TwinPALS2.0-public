# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""One SQLite database, with validated, atomic material-catalogue exchange."""
import copy
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit
from . import factory_updates
from .models import Entry
from .composition import validate_composition
from .standard_materials import standard_catalogue

CATEGORY_LABELS={'scintillator':'Scintillators','coupling':'Coupling','window':'Windows',
    'pmt':'Photomultipliers','digitizer':'Digitizers','wrapping':'Wrapping','sample':'Sample materials',
    'foil':'Encapsulation foils','shield':'Shielding materials'}
APPLICATION_ID=0x54504442

class InvalidCatalogue(ValueError):
    """A local database cannot be read by the current application."""

class CatalogueConflict(ValueError):
    pass

def catalogue_entry(raw, *, check_film_calibration=False):
    entry=validated_entry(raw)
    if check_film_calibration and entry['category']=='pmt' and entry['properties'].get('cathode_reflections'):
        from .material_readiness import missing_properties
        from .photocathode_film import normal_incidence_plot
        if not missing_properties(entry):
            normal_incidence_plot(entry)
    if entry['category']=='window':
        raise ValueError('Define the entrance-window material and curves inside its photomultiplier. Standalone window presets are not supported.')
    return entry


def validated_entry(raw):
    entry=Entry.model_validate(raw).model_dump(mode='json')
    p=entry['properties']; category=entry['category']; curves={c['name']:c for c in entry['curves']}
    references=entry['provenance'].get('references',[])
    if not isinstance(references,list): raise ValueError('References: use a list of sources.')
    for ref in references:
        if not isinstance(ref,dict) or not isinstance(ref.get('title'),str) or not ref['title'].strip(): raise ValueError('References: each source needs a title.')
        url=ref.get('url',''); parsed=urlsplit(url) if isinstance(url,str) else None
        # A named local measurement can document an optical film without a public URL.
        local_film = (category=='pmt' and url=='' and isinstance(ref.get('properties'),list)
                      and bool(ref['properties']) and all(k in ('cathode_film_nm','cathode_n','cathode_k') for k in ref['properties']))
        if not local_film and (not parsed or parsed.scheme not in ('https','http') or not parsed.hostname or parsed.username or parsed.password):
            raise ValueError('References: enter a full http or https source URL.')
        if not isinstance(ref.get('properties',[]),list) or any(not isinstance(v,str) for v in ref.get('properties',[])): raise ValueError('References: select the properties supported by each source.')
        if not isinstance(ref.get('comment',''),str) or len(ref.get('comment',''))>4000: raise ValueError('Reference comments must be text of at most 4,000 characters.')
    if category not in ('pmt','digitizer'):
        validate_composition(p)
        if p.get('nist_material'):
            standard=standard_catalogue()[p['nist_material']];atomic=standard.get('atomic_composition',{})
            p.update(density_g_cm3=standard['density_g_cm3'],composition=copy.deepcopy(atomic or standard['composition']),composition_basis='atoms' if atomic else 'mass_fraction')
        if not p.get('nist_material') and not 0<float(p.get('density_g_cm3',0))<=100:
            raise ValueError('Composition → Density: enter a value greater than zero and at most 100 g/cm³.')
    allowed={'refractive_index','absorption_length'} if category in ('scintillator','coupling','window') else {'quantum_efficiency','gain_hv','cathode_n','cathode_k'} if category=='pmt' else {'reflectivity'} if category=='wrapping' else set()
    for name in curves:
        if name not in allowed and not (category=='scintillator' and name.startswith('emission')):
            raise ValueError(f'{CATEGORY_LABELS[category]} cannot use a “{name}” curve. Select a curve belonging to this material category.')
    if category=='scintillator':
        if 'light_yield_per_MeV' in p and not 0<p['light_yield_per_MeV']<=200000: raise ValueError('Emission → Light yield: enter a positive value up to 200,000 photons/MeV.')
        components=p.get('components',[])
        if components and abs(sum(c['fraction'] for c in components)-1)>1e-6: raise ValueError('Emission: component fractions must add up to 1 (100%).')
        if any(not c['curve'].startswith('emission') or not 0<=c['fraction']<=1 or c['rise_time_ns']<0 or c['decay_time_ns']<=0 for c in components):
            raise ValueError('Emission: each component needs an emission spectrum, fraction from 0 to 1, nonnegative rise time and positive decay time.')
    if category=='digitizer':
        from .photomultiplier import component_entry
        component_entry(entry)
    if category in ('sample','foil','shield'):
        from .material_lifetimes import validate_lifetimes
        validate_lifetimes(p)
    if category=='pmt':
        from .photomultiplier import validate_pmt
        validate_pmt(entry)
        if p.get('qe_reference_plane') not in ('external_tube','intrinsic_cathode'): raise ValueError('Photocathode: choose whether QE is measured for the complete tube or at the cathode surface.')
    if category=='wrapping':
        if p.get('model') not in ('lut','unified'): raise ValueError('Wrapping: choose the measured PTFE table or the unified surface model.')
        if p['model']=='lut' and p.get('finish')!='polishedteflonair': raise ValueError('The measured PTFE model requires the polished PTFE / air finish.')
    return entry


class MaterialDatabase:
    def __init__(self,path,seed):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        data=json.loads(Path(seed).read_text(encoding='utf-8-sig'))
        if data.get('format')!='twinpals-catalogue-seed' or data.get('version')!=2:
            raise ValueError('The bundled factory catalogue is invalid.')
        entries=[catalogue_entry(raw) for raw in data['items']]
        if len({e['id'] for e in entries})!=len(entries):
            raise ValueError('The bundled factory catalogue has duplicate identifiers.')
        releases=data.get('factory_updates',[])
        factory={e['id']:e for e in entries}
        self.factory_pmts={key:e for key,e in factory.items() if e['category']=='pmt'}
        if not self.path.exists():
            target=self.path
            self.path=target.with_name(target.name+'.'+uuid.uuid4().hex+'.tmp')
            try:
                with self.connect() as db:
                    categories=','.join(repr(c) for c in CATEGORY_LABELS if c!='window')
                    db.executescript(f'PRAGMA application_id={APPLICATION_ID}; PRAGMA user_version=2; CREATE TABLE materials(id TEXT PRIMARY KEY, category TEXT NOT NULL CHECK(category IN ({categories})), payload TEXT NOT NULL); CREATE TABLE metadata(revision INTEGER NOT NULL); INSERT INTO metadata VALUES(1);')
                    db.executemany('INSERT INTO materials VALUES(?,?,?)',[(e['id'],e['category'],self.encode(e)) for e in entries])
                    factory_updates.prepare(db)
                    db.executemany('INSERT INTO factory_updates VALUES(?)',[(r['release'],) for r in releases])
                # The desktop and MCP service can initialize the same catalogue.
                # Publish a complete file only if no other process arrived first.
                try:
                    if os.name == 'nt':
                        self.path.rename(target)
                    else:
                        os.link(self.path, target)
                except FileExistsError:
                    pass
            finally:
                self.path.unlink(missing_ok=True)
                self.path=target
        with self.connect() as db:
            if db.execute('PRAGMA application_id').fetchone()[0]!=APPLICATION_ID or db.execute('PRAGMA user_version').fetchone()[0]!=2:
                raise ValueError('This is not a supported TwinPALS database. Close TwinPALS and place a current catalogue.tpdb in its data folder.')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            factory_updates.apply(db,releases,factory,catalogue_entry,self.encode)
        self.entries()  # Reject invalid externally replaced databases before use.

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=10)
        try:
            with db: yield db
        finally: db.close()

    @staticmethod
    def encode(value): return json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':'))

    @property
    def revision(self):
        with self.connect() as db: return db.execute('SELECT revision FROM metadata').fetchone()[0]

    def entries(self):
        with self.connect() as db:
            result=[]
            for key,category,payload in db.execute('SELECT id,category,payload FROM materials ORDER BY category,id'):
                try:
                    entry=catalogue_entry(json.loads(payload))
                except ValueError as exc:
                    raise InvalidCatalogue(
                        f'The database entry "{key}" ({CATEGORY_LABELS.get(category, category)}) '
                        f'is invalid or uses an older format.\nDatabase: {self.path.resolve()}\n'
                        'Keep a backup and use a catalogue matching this application version. '
                        'The database and simulation files have not been changed.'
                    ) from exc
                if entry['id']!=key or entry['category']!=category: raise ValueError('The database has inconsistent entry identifiers or categories.')
                result.append(entry)
            return result

    def put(self,raw,expected_revision=None):
        entry=catalogue_entry(copy.deepcopy(raw),check_film_calibration=True)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT category,payload FROM materials WHERE id=?',(entry['id'],)).fetchone()
            if old:
                if old[0]!=entry['category']: raise ValueError('An existing entry cannot move to another category. Create a new entry in the intended category.')
                original=json.loads(old[1])
                if expected_revision!=original['revision']: raise ValueError('This material was changed in another editor. Reopen it before saving your changes.')
                entry['revision']=original['revision']+1
            else:
                if expected_revision is not None: raise ValueError('This material no longer exists. Create it as a new entry.')
                entry['revision']=1
            factory_updates.resolve_review(db,entry)
            entry['builtin']=False
            db.execute('INSERT OR REPLACE INTO materials VALUES(?,?,?)',(entry['id'],entry['category'],self.encode(entry)))
            db.execute('UPDATE metadata SET revision=revision+1')
        return entry

    def delete(self,key,expected_revision):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT payload FROM materials WHERE id=?',(key,)).fetchone()
            if not old: raise ValueError('This material no longer exists. Refresh the material list.')
            if json.loads(old[0])['revision']!=expected_revision: raise ValueError('This material changed in another editor. Reopen it before deleting it.')
            db.execute('DELETE FROM factory_optics_review WHERE id=?',(key,))
            db.execute('DELETE FROM materials WHERE id=?',(key,));db.execute('UPDATE metadata SET revision=revision+1')

    def factory_optics(self,key,draft=None):
        with self.connect() as db:
            pending=db.execute('SELECT 1 FROM factory_optics_review WHERE id=?',(key,)).fetchone()
        source=self.factory_pmts.get(key)
        if not pending or source is None:
            return {'available':False}
        result={'available':True,'model':source['name'],'thickness_nm':source['properties']['cathode_film_nm']}
        if draft is not None:
            if draft.get('id')!=key or draft.get('category')!='pmt':
                raise ValueError('Choose the matching factory photomultiplier.')
            entry=copy.deepcopy(draft)
            added=factory_updates.add_fields(entry,source,['cathode_reflections','cathode_film_nm'],['cathode_n','cathode_k'])
            if 'cathode_reflections' in added:
                entry['properties']['cathode_reflections']=False
            result['entry']=entry
        return result

    def export_catalogue(self):
        return {'format':'twinpals-catalogue','version':1,'entries':self.entries()}

    def inspect_catalogue(self,raw):
        if not isinstance(raw,dict) or raw.get('format')!='twinpals-catalogue' or raw.get('version')!=1 or not isinstance(raw.get('entries'),list):
            raise ValueError('Choose a TwinPALS database export (.tpcatalogue). M1 settings and streams cannot be imported here.')
        if not 1<=len(raw['entries'])<=10000: raise ValueError('A material catalogue must contain between 1 and 10,000 entries.')
        incoming=[catalogue_entry(item,check_film_calibration=True) for item in raw['entries']]
        if len({e['id'] for e in incoming})!=len(incoming): raise ValueError('This catalogue contains duplicate material identifiers. Each identifier must be unique.')
        existing={e['id']:e for e in self.entries()}
        groups={'added':[],'conflicts':[],'unchanged':[]}
        for item in incoming:
            old=existing.get(item['id'])
            if old and old['category']!=item['category']: raise ValueError(f'“{item["name"]}” ({item["id"]}) belongs to another category in this database. Use a different identifier before importing.')
            semantic=lambda e:{k:v for k,v in e.items() if k not in ('revision','builtin')}
            key='added' if old is None else 'unchanged' if semantic(old)==semantic(item) else 'conflicts'
            groups[key].append({'id':item['id'],'name':item['name'],'category':item['category']})
        return incoming,groups

    def import_catalogue(self,raw,expected_revision,replace_existing=False):
        incoming,groups=self.inspect_catalogue(raw)
        chosen={e['id'] for e in groups['added']+(groups['conflicts'] if replace_existing else [])}
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT revision FROM metadata').fetchone()[0]!=expected_revision:
                raise CatalogueConflict('The database changed after the preview. Preview the import again before applying it.')
            for item in incoming:
                if item['id'] not in chosen: continue
                old=db.execute('SELECT payload FROM materials WHERE id=?',(item['id'],)).fetchone()
                item['revision']=json.loads(old[0])['revision']+1 if old else 1
                factory_updates.resolve_review(db,item)
                item['builtin']=False
                db.execute('INSERT OR REPLACE INTO materials VALUES(?,?,?)',(item['id'],item['category'],self.encode(item)))
            if chosen: db.execute('UPDATE metadata SET revision=revision+1')
        return len(chosen)
