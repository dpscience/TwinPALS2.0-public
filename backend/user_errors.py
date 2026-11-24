# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Actionable field labels for validation and geometry failures."""
import re
from pydantic import ValidationError

LABELS={'distance_mm':'Position → Distance','vertical_offset_mm':'Position → Vertical offset','azimuth_deg':'Azimuth','tilt_deg':'Tilt',
 'length_mm':'Crystal → Length','front_diameter_mm':'Crystal → Front diameter','rear_diameter_mm':'Crystal → Rear diameter',
 'diameter_mm':'Diameter','width_mm':'Width','height_mm':'Height','thickness_mm':'Thickness',
 'coupling_mm':'Optical assembly → Coupling thickness','window_mm':'Optical assembly → Window thickness',
 'radius_mm':'Emission region → Radius','foil_thickness_mm':'Encapsulation foil → Thickness','foil_diameter_mm':'Encapsulation foil → Diameter',
 'events':'1275-keV events / Co-60 cascades','secondary_events':'511-keV pairs','seed':'Seed','threads':'CPU threads',
 'trajectory_sample_limit':'Saved preview samples','bins':'Bins','density_g_cm3':'Composition → Density',
 'light_yield_per_MeV':'Emission → Light yield','rise_time_ns':'Rise time','decay_time_ns':'Decay time','fraction':'Photon fraction',
 'resolution_scale':'Emission → Count fluctuation scale','refractive_index':'Optical properties → Refractive index',
 'absorption_length_mm':'Optical properties → Absorption length','side_mm':'Wrapping → Side thickness','front_mm':'Wrapping → Front thickness',
 'rate_GSps':'Sampling rate · GS/s','samples':'Samples per channel','full_range_mV':'Full voltage range · mV',
 'activity_Bq':'Sample → Effective activity · Bq','waveform_pairs':'Run → Waveform pairs to save','maximum':'Run → Maximum','dead_time_unit':'DAQ → Dead time unit','tts_ns':'Single-photoelectron TTS',
 'attenuation_dB':'Input attenuation · dB','pmt_hv_V':'PMT operating voltage · V','pmt_load_ohm':'Effective output load · Ω','input_bandwidth_MHz':'Input bandwidth · MHz',
 'threshold_mV':'Trigger magnitude · mV','input_paths':'Input streams','tau_ns':'Lifetime','intensity':'Intensity fraction'}


def field_label(location):
    loc=list(location)
    while loc and loc[0] in ('body','profile'): loc.pop(0)
    area='Setup'
    if loc and loc[0]=='detectors':
        index=loc[1] if len(loc)>1 else 0;area=f'Setup → Detector {"AB"[index] if isinstance(index,int) and index<2 else index}';loc=loc[2:]
    elif loc and loc[0]=='channels':
        index=loc[1] if len(loc)>1 else 0;area=f'Setup → Channel {"AB"[index] if isinstance(index,int) and index<2 else index}';loc=loc[2:]
    elif loc and loc[0] in ('digitization','acquisition'):
        area='Setup → '+('Digitizer' if loc.pop(0)=='digitization' else 'DAQ')
    elif loc and loc[0]=='lifetimes':
        area=f'Setup → Sample → Lifetime component {int(loc[1])+1}';loc=loc[2:]
    elif loc and loc[0]=='shields':
        area=f'Setup → Shield → Block {int(loc[1])+1}';loc=loc[2:]
    elif loc and loc[0] in ('sample','source_geometry','assembly'):
        area='Setup → Source';first=loc.pop(0)
        if loc and loc[0] in ('left','right'): area+=f' → {str(loc.pop(0)).title()} sample'
        if first=='assembly': area+=' → Sandwich orientation'
    elif loc and loc[0]=='run': area='Setup → Run';loc=loc[1:]
    elif loc and loc[0] in ('entry','properties','curves'):
        area='Material database'
    if not loc:return area
    key=str(loc[-1]);label=LABELS.get(key,key.replace('_mm','').replace('_deg','').replace('_',' ').capitalize())
    return area+' → '+label


