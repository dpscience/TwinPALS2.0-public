# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""One explicit optical-unit and geometry conversion shared by preview and worker."""
import copy
import math
from .m1_models import Profile
from .execution import resolve_threads
from .physics import source_profiles
from .material_readiness import missing_properties
from .analog_pmt import operating_point

HC_EV_NM = 1239.8419843320026
LENGTH_MM = {'nm':1e-6, 'um':.001, 'µm':.001, 'μm':.001, 'mm':1., 'cm':10., 'm':1000.}


def optical_curve(curve, emission=False, interpretation=None):
    """Return increasing eV. Only photon-density emissions are area-normalized."""
    xunit, yunit, name = curve['x_unit'], curve['y_unit'], curve['name']
    points_in = curve['points']
    if len(points_in)<2 or any(len(p)!=2 or not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in p) or p[0]<=0 for p in points_in):
        raise ValueError('Optical curves need at least two finite points with positive x')
    if any(b[0]<=a[0] for a,b in zip(points_in,points_in[1:])): raise ValueError('Optical curve x values must strictly increase')
    if emission and (yunit not in ('1','relative','1/eV','1/nm') or any(y<0 for x,y in points_in)):
        raise ValueError('Emission requires nonnegative photon-density or declared relative values')
    if xunit not in ('nm', 'eV'): raise ValueError(f'{name}: optical axis must be nm or eV')
    factor = 1.
    if name in ('quantum_efficiency','reflectivity','transmittance'):
        if yunit not in ('1','probability','%','percent'): raise ValueError('Probability requires 1 or %')
        factor = .01 if yunit in ('%','percent') else 1.
        if any(not 0<=y*factor<=1 for x,y in points_in): raise ValueError('Probability must lie in [0,1]')
    elif name == 'absorption_length':
        if yunit not in LENGTH_MM: raise ValueError('Unsupported absorption-length unit')
        factor = LENGTH_MM[yunit]
        if any(y<=0 for x,y in points_in): raise ValueError('Absorption length must be positive')
    density_nm = emission and (yunit == '1/nm' or (yunit in ('1','relative') and interpretation == 'photon_density_per_wavelength'))
    if density_nm and xunit != 'nm': raise ValueError('Wavelength photon density requires nm axis')
    if emission and yunit == '1/eV' and xunit != 'eV': raise ValueError('Energy photon density requires eV axis')
    if emission and yunit in ('1','relative') and interpretation not in ('photon_density_per_wavelength','relative_energy_weights'):
        raise ValueError('Declare how the relative emission ordinate represents photon number')
    points = []
    for x,y in curve['points']:
        energy = HC_EV_NM / x if xunit == 'nm' else x
        value = y * factor * (x*x/HC_EV_NM if density_nm else 1.)
        points.append([energy,value])
    points.sort()
    if emission:
        area = sum((b[0]-a[0])*(a[1]+b[1])/2 for a,b in zip(points,points[1:]))
        if area <= 0 or not math.isfinite(area): raise ValueError('Emission has no finite positive area')
        points = [[x,y/area] for x,y in points]
    return points


def axis(azimuth, tilt=0):
    a,t = math.radians(azimuth),math.radians(tilt)
    return [math.cos(t)*math.cos(a),math.cos(t)*math.sin(a),math.sin(t)]


def scale(v,s): return [x*s for x in v]
def add(a,b): return [x+y for x,y in zip(a,b)]
def dot(a,b): return sum(x*y for x,y in zip(a,b))
def cross(a,b): return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
def unit(v):
    length = math.sqrt(dot(v,v))
    if length < 1e-12: raise ValueError('Geometry axis must not be zero')
    return scale(v,1/length)


def frame(z):
    # Native rotationFor uses this same up vector, including its pole fallback.
    up = [0,1,0] if abs(z[1]) < .9999 else [1,0,0]
    x = unit(cross(up,z))
    return x,cross(z,x),z


def transform_vector(v, basis):
    return [sum(v[j]*basis[j][i] for j in range(3)) for i in range(3)]


