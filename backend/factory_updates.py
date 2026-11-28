# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Apply each published catalogue delta once to the same SQLite database as the entries."""
from copy import deepcopy
import json

from .photocathode_film import missing_film

FILM = frozenset(('cathode_reflections', 'cathode_film_nm', 'cathode_n', 'cathode_k'))


def prepare(db):
    db.execute('CREATE TABLE IF NOT EXISTS factory_updates(release TEXT PRIMARY KEY)')
    db.execute('CREATE TABLE IF NOT EXISTS factory_optics_review(id TEXT PRIMARY KEY REFERENCES materials(id))')


def add_fields(row, source, properties, curves):
    """Only cite the values actually copied. Existing user references retain their indices."""
    added = set()
    for key in properties:
        if key not in row['properties']:
            row['properties'][key] = deepcopy(source['properties'][key])
            added.add(key)
    present = {c['name'] for c in row['curves']}
    source_curves = {c['name']: c for c in source['curves']}
    for key in curves:
        if key not in present:
            row['curves'].append(deepcopy(source_curves[key]))
            added.add(key)
    if not added:
        return added
    refs = row['provenance'].setdefault('references', [])
    for ref in source['provenance'].get('references', []):
        fields = [k for k in ref.get('properties', []) if k in added]
        if not fields:
            continue
        identity = {k: v for k, v in ref.items() if k != 'properties'}
        existing = next((r for r in refs if {k: v for k, v in r.items() if k != 'properties'} == identity), None)
        if existing is None:
            refs.append({**deepcopy(identity), 'properties': fields})
        else:
            keys = existing.setdefault('properties', [])
            keys.extend(k for k in fields if k not in keys)
    return added


def previously_sourced_film(row, source):
    # Before the release ledger, development builds wrote the factory film
    # and all its citations together. Surviving citations identify that bundle.
    def citations(entry):
        return {(r.get('url'), r.get('title'), k)
                for r in entry['provenance'].get('references', [])
                for k in r.get('properties', []) if k in FILM}

    sources = citations(source)
    return bool(sources) and sources <= citations(row)


def resolve_review(db, entry):
    if entry['category'] != 'pmt':
        return
    properties = entry['properties']
    curves = {c['name'] for c in entry['curves'] if len(c['points']) >= 2}
    if {'cathode_reflections', 'cathode_film_nm'} <= properties.keys() and {'cathode_n', 'cathode_k'} <= curves:
        db.execute('DELETE FROM factory_optics_review WHERE id=?', (entry['id'],))


def compatible_film(row, source):
    def identity(entry):
        p = entry['properties']
        qe = next((c for c in entry['curves'] if c['name'] == 'quantum_efficiency'), {})
        sheet = p.get('datasheet')
        material = sheet.get('Photocathode') if isinstance(sheet, dict) else sheet
        return (material, p.get('qe_reference_plane'),
                qe.get('x_unit'), qe.get('y_unit'), qe.get('points'))
    return identity(row) == identity(source)


def apply(db, releases, factory, validate, encode):
    prepare(db)
    changed = False
    for release in releases:
        version = release['release']
        if db.execute('SELECT 1 FROM factory_updates WHERE release=?', (version,)).fetchone():
            continue
        for key in release['introduced_ids']:
            if key not in factory:  # Retired in a subsequent release.
                continue
            source = factory[key]
            inserted = db.execute('INSERT OR IGNORE INTO materials VALUES(?,?,?)',
                                  (key, source['category'], encode(source)))
            changed |= inserted.rowcount == 1
        for group in release['additions']:
            for key in group['ids']:
                saved = db.execute('SELECT payload FROM materials WHERE id=?', (key,)).fetchone()
                if not saved or key not in factory:
                    continue
                source = factory[key]
                original = json.loads(saved[0])
                if original['category'] != source['category']:
                    continue
                row = deepcopy(original)
                props = [k for k in group['properties'] if k in source['properties']]
                present_curves = {c['name'] for c in source['curves']}
                curves = [k for k in group['curves'] if k in present_curves]
                add_fields(row, source, [k for k in props if k not in FILM], [k for k in curves if k not in FILM])
                candidate = deepcopy(row)
                film_props = [k for k in props if k in FILM]
                film_curves = [k for k in curves if k in FILM]
                if not original['builtin'] and previously_sourced_film(original, source):
                    # Preserve deliberate removals from an already delivered film bundle.
                    film_props, film_curves = [], []
                film_added = add_fields(candidate, source, film_props, film_curves)
                if film_added:
                    compatible = compatible_film(original, source) and not missing_film(candidate)
                    if compatible:
                        try:
                            validate(candidate, check_film_calibration=True)
                        except ValueError:
                            compatible = False
                    if compatible:
                        row = candidate
                    else:
                        db.execute('INSERT OR IGNORE INTO factory_optics_review VALUES(?)', (key,))
                elif ('cathode_reflections' in props and original['builtin']
                      and original['properties'].get('cathode_reflections') is False):
                    # The pre-release factory shipped complete films disabled. User saves clear builtin.
                    row['properties']['cathode_reflections'] = source['properties']['cathode_reflections']
                if row != original:
                    row['revision'] += 1
                    db.execute('UPDATE materials SET payload=? WHERE id=?', (encode(validate(row)), key))
                    changed = True
        db.execute('INSERT INTO factory_updates VALUES(?)', (version,))
    if changed:
        db.execute('UPDATE metadata SET revision=revision+1')