def validation_messages(exc,material=False):
    if not isinstance(exc,ValidationError) and not hasattr(exc,'errors'): return [friendly_error(str(exc))]
    messages=[]
    for error in exc.errors():
        loc=error.get('loc',());key=str(loc[-1]) if loc else '';context=error.get('ctx',{});kind=error['type']
        unit=' mm' if key.endswith('_mm') else ' ns' if key.endswith('_ns') else '°' if key.endswith('_deg') else ''
        bounds={'greater_than':('greater than','gt'),'greater_than_equal':('at least','ge'),'less_than':('less than','lt'),'less_than_equal':('at most','le')}
        if kind in bounds:
            phrase,bound=bounds[kind];message=f'Enter a value {phrase} {context.get(bound)}{unit}.'
        elif kind in ('float_parsing','int_parsing','float_type','int_type','int_from_float'):message='Enter a valid '+('whole number.' if kind.startswith('int') else 'number.')
        elif kind=='missing':message='This value is required. Complete this field.'
        elif kind=='extra_forbidden':message='This field is not part of the current file format. Use a current file for this module.'
        elif kind=='literal_error':message='Choose one of the available options. Older file formats cannot be loaded.'
        else:message=error.get('msg','Check this value.').removeprefix('Value error, ')
        label=field_label(loc)
        if material:label=label.replace('Setup','Material database',1)
        for raw,display in LABELS.items():message=message.replace(raw,display)
        messages.append(label+': '+message)
    return list(dict.fromkeys(messages))


def friendly_error(message):
    from .storage_health import exhausted,space_message
    if exhausted(message):return space_message()
    if 'Cannot resolve a grazing optical reflection at ' in message:
        match=re.search(r'ScintSolid([AB])',message)
        part=f'Detector {match[1]} crystal' if match else 'an optical component'
        return (f'Optical transport stopped at the surface of {part}. The navigator could not resolve this boundary safely.\n'
                'Keep the Module 1 settings and run log for diagnosis; the log contains the exact position and direction. '
                'Completed stream records remain available. Increasing the event count or waiting longer does not repair this boundary.')
    if 'Geometry overlaps at ' in message or 'Overlap is detected' in message:
        names=re.findall(r'(?:Scint|WrapFront|Wrap|Coupling|Window|Cathode)[AB]|(?:Sample|Shield)_[A-Za-z0-9_]+',message)
        labels=[];advice=[]
        for name in dict.fromkeys(names):
            if name.startswith(('Sample_','Shield_')):
                side='Left' if 'left_' in name else 'Right'
                label=f'{side} encapsulation foil' if '_foil' in name else f'{side} sample' if '_sample' in name else 'Shielding block '+name.removeprefix('Shield_')
                advice.append('Setup → Source: reduce sample/foil dimensions or adjust sandwich orientation.' if name.startswith('Sample_') else 'Setup → Shield: adjust the block position or reduce its dimensions.')
            else:
                label='Detector '+name[-1]+' '+{'Scint':'crystal','Wrap':'side wrapping','WrapFront':'front wrapping','Coupling':'coupling','Window':'entrance window','Cathode':'photocathode'}[name[:-1]]
                advice.append(f'Setup → Detector {name[-1]} → Position: increase Distance or adjust Vertical offset, Azimuth or Tilt.')
                if name.startswith('Wrap'):advice.append(f'Setup → Detector {name[-1]} → Wrapping: check the front and side thicknesses.')
            labels.append(label)
        return 'Geometry overlap: '+(', '.join(labels) or 'two components')+' occupy the same space.\n'+'\n'.join(dict.fromkeys(advice or ['Adjust component positions or dimensions in Setup, then run Check geometry again.']))
    if 'Source radius exceeds' in message:
        target='encapsulation foil' if 'foil' in message else 'left sample' if 'left' in message else 'right sample'
        return f'Setup → Source: the emission region is wider than the {target}. Reduce Emission region → Radius or increase the {target} diameter/width.'
    return message
