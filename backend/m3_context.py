# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Acquisition metadata and comparison for the selected Module 2 files."""
from pathlib import Path
from .m2_stream import Reader


def recorded_apparatus(header):
    """Describe only the detector setup carried by this particular transport input."""
    profile=header.get('profile') or {}
    names=header.get('material_names') or {}
    def material(key):
        return names.get(key,key) if key else ''
    def quantity(obj,key,unit):
        value=obj.get(key)
        return f'{value:g} {unit}' if isinstance(value,(int,float)) else ''
    def join(*parts):
        return ' · '.join(part for part in parts if part)
    def face(obj,shape,prefix=''):
        if shape in ('cone','cylinder'):
            diameter=quantity(obj,prefix+'diameter_mm','mm')
            return 'Ø '+diameter if diameter else ''
        if shape in ('box','pyramid'):
            w,h=obj.get(prefix+'width_mm'),obj.get(prefix+'height_mm')
            if w is not None and h is not None:return f'{w:g} × {h:g} mm'
        return ''
    def geometry(obj,shape):
        if shape in ('cone','pyramid'):
            ends=[face(obj,shape,prefix) for prefix in ('front_','rear_')]
            return ' → '.join(ends) if all(ends) else ''
        return face(obj,shape)
    source={}
    isotope=header.get('source') or profile.get('source')
    shape=profile.get('source_geometry') or {}
    size='Point source' if shape.get('radius_mm')==0 and shape.get('thickness_mm')==0 else join(
        quantity(shape,'radius_mm','mm radius'),quantity(shape,'thickness_mm','mm thick'))
    if isotope:source['Source']=join({'na22':'Na-22','co60':'Co-60'}.get(isotope,isotope),size)
    sample=profile.get('sample') or {}
    if sample.get('enabled') is False:source['Sample']='Disabled'
    else:
        for side in ('left','right'):
            slab=sample.get(side) or {}
            if slab:source[side.title()+' sample']=join(material(slab.get('material_id')),face(slab,slab.get('shape')),quantity(slab,'thickness_mm','mm')+' thick' if slab.get('thickness_mm') is not None else '')
    if 'foil_enabled' in sample:
        diameter=quantity(sample,'foil_diameter_mm','mm')
        source['Source foils']=join(material(sample.get('foil_material_id')),'Ø '+diameter if diameter else '',quantity(sample,'foil_thickness_mm','mm per foil')) if sample['foil_enabled'] else 'Disabled'
    assembly=profile.get('assembly') or {}
    if assembly:source['Sandwich axis']=join(quantity(assembly,'azimuth_deg','° azimuth'),quantity(assembly,'tilt_deg','° tilt'))
    if 'shields' in profile:
        enabled=[v for v in profile['shields'] if v.get('enabled')]
        if not enabled:source['Shielding']='None enabled'
        for index,shield in enumerate(enabled,1):
            pos=shield.get('position_mm') or []
            xyz='('+', '.join(f'{v:g}' for v in pos)+') mm' if len(pos)==3 else ''
            source[f'Shield {index}']=join(material(shield.get('material_id')),shield.get('shape'),face(shield,shield.get('shape')),quantity(shield,'thickness_mm','mm thick'),xyz,shield.get('reference'),quantity(shield,'azimuth_deg','° azimuth'),quantity(shield,'tilt_deg','° tilt'))
    physics=header.get('physics') or profile.get('physics') or {}
    if 'include_cherenkov' in physics:source['Cherenkov']='Enabled' if physics['include_cherenkov'] else 'Disabled'
    if 'minimum_energy_keV' in physics:source['Minimum crystal energy']=quantity(physics,'minimum_energy_keV','keV')
    if (version:=(header.get('native') or {}).get('geant4_version')):source['Transport']='Geant4 '+str(version)
    detectors={}
    instrument={}
    pmts={p.get('id'):p.get('properties',{}) for p in header.get('pmt_snapshot') or []}
    for i,det in enumerate(profile.get('detectors') or []):
        channel=det.get('id')
        if channel not in ('A','B'):continue
        dim=det.get('dimensions') or {};shape=det.get('shape');wrap=det.get('wrapping') or {}
        pmt=pmts.get(det.get('pmt_id'),{});glass=pmt.get('window_material') or {}
        tube_response=header.get('analog_response') or []
        tube=tube_response[i] if i<len(tube_response) and tube_response[i].get('pmt_id')==det.get('pmt_id') else {}
        cathode_shape=pmt.get('photocathode_shape')
        cathode_dimension=face(pmt,{'circle':'cylinder','rect':'box','rectangle':'box'}.get(cathode_shape),'photocathode_')
        model=material(det.get('pmt_id'))
        voltage=quantity(tube,'hv_V','V') or quantity(det,'pmt_hv_V','V')
        load=quantity(det,'pmt_load_ohm','Ω')
        tapered=shape in ('cone','pyramid')
        fields={'Shape':shape,'Front face':face(dim,shape,'front_') if tapered else '',
                'Rear face':face(dim,shape,'rear_') if tapered else '',
                'Cross section':face(dim,shape) if not tapered else '','Length':quantity(dim,'length_mm','mm'),
                'Model':model,'Bias voltage':voltage,'Load':load,'Cathode shape':cathode_shape,'Active face':cathode_dimension}
        instrument[channel]={key:value for key,value in fields.items() if value}
        rows={'Crystal':material(det.get('scintillator_id')),
              'Geometry':join(shape,geometry(dim,shape),quantity(dim,'length_mm','mm')+' long' if 'length_mm' in dim else ''),
              'Front radial distance':quantity(det,'distance_mm','mm'),
              'Orientation':join(quantity(det,'azimuth_deg','° azimuth'),quantity(det,'tilt_deg','° tilt'),quantity(det,'vertical_offset_mm','mm vertical offset')),
              'Wrapping':('Disabled' if wrap.get('enabled') is False else join(material(det.get('surface_id')),quantity(wrap,'front_mm','mm front'),quantity(wrap,'side_mm','mm side'))),
              'Coupling':join(material(det.get('coupling_id')),quantity(det,'coupling_mm','mm')),
              'PMT window':join(glass.get('name') if isinstance(glass,dict) else glass,quantity(pmt,'window_thickness_mm','mm')),
              'Photocathode':join(cathode_shape,cathode_dimension),
              'PMT':join(model,voltage,load)}
        detectors[channel]={k:v for k,v in rows.items() if v}
    result={'source':source,'detectors':detectors}
    if instrument:result['instrument']=instrument
    return result


