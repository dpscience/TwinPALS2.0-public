# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Single-material files, shared only by physically compatible categories."""
import copy
import json
from .material_database import validated_entry, CatalogueConflict, CATEGORY_LABELS

FAMILIES = {
    'bulk': {'extension': '.tpmaterial', 'categories': ('sample', 'foil', 'shield')},
    'optical': {'extension': '.tpoptical', 'categories': ('coupling',)},
    'scintillator': {'extension': '.tpscint', 'categories': ('scintillator',)},
    'pmt': {'extension': '.tppmt', 'categories': ('pmt',)},
    'digitizer': {'extension': '.tpdigitizer', 'categories': ('digitizer',)},
    'wrapping': {'extension': '.tpwrap', 'categories': ('wrapping',)},
}

def family_for(category):
    for name, spec in FAMILIES.items():
        if category in spec['categories']: return name
    raise ValueError('Choose a material category before importing.')

def export_entry(database, identifier):
    item=next((e for e in database.entries() if e['id']==identifier),None)
    if item is None: raise ValueError('This material no longer exists. Select a saved entry.')
    return {'format':'twinpals-material-entry','version':1,'family':family_for(item['category']),'entry':item}

def signature(entry):
    return {k:v for k,v in entry.items() if k not in ('id','name','revision','builtin')}

def inspect_entry(database, raw, category, identifier=None):
    family=family_for(category)
    if not isinstance(raw,dict) or raw.get('format')!='twinpals-material-entry' or raw.get('version')!=1:
        raise ValueError('Choose a single-material export. A whole database, profile or numeric curve table cannot be imported here.')
    item=validated_entry(copy.deepcopy(raw.get('entry')))
    if raw.get('family')!=family_for(item['category']) or family!=raw['family']:
        raise ValueError(f'This file belongs to {CATEGORY_LABELS[item["category"]]}; it cannot be used as {CATEGORY_LABELS[category]}.')
    items={e['id']:e for e in database.entries()}
    original_id=item['id'];item['category']=category
    suggested=original_id
    if original_id in items and items[original_id]['category']!=category:
        stem=(category+'-'+original_id)[:90]
        suggested=stem
        suffix=2
        while suggested in items: suggested=f'{stem}-{suffix}';suffix+=1
    item['id']=identifier or suggested
    item=validated_entry(item)
    old=items.get(item['id'])
    if old and old['category']!=category:
        raise ValueError('This identifier belongs to another category. Choose a new identifier to create a separate entry here.')
    duplicates=[{'id':e['id'],'name':e['name']} for e in items.values() if e['category']==category and e['id']!=item['id'] and (e['name'].casefold().strip()==item['name'].casefold().strip() or signature(e)==signature(item))]
    unchanged=old and all(old[k]==item[k] for k in item if k not in ('revision','builtin'))
    return item, {'entry':item,'existing':'unchanged' if unchanged else 'different' if old else None,'duplicates':duplicates,'revision':database.revision}

def import_entry(database, raw, category, identifier, revision, replace=False):
    item, preview=inspect_entry(database,raw,category,identifier)
    with database.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT revision FROM metadata').fetchone()[0]!=revision:
            raise CatalogueConflict('The database changed after the preview. Preview the material again.')
        row=db.execute('SELECT payload FROM materials WHERE id=?',(item['id'],)).fetchone()
        if row and not replace: raise CatalogueConflict('This identifier already exists. Choose Replace explicitly or use a new identifier.')
        item['revision']=json.loads(row[0])['revision']+1 if row else 1
        item['builtin']=False
        db.execute('INSERT OR REPLACE INTO materials VALUES(?,?,?)',(item['id'],category,database.encode(item)))
        db.execute('UPDATE metadata SET revision=revision+1')
    return item
