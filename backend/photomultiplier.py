# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""One PMT owns its entrance optics, active surface, vacuum envelope and timing."""
import copy
import math

GEOMETRY_DEFAULTS = dict(window_shape='circle', window_diameter_mm=52., window_width_mm=40.,
    window_height_mm=40., window_thickness_mm=2., photocathode_shape='circle',
    photocathode_diameter_mm=46., photocathode_width_mm=40., photocathode_height_mm=40.,
    cathode_gap_mm=0., tube_diameter_mm=52., tube_length_mm=121.)


def geometry_fields(p):
    return tuple('tube_width_mm' if k == 'tube_diameter_mm' and p.get('tube_shape') == 'square' else k
                 for k in GEOMETRY_DEFAULTS)


def validate_pmt(entry):
    from .material_database import validated_entry
    from .analog_pmt import validate_response
    p = entry['properties']
    validate_response(p)
    if type(p.get('cathode_reflections',False)) is not bool:
        raise ValueError('Simulate photocathode reflections must be a checkbox.')
    if p.get('cathode_reflections') and 'cathode_film_nm' in p and (type(p['cathode_film_nm']) not in (int,float) or not 0 < p['cathode_film_nm'] < math.inf):
        raise ValueError('Cathode film thickness must be positive and finite.')
    if p.get('tube_shape', 'circle') not in ('circle', 'square'):
        raise ValueError('Photomultiplier → Package: choose cylindrical or square.')
    for key in geometry_fields(p):
        if key not in p: continue  # Draft entries may be incomplete.
        value = p[key]
        if key.endswith('_shape'):
            if value not in ('circle', 'rect'): raise ValueError(f'{key}: choose circular or rectangular.')
        elif isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0 or (key != 'cathode_gap_mm' and value == 0):
            raise ValueError(f'Photomultiplier → {key}: enter a valid positive dimension or nonnegative timing/gap.')
    if p.get('qe_reference_plane') not in ('external_tube', 'intrinsic_cathode'):
        raise ValueError('Photomultiplier → Photocathode: choose the quantum-efficiency reference plane.')
    if 'window_material' in p:
        if p['window_material'].get('category') != 'window': raise ValueError('The entrance window requires an optical glass entry.')
        p['window_material'] = validated_entry(p['window_material'])
    if all(key in p for key in geometry_fields(p)):
        square = p.get('tube_shape') == 'square'
        size = p['tube_width_mm'] if square else p['tube_diameter_mm']
        for prefix in ('window', 'photocathode'):
            span = p[prefix+'_diameter_mm']
            if p[prefix+'_shape'] == 'rect':
                w, h = p[prefix+'_width_mm'], p[prefix+'_height_mm']
                span = max(w, h) if square else math.hypot(w, h)
            if span > size + 1e-8:
                raise ValueError(f'Photomultiplier → {prefix.title()}: the aperture must fit inside the tube.')
        if p['tube_length_mm'] <= p['window_thickness_mm']+p['cathode_gap_mm']+.05:
            raise ValueError('Photomultiplier → Tube: increase the length to leave vacuum behind the window and cathode.')
    return entry


def component_entry(entry):
    """Project the shared catalogue into the pulse engine's parameter contract."""
    from .m2_models import Component
    raw = {k:copy.deepcopy(entry[k]) for k in ('id','name','category','revision','builtin','description')}
    raw['references'] = [{**{k:copy.deepcopy(r[k]) for k in ('title','url','comment') if k in r},'fields':r.get('properties',[])} for r in entry['provenance'].get('references',[])]
    if entry['category']=='digitizer': raw.update(copy.deepcopy(entry['properties']))
    else: raise ValueError('PMT response belongs to Module 1; Module 2 selects only an acquisition digitizer.')
    return Component.model_validate(raw).model_dump(mode='json')


class PulseCatalogue:
    """Read-only projection. All edits and exchanges use the single catalogue."""
    def __init__(self, database): self.database=database
    @property
    def path(self): return self.database.path
    @property
    def revision(self): return self.database.revision
    def entries(self): return [component_entry(e) for e in self.database.entries() if e['category']=='digitizer']
