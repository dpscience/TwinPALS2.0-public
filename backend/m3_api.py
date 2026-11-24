# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Module 3 acquisition endpoints and ordered live measurement changes."""
from .m3_models import Profile, Settings, SpectrumDirection, SpectrumDisplay
from .m1_store import atomic_json, read_json, Conflict

def register(app,store,manager,controls):
    @app.get('/api/m3/state')
    def state():return dict(profile=store.module3,job=manager.current())
    @app.get('/api/m3/context')
    def context():
        from .m3_context import source_context
        with manager.borrow() as job:return source_context(job.paths,job.headers)
    @app.post('/api/m3/check')
    def check(raw:dict):
        p,paths,headers=manager.check(store,raw)
        return dict(valid=True,headers=headers)
    @app.post('/api/m3/inputs')
    def inputs(raw:dict):
        from .m3_context import inspect_inputs
        manager.check_selection(store,raw.get('paths',[]))
        return inspect_inputs(store,raw.get('paths',[]))
    @app.post('/api/m3/start')
    def start(raw:dict):
        with controls:return manager.start(store,raw)
    @app.post('/api/m3/restart')
    def restart(raw:dict):
        with controls:return manager.start(store,raw['profile'],raw['id'])
    @app.post('/api/m3/hold')
    def hold(raw:dict):return manager.hold(raw.get('id'))
    @app.post('/api/m3/resume')
    def resume(raw:dict):return manager.hold(raw.get('id'),True)
    @app.post('/api/m3/stop')
    def stop():return manager.stop()
    @app.post('/api/m3/reset')
    def reset():
        with controls,manager.borrow() as job:return job.reset()
    @app.post('/api/m3/plot/reset')
    def reset_plot(raw:dict):
        with controls,manager.borrow() as job:
            if raw.get('id')!=job.id:raise Conflict('The active Module 3 stream has changed.')
            return job.reset_plot(raw.get('kind'),raw.get('target'))
    @app.post('/api/m3/monitor')
    def monitor(raw:dict):
        from fastapi.responses import Response
        from pydantic_core import to_json
        with manager.borrow() as job:return Response(to_json(job.monitor(raw.get('plots',[]),raw.get('share_cells',False))),media_type='application/json')
    @app.post('/api/m3/workers')
    def workers(raw:dict):
        with controls,manager.borrow() as job:
            if raw.get('id')!=job.id:raise Conflict('The active Module 3 stream has changed.')
            return job.set_workers(raw.get('workers'))
    @app.post('/api/m3/configure')
    def configure(raw:dict):
        with controls,manager.borrow() as job:
            if raw.get('id')!=job.id:raise Conflict('The active Module 3 stream has changed.')
            return job.configure(raw.get('channels',[]),raw.get('revision'),raw.get('pulse_selection'),raw.get('preview_count'))
    @app.post('/api/m3/analysis')
    def analysis(displays:dict[SpectrumDirection,SpectrumDisplay]):
        from fastapi.responses import Response
        from pydantic_core import to_json
        if not displays:raise ValueError('Choose a lifetime spectrum.')
        with manager.borrow() as job:result=job.spectra(displays)
        return Response(to_json(result),media_type='application/json')
    @app.post('/api/m3/query')
    def query(raw:dict):
        from fastapi.responses import Response
        from pydantic_core import to_json
        with manager.borrow() as job:result=job.query(raw)
        return Response(to_json(result),media_type='application/json')
    @app.get('/api/m3/waveform/{sequence}')
    def waveform(sequence:int):
        with manager.borrow() as job:return job.waveform(sequence)
    @app.post('/api/m3/waveform/{sequence}')
    def preview(sequence:int,raw:dict):
        traces=raw.get('traces',[False,False])
        if not isinstance(traces,list) or len(traces)!=2 or any(type(t) is not bool for t in traces):raise ValueError('Choose interpolation traces for A and B.')
        with manager.borrow() as job:
            if raw.get('id',job.id)!=job.id:raise Conflict('The active Module 3 stream has changed.')
            return job.waveform(sequence,raw.get('channels'),traces,raw.get('pulse_selection'))
    @app.post('/api/m3/autofit')
    def autofit(raw:dict):
        if raw.get('channel') not in (0,1) or raw.get('window') not in ('start','stop') or raw.get('kind') not in ('area','shape'):raise ValueError('Choose channel A or B, Start or Stop, and an area or shape filter.')
        from .m3_models import Window
        limits=Window.model_validate(raw['phs']).model_dump() if 'phs' in raw else None
        with manager.borrow() as job:
            if raw.get('id',job.id)!=job.id:raise Conflict('The active Module 3 stream has changed.')
            return job.autofit(raw['channel'],raw['window'],raw['kind'],limits,raw.get('options'),raw.get('include_counts') is True)
    @app.post('/api/m3/settings/open')
    def open_settings(raw:dict):
        path=store.resolve_path(raw['path'])
        if path.suffix.lower()!='.tpm3':raise ValueError('Choose Module 3 settings (.tpm3).')
        value=read_json(path)
        if isinstance(value,dict) and 'processing' in value:
            value={**value,'processing':Profile.from_saved(value['processing']).model_dump()}
        return Settings.model_validate(value).model_dump()
    @app.post('/api/m3/settings/save')
    def save_settings(raw:dict):
        settings=Settings.model_validate(raw['settings']).model_dump()
        path=store.resolve_path(raw['path'])
        if path.suffix.lower()!='.tpm3':raise ValueError('Use the .tpm3 extension for Module 3 settings.')
        if path.exists() and not raw.get('overwrite'):raise Conflict('This settings file already exists. Confirm replacement.')
        atomic_json(path,settings);return dict(path=str(path))
