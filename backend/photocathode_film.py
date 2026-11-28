# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Calibrate photoemission to the reference plane of the tube's measured QE."""
import numpy as np

FIELDS = {
    'cathode_film_nm': 'Cathode film thickness',
    'cathode_n': 'Cathode refractive index n',
    'cathode_k': 'Cathode extinction coefficient k',
}


def missing_film(entry):
    p = entry['properties']
    if not p.get('cathode_reflections'):
        return []
    curves = {c['name'] for c in entry['curves'] if len(c['points']) >= 2}
    sourced = {key for ref in entry['provenance'].get('references', []) for key in ref.get('properties', [])}
    missing = []
    for key, label in FIELDS.items():
        if key not in (p if key == 'cathode_film_nm' else curves):
            missing.append(label)
        if key not in sourced:
            missing.append(label + ' reference')
    if {'cathode_n','cathode_k'} <= curves:
        bounds = []
        for c in entry['curves']:
            if c['name'] in ('cathode_n','cathode_k') and c['points']:
                x = [v for v,_ in c['points'] if v > 0]
                if x:
                    from .m1_resolve import HC_EV_NM
                    nm = x if c['x_unit']=='nm' else [HC_EV_NM/v for v in x]
                    bounds.append((min(nm),max(nm)))
        if len(bounds)==2 and max(lo for lo,_ in bounds)>=min(hi for _,hi in bounds):
            missing.append('Overlapping cathode n and k spectral range')
    return missing


def resolve_film(entry, window, qe):
    from .m1_resolve import HC_EV_NM, optical_curve
    p = entry['properties']
    curves = {c['name']: optical_curve(c) for c in entry['curves'] if c['name'] in ('cathode_n','cathode_k')}
    lower = max(rows[0][0] for rows in curves.values())
    upper = min(rows[-1][0] for rows in curves.values())
    if lower >= upper:
        raise ValueError('Photocathode n and k need an overlapping spectral range.')
    # Include glass and QE knots. Refine in between to resolve the film phase.
    inputs = [qe, *curves.values(), window['refractive_index'], window['absorption_length_mm']]
    knots = np.unique([x for rows in inputs if isinstance(rows,list) for x,_ in rows] + [lower, upper])
    energies = np.unique(np.concatenate([knots, np.linspace(lower, upper, 1025), np.linspace(knots[0], knots[-1], 1025)]))
    def interpolate(rows):
        return np.interp(energies, *np.transpose(rows)) if isinstance(rows, list) else rows
    glass = interpolate(window['refractive_index'])
    gap = p['cathode_gap_mm'] > 0
    incident = 1. if gap else glass
    nk = interpolate(curves['cathode_n']) + 1j*interpolate(curves['cathode_k'])
    rho01, rho12 = (incident-nk)/(incident+nk), (nk-1)/(nk+1)
    phase = np.exp(2j*np.pi*nk*p['cathode_film_nm']*energies/HC_EV_NM)
    denom = 1+rho01*rho12*phase**2
    reflect = abs((rho01+rho12*phase**2)/denom)**2
    transmit = abs((1+rho01)*(1+rho12)*phase/denom)**2/incident
    absorb = np.maximum(0.,1-reflect-transmit)
    target = np.interp(energies,*np.transpose(qe),left=0.,right=0.)
    # Outside the common measured band the cathode uses the QE-only boundary.
    inside = (energies >= lower) & (energies <= upper)
    absorb_ref = np.where(inside,absorb,1.)
    reflect_ref = np.where(inside,reflect,0.)
    if p['qe_reference_plane'] == 'external_tube':
        fresnel = ((glass-1)/(glass+1))**2
        bulk = np.exp(-p['window_thickness_mm']/interpolate(window['absorption_length_mm']))
        forward = (1-fresnel)*bulk
        reverse = fresnel*bulk**2
        if gap:
            forward, reverse = (forward*(1-fresnel)/(1-fresnel*reverse),
                                fresnel+(1-fresnel)**2*reverse/(1-fresnel*reverse))
        absorb_ref = forward*absorb_ref/(1-reverse*reflect_ref)
    def probability(mask, denominator):
        required = target[mask]
        available = np.broadcast_to(denominator,energies.shape)[mask]
        bad = required > available + 1.e-10
        if np.any(bad):
            at = np.flatnonzero(bad)[0]
            raise ValueError(f"{entry['name']}: QE {required[at]:.1%} exceeds reference absorption "
                             f"{available[at]:.1%} at {HC_EV_NM/energies[mask][at]:.1f} nm. Check film and window data.")
        return np.clip(np.divide(required,available,out=np.zeros_like(required),where=available>0),0,1)
    # Separate tables avoid interpolating across the change of boundary model at a band edge.
    escape = probability(inside,absorb_ref)
    outside_ref = forward if p['qe_reference_plane']=='external_tube' else 1.
    fallback = probability(np.ones(len(energies), dtype=bool),outside_ref)
    return dict(n=curves['cathode_n'],k=curves['cathode_k'],thickness_nm=p['cathode_film_nm'],
                escape=np.column_stack((energies[inside],escape)).tolist(),
                fallback=np.column_stack((energies,fallback)).tolist(),
                normal=[[float(HC_EV_NM/e),float(r),float(a),float(t)] for e,r,a,t in
                        zip(energies[inside][::-1],reflect[inside][::-1],absorb[inside][::-1],transmit[inside][::-1])])


def normal_incidence_plot(entry):
    from .m1_resolve import optical_curve
    p = entry['properties']
    if entry['category'] != 'pmt' or not p.get('cathode_reflections') or missing_film(entry):
        raise ValueError('Select a PMT with complete cathode film data.')
    glass = p.get('window_material')
    if not glass or not any(c['name']=='quantum_efficiency' for c in entry['curves']):
        raise ValueError('Window optics and a QE curve are required to calculate the film response.')
    window = dict(glass['properties'])
    for c in glass['curves']:
        if c['name'] in ('absorption_length','refractive_index'):
            key = 'absorption_length_mm' if c['name']=='absorption_length' else c['name']
            window[key] = optical_curve(c)
    if not all(key in window for key in ('absorption_length_mm','refractive_index')) or not all(
            key in p for key in ('window_thickness_mm','qe_reference_plane','cathode_gap_mm')):
        raise ValueError('Complete the PMT window, gap and QE reference plane first.')
    qe = next(c for c in entry['curves'] if c['name']=='quantum_efficiency')
    return resolve_film(entry,window,optical_curve(qe))['normal']
