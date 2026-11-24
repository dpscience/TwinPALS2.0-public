# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Module 2 endpoints, registered before the application's static mount."""
import hashlib
from pathlib import Path
from .m1_store import encode, read_json, atomic_json, Conflict
from .m2_models import Profile
from .m2_physics import input_info
from .user_errors import validation_messages


def register(app,store,manager,controls,require_shared_idle):
    def components():
        return {'entries':store.components.entries(),'revision':store.components.revision,'path':str(store.components.path)}
    app.get('/api/m2/components')(components)

    @app.get('/api/m2/state')
    def state():
        return {'profile':store.module2,'components':components(),'job':manager.current()}

    @app.post('/api/m2/inputs')
    def inputs(raw:dict):
        from .material_lifetimes import input_materials
        info=input_info([store.resolve_path(v) for v in raw.get('paths',[])])
        info['materials']=input_materials(info,store.entries)
        return info

    @app.post('/api/m2/input-preview')
    def input_preview(raw:dict):
        import numpy as np
        from .analog_pmt import evaluate, tail_span
        from .streams import _Snapshot, _open_shared_read
        from .m2_models import resolve
        p=resolve(raw['profile'],store.components.entries(),check_mixture=False)['profile']
        info=input_info([store.resolve_path(v) for v in p['input_paths']])
        selected=None
        # Prefer an actual nonempty retained transport event, bounded for UI latency.
        for item in info['streams']:
            with _open_shared_read(item['path']) as f:
                snapshot=_Snapshot(Path(item['path']),f)
                for prefix,ds in snapshot.events():
                    if any(d[1] and d[0]&4 for d in ds):
                        selected=(prefix[0],[a[:,1].copy() if d[0]&4 else np.empty(0) for a,d in zip(snapshot.analog,ds)],snapshot.header);break
                    if prefix[0]>=4095:break
            if selected:break
        if selected is None:return dict(title='Digitizer input · no accepted photoelectrons',xLabel='Time after gamma emission (ns)',yLabel='Voltage (mV)',series=[])
        event,onsets,header=selected;responses=header['analog_response']
        active=[(a,r,c) for a,r,c in zip(onsets,responses,p['channels']) if len(a)]
        bandwidth=p['digitization']['input_bandwidth_MHz'];tau=1000/(2*np.pi*bandwidth) if bandwidth else 0.
        lo=min(a.min()+c['cable_delay_ns'] for a,r,c in active)-1
        hi=max(a.max()+tail_span(r['order'],r['tau_ns'])+c['cable_delay_ns'] for a,r,c in active)+tau*28
        x=np.linspace(lo,hi,1000);rail=p['digitization']['full_range_mV']/2
        series=[]
        for ch,(a,r,c) in enumerate(zip(onsets,responses,p['channels'])):
            y=evaluate(a,r,x-c['cable_delay_ns'],filter_tau_ns=tau)*10**(-c['attenuation_dB']/20)
            series.append(dict(name='Channel '+'AB'[ch],color=('#198f8c','#9870ca')[ch],points=np.column_stack((x,y)).tolist()))
        return dict(title=f'Digitizer input · event {event}',xLabel='Time after gamma emission (ns)',yLabel='Voltage (mV)',series=series,
            levels=[dict(y=-rail,label='Negative rail'),dict(y=rail,label='Positive rail')],
            explanation=dict(text='Actual analog pulse from the selected M1 stream.\n- Includes its complete PMT response; M2 applies only attenuation, cable delay and the chosen input bandwidth.\n- This isolated event is a preview, not a bound on future pile-up. Source overlap, lifetime, noise and sampling are applied during the M2 run.'))

    @app.post('/api/m2/validate')
    def validate(raw:dict):
        try:
            resolved,info=manager.check(store,raw['profile'])
            return {'valid':True,'errors':[],'warnings':resolved['warnings'],'resolved':resolved,'inputs':info}
        except (ValueError,OSError) as exc:
            return {'valid':False,'errors':validation_messages(exc),'warnings':[]}

    @app.post('/api/m2/runs')
    def run(raw:dict):
        with controls:return manager.create(store,raw['profile'],raw.get('overwrite') is True)
    @app.get('/api/m2/runs/current')
    def current_run():
        from fastapi.responses import JSONResponse
        return JSONResponse(manager.current())

    @app.post('/api/m2/runs/{identifier}/stop')
    def stop(identifier:str):return manager.stop(identifier)

    @app.post('/api/m2/analysis/open')
    def open_streams(raw:dict):
        with controls:return manager.import_streams(store,raw.get('paths',[]),raw.get('workers',0))

    @app.post('/api/m2/analysis')
    def analysis(raw:dict):
        if manager.analysis is None:raise ValueError('Generate or open a pulse stream first.')
        from fastapi.responses import JSONResponse
        return JSONResponse(manager.analysis.query(raw))

    @app.get('/api/m2/waveforms/{index}')
    def waveform(index:int):
        if manager.analysis is None:raise ValueError('No pulse stream is open.')
        return manager.analysis.waveform(index)

    def profile(raw):
        p=Profile.model_validate(raw).model_dump(mode='json')
        entries={e['id']:e for e in store.components.entries()}
        for key,category in [(p['digitization']['digitizer_id'],'digitizer')]:
            if key not in entries or entries[key]['category']!=category:
                raise ValueError(f'Component "{key}" is missing from the {category} database. Import it before loading these Module 2 settings.')
        return p

    @app.post('/api/m2/profiles/inspect')
    def inspect_profile(raw:dict):
        if 'profile' in raw:return {'profile':profile(raw['profile'])}
        path=store.resolve_path(raw.get('path',''))
        if path.suffix.lower()!='.tpm2':raise ValueError('Choose a Module 2 settings file ending in .tpm2.')
        return {'profile':profile(read_json(path))}

    @app.post('/api/m2/profiles/save')
    def save_profile(raw:dict):
        p=profile(raw['profile']);path=store.resolve_path(raw.get('path',''))
        if path.suffix.lower()!='.tpm2':raise ValueError('Module 2 settings filenames must end in .tpm2.')
        atomic_json(path,p,overwrite=raw.get('overwrite') is True)
        return {'path':str(path)}

