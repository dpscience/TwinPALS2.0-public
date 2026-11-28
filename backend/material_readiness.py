# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Incomplete optical entries may be stored, but cannot drive transport."""
def missing_properties(entry):
    p, category = entry['properties'], entry['category']
    curves = {c['name'] for c in entry['curves']}
    missing = []
    if category in ('scintillator', 'coupling', 'window'):
        for curve, scalar, label in [('refractive_index','refractive_index','Refractive index'),
                                      ('absorption_length','absorption_length_mm','Absorption length')]:
            if curve not in curves and scalar not in p: missing.append(label)
    if category == 'scintillator':
        if not p.get('light_yield_per_MeV'): missing.append('Light yield')
        components = p.get('components', [])
        if not components or any(c.get('curve') not in curves for c in components): missing.append('Emission spectrum')
        if any(c.get('rise_time_ns') is None or c.get('decay_time_ns') is None for c in components): missing.append('Rise / decay time')
    if category == 'pmt' and 'quantum_efficiency' not in curves: missing.append('Quantum efficiency')
    if category == 'pmt':
        from .photocathode_film import missing_film
        missing.extend(missing_film(entry))
        from .photomultiplier import geometry_fields
        from .analog_pmt import RESPONSE_FIELDS
        for key in (*geometry_fields(p), *RESPONSE_FIELDS):
            if key not in p: missing.append(key.replace('_',' '))
        if 'gain_hv' not in curves and not p.get('gain_exponent'): missing.append('Gain versus HV')
        if not p.get('window_material'): missing.append('Window glass')
        else: missing += ['Window: '+v for v in missing_properties(p['window_material'])]
    return missing