def resolve_profile(raw, materials):
    profile = Profile.model_validate(raw).model_dump(mode='json')
    entries = {e['id']:e for e in materials}
    warnings = []
    def get(key, categories):
        entry = entries.get(key)
        if not entry or entry['category'] not in categories: raise ValueError(f'Missing {"/".join(categories)} entry: {key}')
        missing = missing_properties(entry)
        if missing: raise ValueError(f'{entry["name"]}: incomplete material. Add {", ".join(missing)} in Material database before simulation.')
        return entry
    def curve(entry,name,emission=False):
        item = next((c for c in entry['curves'] if c['name'] == name),None)
        if item is None: raise ValueError(f'{entry["name"]}: missing {name} curve')
        return optical_curve(item,emission,entry['properties'].get('spectral_interpretation'))
    def bulk(entry):
        props = entry['properties']
        if 'nist_material' in props: return {'nist_material':props['nist_material']}
        composition = props.get('composition',{})
        density = props.get('density_g_cm3',0)
        if not 0 < density <= 100 or not composition or any(not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) or v<=0 for v in composition.values()):
            raise ValueError(f'{entry["name"]}: positive density and composition are required')
        basis = props.get('composition_basis','atoms')
        if basis not in ('atoms','mass_fraction'): raise ValueError('Composition basis must be atoms or mass_fraction')
        return {'density_g_cm3':density,'composition':copy.deepcopy(composition),'composition_basis':basis}
    def optical(entry):
        props = entry['properties']; result = bulk(entry)
        curves = {c['name'] for c in entry['curves']}
        for name,output in [('refractive_index','refractive_index'),('absorption_length','absorption_length_mm')]:
            if name in curves: result[output] = curve(entry,name)
            elif output in props: result[output] = props[output]
        if 'refractive_index' not in result: raise ValueError(f'{entry["name"]}: refractive index is required')
        if 'absorption_length_mm' not in result:
            raise ValueError(f'{entry["name"]}: optical absorption is not specified. Open Material database → {entry["name"]} → Optical properties and supply a justified absorption length or curve before running. The reference data alone do not define a complete optical transport model.')
        return result
    def coverage(entry, material, domain):
        for key in ('refractive_index','absorption_length_mm'):
            values = material.get(key)
            if isinstance(values,list) and (values[0][0] > domain[0] or values[-1][0] < domain[1]):
                if entry['properties'].get('optical_extrapolation') != 'constant':
                    raise ValueError(f'{entry["name"]}: {key} does not cover the emission range')
    detectors=[]
    for d in profile['detectors']:
        scint = get(d['scintillator_id'],['scintillator']); props = scint['properties']
        material = optical(scint)
        for key in ('light_yield_per_MeV','resolution_scale'):
            if key not in props: raise ValueError(scint['name'] + ': missing ' + key)
            material[key] = props[key]
        if not 0 < material['light_yield_per_MeV'] <= 200000: raise ValueError('Light yield must be 0..200000 photons/MeV')
        if 'birks_mm_per_MeV' in props: material['birks_mm_per_MeV'] = props['birks_mm_per_MeV']
        components=props['components']
        if not 1 <= len(components) <= 3: raise ValueError('Geant4 accepts one to three scintillation components')
        material['components']=[]
        for c in components:
            fraction,rise,decay=c.get('fraction'),c.get('rise_time_ns'),c.get('decay_time_ns')
            if any(not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) for v in (fraction,rise,decay)) or not 0<=fraction<=1 or rise<0 or decay<=0:
                raise ValueError(scint['name'] + ': invalid component fraction/rise/decay')
            material['components'].append({'name':c.get('name',c['curve']),'fraction':fraction,'rise_time_ns':rise,'decay_time_ns':decay,'emission':curve(scint,c['curve'],True)})
        if not math.isclose(sum(c['fraction'] for c in material['components']),1,abs_tol=1e-6): raise ValueError('Component photon fractions must sum to one')
        domain=[min(c['emission'][0][0] for c in material['components']),max(c['emission'][-1][0] for c in material['components'])]
        coverage(scint,material,domain)
        sensor=get(d['pmt_id'],['pmt']); pp=sensor['properties']; qe=curve(sensor,'quantum_efficiency')
        reference=sensor['properties'].get('qe_reference_plane')
        if reference not in ('external_tube','intrinsic_cathode'): raise ValueError(sensor['name'] + ': declare the QE reference plane')
        coupling_entry=get(d['coupling_id'],['coupling']); coupling=optical(coupling_entry)
        window_entry=pp['window_material']; window=optical(window_entry)
        if reference == 'external_tube':
            window.pop('absorption_length_mm',None)
            window['bulk_attenuation_disabled_for_external_qe']=True
            if pp['window_thickness_mm']>0:
                warnings.append(f'Detector {d["id"]} → Photocathode: {sensor["name"]} uses complete-PMT QE, which already includes window losses. Separate window bulk absorption is disabled; interface optics still apply. Select the matching window glass. Use intrinsic-cathode QE to model window absorption explicitly.')
        coverage(coupling_entry,coupling,domain); coverage(window_entry,window,domain)
        coupling['thickness_mm']=d['coupling_mm']; window['thickness_mm']=pp['window_thickness_mm']
        aperture=lambda prefix: ({'shape':'circle','diameter_mm':pp[prefix+'_diameter_mm']} if pp[prefix+'_shape']=='circle'
                                 else {'shape':'rect','width_mm':pp[prefix+'_width_mm'],'height_mm':pp[prefix+'_height_mm']})
        window.update(aperture('window'))
        surface_entry=get(d['surface_id'],['wrapping']); sp=surface_entry['properties']; model=sp.get('model')
        if model not in ('lut','unified'): raise ValueError('Surface model must be lut or unified')
        surface={'enabled':d['wrapping']['enabled'],'thickness_mm':d['wrapping']['side_mm'],'front_thickness_mm':d['wrapping']['front_mm'],'model':model,'finish':sp.get('finish','ground')}
        if model=='lut' and surface['finish']!='polishedteflonair': raise ValueError('Supported LUT finish is polishedteflonair')
        if model=='unified':
            surface['reflectivity']=curve(surface_entry,'reflectivity') if any(c['name']=='reflectivity' for c in surface_entry['curves']) else sp.get('reflectivity',.98)
            surface['sigma_alpha_rad']=sp.get('sigma_alpha_rad',.1)
        if sp.get('nist_material') or sp.get('composition'): surface['material']=bulk(surface_entry)
        front=[d['distance_mm']*math.cos(math.radians(d['azimuth_deg'])),d['distance_mm']*math.sin(math.radians(d['azimuth_deg'])),d['vertical_offset_mm']]
        direction=axis(d['azimuth_deg'],d['tilt_deg'])
        detectors.append({'id':d['id'],'shape':d['shape'],'dimensions':d['dimensions'],'front_mm':front,'axis':direction,'up':[0,1,0],
                          'material':material,'sensor':{'qe':qe,**aperture('photocathode'),'qe_reference_plane':reference},'coupling':coupling,'window':window,'surface':surface,'pmt':{k:pp[k] for k in ('cathode_gap_mm','tube_shape','tube_diameter_mm','tube_width_mm','tube_length_mm') if k in pp}})
    sg=profile['source_geometry']; assembly=profile['assembly']; saxis=axis(assembly['azimuth_deg'],assembly['tilt_deg'])
    source_geometry={'position_mm':[0,0,0],'axis':saxis,'radius_mm':sg['radius_mm'],'thickness_mm':sg['thickness_mm']}
    blocks=[]; sample=profile['sample']
    foil=sample['foil_thickness_mm'] if sample['foil_enabled'] else 0
    gap_half=sg['thickness_mm']/2
    for side,sign in [('left',-1),('right',1)]:
        shape=sample[side]
        if sample['enabled'] and shape['thickness_mm']>0:
            aperture=shape['diameter_mm']/2 if shape['shape']=='cylinder' else min(shape['width_mm'],shape['height_mm'])/2
            if sg['radius_mm']>aperture: raise ValueError(f'Source radius exceeds {side} sample aperture')
            t=shape['thickness_mm']
            blocks.append({'id':side+'_sample','enabled':True,**{k:shape[k] for k in ('shape','width_mm','height_mm','diameter_mm')},'position_mm':scale(saxis,sign*(gap_half+foil+t/2)),'axis':saxis,'thickness_mm':t,'material':bulk(get(shape['material_id'],['sample']))})
        if foil>0:
            if sg['radius_mm']>sample['foil_diameter_mm']/2: raise ValueError('Source radius exceeds foil aperture')
            blocks.append({'id':side+'_foil','enabled':True,'shape':'cylinder','position_mm':scale(saxis,sign*(gap_half+foil/2)),'axis':saxis,'diameter_mm':sample['foil_diameter_mm'],'thickness_mm':foil,'material':bulk(get(sample['foil_material_id'],['foil']))})
    for shield in profile['shields']:
        if not shield['enabled']: continue
        position=shield['position_mm']; direction=axis(shield['azimuth_deg'],shield['tilt_deg']); up=frame(direction)[1]
        if shield['reference']!='source':
            detector=detectors[0 if shield['reference']=='A' else 1]; basis=frame(detector['axis'])
            position=add(detector['front_mm'],transform_vector(position,basis)); direction=transform_vector(direction,basis); up=transform_vector(up,basis)
        blocks.append({'id':shield['id'],'enabled':True,'shape':shield['shape'],'position_mm':position,'axis':direction,'up':up,
                       'width_mm':shield['width_mm'],'height_mm':shield['height_mm'],'diameter_mm':shield['diameter_mm'],'thickness_mm':shield['thickness_mm'],
                       'material':bulk(get(shield['material_id'],['shield']))})
    run=profile['run']; threads=resolve_threads(run['threads'],min(run['events'],run['secondary_events']) if profile['source']=='na22' else run['events'])
    source_profile=next(s for s in source_profiles() if s['id']==profile['source'])
    response=[operating_point(entries[d['pmt_id']],d['pmt_hv_V'],d['pmt_load_ohm'],d['pmt_polarity']) for d in profile['detectors']]
    resolved={'source':profile['source'],'physics':dict(profile['physics']),'events':run['events'],'seed':run['seed'],'threads':threads,'analog_response':response,
              'source_profile':source_profile,'source_geometry':source_geometry,'detectors':detectors,'blocks':blocks,'output':{'trajectory_sample_limit':run['trajectory_sample_limit'],'optical_tracks_per_detector':run['optical_tracks_per_detector']}}
    return resolved,list(dict.fromkeys(warnings))