def adc_channels(header):
    profile=header.get('profile',{})
    digitizer=profile.get('digitization',{})
    low=digitizer.get('voltage_min_mV',-500);high=digitizer.get('voltage_max_mV',500)
    baseline=digitizer.get('baseline_mV',0)
    response=header.get('resolved',{}).get('analog_response',[])
    result=[]
    for i,ch in enumerate(profile.get('channels',[{},{}])):
        positive=(i<len(response) and response[i].get('polarity')=='positive')!=ch.get('invert',False)
        result.append(dict(polarity='positive' if positive else 'negative',low=low,high=high,baseline=baseline,
                           height=max(.001,high-baseline if positive else baseline-low)))
    return result


def selection_error(headers):
    return 'Select one Module 2 pulse stream.' if len(headers)>1 else ''


def inspect_inputs(store,values):
    if not isinstance(values,list) or len(values)>1:raise ValueError('Select one Module 2 pulse stream.')
    streams=[];headers=[];errors=[]
    for index,value in enumerate(values):
        if not value:
            streams.append(None);continue
        try:
            path=store.resolve_path(value)
            if not path.name.endswith(('.tppulses','.tppulses.part')):raise ValueError('Choose a Module 2 pulse stream.')
            reader=Reader(path)
            try:
                info=source_context([path],[reader.header])['streams'][0]
                info['bytes']=reader.limit;info['partial']=reader.path.suffix=='.part'
                headers.append(reader.header);streams.append(info)
            finally:reader.close()
        except (OSError,ValueError,KeyError) as exc:
            streams.append(None);errors.append(dict(index=index,message=str(exc)))
    return dict(streams=streams,errors=errors,conflict=selection_error(headers))
def source_context(paths, headers):
    streams=[]
    for path,h in zip(paths,headers):
        profile=h.get('profile',{})
        resolved=h.get('resolved',{})
        inputs=[]
        for source in h.get('inputs',[]):
            m1=source.get('header',{})
            names=m1.get('material_names',{})
            entries={key:dict(id=key,name=name) for key,name in names.items()}
            for pmt in m1.get('pmt_snapshot',[]):
                entries[pmt['id']]={k:pmt[k] for k in ('id','name','properties') if k in pmt}
            inputs.append(dict(path=source.get('path',''),role=m1.get('role'),
                               physics=m1.get('physics',{}),setup=m1.get('profile',{}),apparatus=recorded_apparatus(m1),
                               entries=list(entries.values()),maximum_mV=(source.get('completion') or {}).get('observed_maximum_mV')))
        d=resolved.get('digitizer',{})
        streams.append(dict(path=str(path),name=Path(path).name,run_id=h.get('run_id'),stream_id=h.get('stream_id'),class_filter=h.get('class_filter'),created_utc=h.get('created_utc',''),
            source=h.get('isotope',''),activity_Bq=profile.get('activity_Bq'),
            lifetimes=profile.get('lifetimes',[]) if h.get('isotope')=='na22' else [],acquisition=profile.get('acquisition',{}),
            electronics=dict(profile=profile,device=d,responses=resolved.get('analog_response',[])),
            digitizer={**{k:v for k,v in d.items() if k in ('name','id','adc_bits')},
                       **{k:v for k,v in profile.get('digitization',{}).items() if k in ('rate_GSps','samples','voltage_min_mV','voltage_max_mV','input_bandwidth_MHz')}},
            adc=adc_channels(h),channels=[{**response, **channel} for response,channel in
                zip(resolved.get('analog_response',[]),profile.get('channels',[]))],inputs=inputs))
    return dict(streams=streams)
