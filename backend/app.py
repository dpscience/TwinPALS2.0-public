# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Local application with a database and private automatic UI state."""
from contextlib import asynccontextmanager
import asyncio
import copy
import csv
import io
import json
import hashlib
import os
from pathlib import Path
import sys
import threading
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from backend.legal_notices import mount_legal_notices
from starlette.middleware.trustedhost import TrustedHostMiddleware
from backend.release_updates import release_status
from starlette.concurrency import run_in_threadpool
from . import __version__
from .execution import cpu_settings
from .native_runtime import engine_status
from .m1_engine import RunManager
from .m1_models import Profile as Module1Profile
from .m1_resolve import resolve_profile
from .m1_store import ApplicationStore, Conflict, read_json, atomic_json
from .user_errors import validation_messages
from .composition import parse_formula, ELEMENTS
from .material_database import CATEGORY_LABELS, CatalogueConflict
from .material_exchange import FAMILIES, family_for, export_entry, inspect_entry, import_entry
from .standard_materials import standard_catalogue
from .client_gate import ClientGate
from .physics import source_profiles
from .live_analysis import AnalysisStore
from .geometry_check import validate_geometry
from .view_settings import view_settings


def application_root():
    return Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]


def default_data_directory(root):
    if getattr(sys, 'frozen', False) and (root / 'twinpals-installed.ini').is_file():
        return Path(os.environ['LOCALAPPDATA']) / 'TwinPALS' / 'Data'
    return root / 'data'


def create_app(data_dir=None, project_root=None, catalogue_path=None):
    root=Path(project_root or application_root()).resolve()
    store=ApplicationStore(Path(data_dir or default_data_directory(root)),root/'seed/factory_catalogue.json',catalogue_path)
    # Reset only the launch destination. A browser reconnect or profile import
    # within this application session can still restore its own navigation.
    store.ui.update(module=1, tab='setup')
    for module in ('module2','module3'):
        store.ui[module]['tab']='setup'
    manager=RunManager(root)
    from .m2_engine import PulseManager
    pulse_manager=PulseManager()
    from .m3_engine import LifetimeManager
    lifetime_manager=LifetimeManager()
    controls=threading.RLock()
    clients=ClientGate()
    imported=None
    import_key=None
    @asynccontextmanager
    async def lifespan(app):
        try: yield
        finally:
            manager.shutdown()
            pulse_manager.shutdown()
            lifetime_manager.shutdown()
            if imported is not None: imported.close()
            store.close()
    app=FastAPI(title='TwinPALS',version=__version__,lifespan=lifespan)
    app.state.store=store; app.state.manager=manager; app.state.clients=clients; app.state.pulse_manager=pulse_manager;app.state.lifetime_manager=lifetime_manager
    def tray_activity():
        active = []
        source = imported
        if manager.active() or (source is not None and source.progress()['loading']):
            active.append('Module 1')
        if pulse_manager.active():
            active.append('Module 2')
        if lifetime_manager.active():
            active.append('Module 3')
        return ', '.join(active) + ' active' if active else ''
    app.state.tray_activity = tray_activity
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=['127.0.0.1','localhost','[::1]','testserver'])

    @app.middleware('http')
    async def local_origin(request,call_next):
        origin=request.headers.get('origin')
        if request.method not in ('GET','HEAD','OPTIONS') and origin and (urlsplit(origin).scheme,urlsplit(origin).netloc)!=(request.url.scheme,request.url.netloc):
            return JSONResponse({'detail':'Cross-origin writes are disabled'},status_code=403)
        if request.url.path.startswith('/api/') and request.url.path not in ('/api/health','/api/client/connect','/api/client/close') and not clients.owns(request.headers.get('x-twinpals-client')):
            return JSONResponse({'detail':'TwinPALS is already open in another window, or this window lost its connection. Close the active window and reconnect here.'},status_code=423)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='same-origin'
        if response.headers.get('content-type','').startswith('text/html'): response.headers['Cache-Control']='no-store'
        return response

    @app.exception_handler(Conflict)
    @app.exception_handler(CatalogueConflict)
    async def conflict(request,exc): return JSONResponse({'detail':str(exc)},status_code=409)
    @app.exception_handler(ValueError)
    async def invalid(request,exc): return JSONResponse({'detail':'\n'.join(validation_messages(exc,material=request.url.path.startswith('/api/materials')))},status_code=422)
    @app.exception_handler(RequestValidationError)
    async def invalid_request(request,exc): return JSONResponse({'detail':'\n'.join(validation_messages(exc))},status_code=422)
    @app.exception_handler(KeyError)
    async def missing(request,exc): return JSONResponse({'detail':'Requested value was not found: '+str(exc)},status_code=404)
    @app.exception_handler(OSError)
    async def filesystem(request,exc):
        if isinstance(exc,FileNotFoundError):
            message=f'File not found: {exc.filename or "the selected file"}. Choose its current location and try again.'
        elif isinstance(exc,PermissionError):
            message=f'Cannot access {exc.filename or "this location"}. Close any program locking the file or choose a writable folder.'
        else:message=str(exc)
        return JSONResponse({'detail':message},status_code=422)

    def health(): return {'status':'ok','version':__version__,'engine':engine_status(root),**cpu_settings(),'settings_version':Module1Profile.model_fields['version'].default}
    app.get('/api/health')(health)

    @app.get('/api/releases/latest')
    def releases(refresh: bool = False, manual: bool = False):
        return release_status(store.root, refresh=refresh, manual=manual)

    @app.get('/api/client/connect')
    async def connect_client(request:Request):
        origin=request.headers.get('origin')
        if origin and (urlsplit(origin).scheme,urlsplit(origin).netloc)!=(request.url.scheme,request.url.netloc):
            raise HTTPException(403,'Open TwinPALS from its own local address.')
        async def events():
            token=None
            try:
                for _ in range(8):
                    token=clients.acquire()
                    if token:break
                    await asyncio.sleep(.15)
                if not token:
                    yield 'data: {"type":"busy"}\n\n';return
                yield 'data: '+json.dumps({'type':'ready','token':token})+'\n\n'
                while clients.owns(token):
                    if await request.is_disconnected():break
                    yield ': connected\n\n'
                    await asyncio.sleep(1)
            finally:
                if token:clients.release(token)
        return StreamingResponse(events(),media_type='text/event-stream',headers={'Cache-Control':'no-store','X-Accel-Buffering':'no'})

    @app.post('/api/client/close')
    def close_client(raw:dict):
        token=raw.get('token')
        with clients.lock:
            if not clients.can_close(token):raise HTTPException(423,'This window no longer owns the application.')
            try:
                if raw.get('state'):
                    save_session(raw['state'])
            finally:clients.release(token)
        return {'closed':True}
    def imported_session():
        if imported is None: return None
        progress=imported.progress()
        streams=[{'path':b.path,'header':copy.deepcopy(b.header),
                  'completion':{'events':b.count,'status':b.status,'verified':b.verified}}
                 for b in imported.buffers.values()]
        return {'streams':streams,'profile':streams[0]['header']['profile'],
                'roles':list(imported.buffers),'progress':progress}

    def state():
        with store.lock:
            return {'folder':str(store.root),'settings_path':str(store.path),'database_path':str(store.database.path),'database_revision':store.database.revision,'revision':store.revision,'profile':copy.deepcopy(store.profile),'module2':copy.deepcopy(store.module2),'module3':copy.deepcopy(store.module3),'entries':copy.deepcopy(store.entries),
                    'ui':copy.deepcopy(store.ui),'sources':source_profiles(),'health':health(),'run':manager.current(),'imported':imported_session(),'startup_notice':store.startup_notice}
    app.get('/api/m1/state')(state)

    def require_idle():
        if manager.active(): raise Conflict('Module 1 is running. Stop it before opening another data source.')
        if imported is not None:
            with imported.lock:
                if imported.progress()['loading']:
                    raise Conflict('Wait for the stream import to finish before opening another data source.')

    def require_shared_idle():
        require_idle()
        if lifetime_manager.active():raise Conflict('Module 3 is reading. Stop it before changing shared profiles or databases.')
        if pulse_manager.active(): raise Conflict('Module 2 is running or importing. Stop it before changing shared profiles or component databases.')

    @app.post('/api/session')
    def save_session(raw:dict):
        with controls:
            draft=raw.get('module3')
            if draft is not None:lifetime_manager.check_selection(store,draft.get('input_paths',[]))
            return store.save(raw['profile'],raw['ui'],raw['client_id'],raw['sequence'],raw.get('module2'),draft)

    def read_app_profile(value):
        path=store.resolve_path(value)
        if path.suffix.lower()!='.tpprofile': raise ValueError('Choose a TwinPALS profile ending in .tpprofile.')
        data=store.inspect_app_profile(read_json(path))
        digest=hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        return data,digest

    @app.post('/api/profile/export')
    def export_app_profile(raw:dict):
        with controls,store.lock:
            require_shared_idle()
            path=store.resolve_path(raw.get('path',''))
            if path.suffix.lower()!='.tpprofile': raise ValueError('Choose a filename ending in .tpprofile.')
            atomic_json(path,store.app_profile(),overwrite=raw.get('overwrite') is True)
            return {'path':str(path)}

    @app.post('/api/profile/preview')
    def preview_app_profile(raw:dict):
        with controls,store.lock:
            require_shared_idle()
            data,digest=read_app_profile(raw.get('path',''))
            return {'sha256':digest,'source':data['modules']['module1']['source'],'tab':data['ui']['tab']}

    @app.post('/api/profile/import')
    def import_app_profile(raw:dict):
        with controls,store.lock:
            require_shared_idle()
            if raw.get('confirmed') is not True: raise Conflict('Confirm replacement of the current profile first.')
            data,digest=read_app_profile(raw.get('path',''))
            if raw.get('sha256')!=digest: raise Conflict('The profile file changed after checking it. Load it again.')
            store.apply_app_profile(data)
            return state()

    @app.get('/api/materials')
    def materials():
        return {'entries':store.entries,'revision':store.database.revision,'path':str(store.database.path),'categories':CATEGORY_LABELS}

    @app.post('/api/materials')
    def put_material(raw:dict):
        with controls:
            require_shared_idle(); store.put_entry(raw['entry'],raw.get('expected_revision'))
        return materials()

    @app.delete('/api/materials/{key}')
    def delete_material(key:str,expected_revision:int):
        with controls:
            require_shared_idle(); store.delete_entry(key,expected_revision)
        return materials()

    @app.post('/api/materials/formula')
    def formula(raw:dict): return {'composition':parse_formula(raw.get('formula',''))}

    @app.get('/api/materials/elements')
    def elements(): return ELEMENTS

    @app.get('/api/materials/standards')
    def standards(): return {'version':'11.4.0','items':[{**s,'composition':s.get('atomic_composition') or s['composition'],'composition_basis':'atoms' if s.get('atomic_composition') else 'mass_fraction'} for s in standard_catalogue().values()]}

    @app.post('/api/materials/export')
    def export_materials(raw:dict):
        path=store.resolve_path(raw.get('path',''))
        if path.suffix.lower()!='.tpcatalogue': raise ValueError('Choose a filename ending in .tpcatalogue.')
        with controls,store.lock:
            require_shared_idle()
            atomic_json(path,store.database.export_catalogue(),overwrite=raw.get('overwrite') is True)
        return {'path':str(path)}

    def read_material_catalogue(path):
        path=store.resolve_path(path)
        if path.suffix.lower()!='.tpcatalogue': raise ValueError('Choose a database export ending in .tpcatalogue.')
        raw=read_json(path)
        digest=hashlib.sha256(json.dumps(raw,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        return raw,digest

    @app.post('/api/materials/import/preview')
    def preview_materials(raw:dict):
        with controls,store.lock:
            require_shared_idle()
            data,digest=read_material_catalogue(raw.get('path',''))
            _,groups=store.database.inspect_catalogue(data)
            return {**groups,'sha256':digest,'revision':store.database.revision}

    @app.post('/api/materials/import')
    def import_materials(raw:dict):
        with controls,store.lock:
            require_shared_idle()
            data,digest=read_material_catalogue(raw.get('path',''))
            if raw.get('sha256')!=digest: raise Conflict('The import file changed after the preview. Preview it again before importing.')
            store.database.import_catalogue(data,raw.get('revision'),replace_existing=raw.get('replace_existing') is True)
            return materials()

    def read_single_material(raw):
        category=raw.get('category'); family=family_for(category)
        path=store.resolve_path(raw.get('path',''))
        extension=FAMILIES[family]['extension']
        if path.suffix.lower()!=extension: raise ValueError(f'Choose a {extension} file for {CATEGORY_LABELS[category]}.')
        data=read_json(path)
        digest=hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        return data,digest

    @app.post('/api/materials/entry/export')
    def export_single_material(raw:dict):
        with controls,store.lock:
            require_shared_idle()
            data=export_entry(store.database,raw.get('id'))
            path=store.resolve_path(raw.get('path','')); extension=FAMILIES[data['family']]['extension']
            if path.suffix.lower()!=extension: raise ValueError(f'Use the {extension} extension for this material.')
            atomic_json(path,data,overwrite=raw.get('overwrite') is True)
            return {'path':str(path)}

    @app.post('/api/materials/entry/preview')
    def preview_single_material(raw:dict):
        with controls,store.lock:
            require_shared_idle(); data,digest=read_single_material(raw)
            _,preview=inspect_entry(store.database,data,raw.get('category'),raw.get('id'))
            return {**preview,'sha256':digest}

    @app.post('/api/materials/entry/import')
    def import_single_material(raw:dict):
        with controls,store.lock:
            require_shared_idle(); data,digest=read_single_material(raw)
            if raw.get('sha256')!=digest: raise Conflict('The file changed after the preview. Preview it again before importing.')
            entry=import_entry(store.database,data,raw.get('category'),raw.get('id'),raw.get('revision'),replace=raw.get('replace') is True)
            return {**materials(),'imported_id':entry['id']}

    @app.post('/api/files/text')
    def file_text(raw:dict):
        path=store.resolve_path(raw['path'])
        if path.suffix.lower() not in ('.csv','.txt','.tsv','.dat'): raise ValueError('Choose a CSV, TXT, TSV or DAT table.')
        if path.stat().st_size>32*1024*1024: raise ValueError('This table exceeds 32 MiB. Choose a smaller optical-property table.')
        return {'text':path.read_text(encoding='utf-8-sig')}

    @app.post('/api/m1/validate')
    def validate(raw:dict):
        try:
            profile=store.freeze(raw['profile']); resolved,warnings=resolve_profile(profile,store.entries)
            geometry=validate_geometry(root,resolved)
            return {'valid':True,'errors':[],'warnings':warnings,'resolved':resolved,'geometry':geometry}
        except (ValueError,KeyError) as exc: return {'valid':False,'errors':validation_messages(exc),'warnings':[],'resolved':None}

    @app.post('/api/m1/profiles/save')
    def save_profile(raw:dict):
        profile=store.freeze(raw['profile']); path=store.resolve_path(raw['path'])
        if path.suffix.lower()!='.tpm1': raise ValueError('Module 1 settings filenames must end in .tpm1')
        atomic_json(path,profile,overwrite=bool(raw.get('overwrite',False)))
        return {'path':str(path),'profile':profile}

    @app.post('/api/m1/profiles/inspect')
    def inspect_profile(raw:dict):
        if 'profile' in raw:
            profile=raw['profile']
        else:
            path=store.resolve_path(raw['path'])
            try: profile=read_json(path)
            except (json.JSONDecodeError,UnicodeError) as exc:
                raise ValueError(f'“{path.name}” is not a readable Module 1 settings file. Select a .tpm1 file saved by TwinPALS.') from exc
        if not isinstance(profile,dict) or profile.get('format')!='twinpals-module1-profile' or profile.get('version')!=8: raise ValueError('This file does not contain current Module 1 settings. Select a reference-only .tpm1 file saved by TwinPALS.')
        return store.inspect(profile)

    @app.post('/api/m1/runs')
    def run(raw:dict):
        with controls:
            require_idle()
            return manager.create(store,raw['profile'],bool(raw.get('overwrite',False)))
    @app.get('/api/m1/runs/current')
    def current_run(preview_after:int|None=None,preview_run:str|None=None):
        # Native protocol and profile snapshots already contain JSON values.
        # Avoid recursively copying all nested preview vertices in FastAPI.
        return JSONResponse(manager.current(preview_after,preview_run))
    @app.post('/api/m1/runs/{identifier}/stop')
    def stop(identifier:str): return manager.stop(identifier)

    def paths_for(raw):
        paths=raw.get('paths')
        if not paths:
            run=manager.current()
            if run is None or (raw.get('run_id') and raw['run_id']!=run['id']): raise ValueError('Choose a stream file or a current simulation')
            paths=[s['path'] for s in run['streams'] if Path(s['path']).is_file()]
        if not isinstance(paths,list) or not 1<=len(paths)<=16: raise ValueError('Select one to sixteen stream files')
        resolved=[store.resolve_path(p) for p in paths]
        # A remembered live path may have completed while its browser was closed.
        resolved=[p.with_suffix('') if not p.exists() and p.name.endswith('.tpstream.part') and p.with_suffix('').is_file() else p for p in resolved]
        if len({os.path.normcase(str(p)) for p in resolved})!=len(resolved): raise ValueError('A stream may be selected only once')
        return resolved

    def analysis_store(raw, reload=False):
        nonlocal imported,import_key
        if not raw.get('paths'):
            with manager.lock:
                run=manager.run
                if run is None or (raw.get('run_id') and raw['run_id']!=run['id']):
                    raise ValueError('Choose stream files or the current simulation')
                return manager.analysis
        paths=paths_for(raw)
        key=tuple((str(p),p.stat().st_dev,p.stat().st_ino) for p in paths)
        with controls:
            if reload or imported is None or import_key!=key:
                next_store=AnalysisStore()
                try: next_store.open_files(paths, workers=raw.get('workers', 0))
                except BaseException: next_store.close(); raise
                previous=imported; imported=next_store; import_key=key
                if previous is not None: previous.close()
            return imported

    async def scan(request,raw,batch=False):
        cancelled=threading.Event()
        source=analysis_store(raw)
        task=asyncio.create_task(run_in_threadpool(source.query,raw,cancel=cancelled))
        try:
            while not task.done():
                if await request.is_disconnected():
                    cancelled.set()
                    try: await task
                    except ValueError: pass
                    raise HTTPException(499,'Analysis cancelled')
                await asyncio.wait({task},timeout=.2)
            result=await task
            return result if batch else result[0]
        finally:
            cancelled.set()

    @app.post('/api/m1/analysis')
    async def analysis(request:Request,raw:dict):
        return await run_in_threadpool(JSONResponse,await scan(request,raw))

    @app.post('/api/m1/analysis/batch')
    async def analysis_batch(request:Request,raw:dict):
        return await run_in_threadpool(JSONResponse,await scan(request,raw,batch=True))

    @app.post('/api/m1/pmt-response')
    def pmt_response(raw:dict):
        from .analog_pmt import operating_point
        return operating_point(raw['entry'],raw.get('hv_V'),raw.get('load_ohm',50),raw.get('polarity','negative'))

    def pulse_previews(raw):
        source=analysis_store(raw)
        if raw.get('paths'):
            previews=[]
            for b in source.buffers.values():
                with b.lock: previews.extend(b.previews)
        else:
            with manager.lock: previews=list(manager.run.get('trajectories',[])) if manager.run else []
        return source,previews

    @app.post('/api/m1/pulse/previews')
    def preview_list(raw:dict):
        keys=('event_id','role','category','detectors','tracks','pulse_origins','cherenkov_births')
        if raw.get('paths') and 'after' in raw:
            # Each file has an independent cursor. Bound each response, even if
            # the Simulation tab is first opened after the entire import.
            with controls:
                source=imported
                if source is None or [store.resolve_path(p) for p in raw['paths']]!=[Path(b.path) for b in source.buffers.values()]:
                    raise Conflict('The selected stream session has changed.')
            if not isinstance(raw['after'],dict):
                raise ValueError('Invalid trajectory cursor')
            rows=[];cursors={}
            for role,b in source.buffers.items():
                start=raw['after'].get(role,0)
                if type(start) is not int or start<0:raise ValueError('Invalid trajectory cursor')
                with b.lock:
                    batch=b.previews[start:start+32]
                cursors[role]=start+len(batch)
                rows.extend({k:p[k] for k in keys if k in p} for p in batch)
            return {'previews':rows,'cursors':cursors}
        _,previews=pulse_previews(raw)
        return [{k:p[k] for k in keys if k in p} for p in previews]

    @app.post('/api/m1/density-bank')
    def density_bank(raw:dict):
        return JSONResponse(analysis_store(raw).density_bank(raw))

    @app.post('/api/m1/cathode-map')
    def cathode_map(raw:dict):
        return analysis_store(raw).hit_map(raw)

    @app.post('/api/m1/persistence')
    def persistence(raw:dict):
        source=analysis_store(raw)
        return source.persistence_preview(raw) if raw.get('background') else source.persistence(raw)

    def event_optics(raw, include_arrivals=False):
        source=analysis_store(raw)
        role=raw.get('role');event=raw.get('event_id');buffer=source.buffers.get(role)
        if buffer is None or type(event) is not int or event<0:raise ValueError('This event has not arrived yet. Select a loaded event.')
        if event>=buffer.count:
            # A validated preview can precede the batched EVNT commit, both
            # during transport and during file import. Use its server-owned
            # onset snapshot until the complete event spool catches up.
            _,previews=pulse_previews(raw)
            preview=next((p for p in previews if p['role']==role and p['event_id']==event),None)
            if preview is None:raise ValueError('This event has not arrived yet. Select a loaded event.')
            onsets=preview['analog_onsets_ns']
            arrivals=preview.get('cathode_arrivals_ns')
            if include_arrivals and arrivals is None:raise ValueError('Cathode arrival times for this event are still arriving.')
            accepted=preview['energy_accepted']
            origins=preview['light_origins']
            onsets=[v if accepted[i] else [] for i,v in enumerate(onsets)]
            origins=[v if accepted[i] else [] for i,v in enumerate(origins)]
            if arrivals is not None:arrivals=[v if accepted[i] else [] for i,v in enumerate(arrivals)]
        else:
            # A single event must never wait behind an all-event density scan.
            # Each append-only cloud owns its short read/close lock.
            onsets=[cloud.event(event) for cloud in buffer.pulses]
            origins=[cloud.event_origins(event) for cloud in buffer.pulses]
            arrivals=[cloud.event_arrivals(event) for cloud in buffer.pulses] if include_arrivals else None
        return onsets,arrivals,buffer.header['analog_response'],event,role,origins,buffer.header.get('light_components',[])

    @app.post('/api/m1/pulse')
    def event_pulse(raw:dict):
        from .analog_pmt import pulse_plot
        onsets,_,responses,event,role,_,_=event_optics(raw)
        return pulse_plot(onsets,responses,event,role)

    @app.post('/api/m1/event-plots')
    def event_plots(raw:dict):
        from .analog_pmt import pulse_plot
        from .cathode_arrivals import arrival_plot
        onsets,arrivals,responses,event,role,origins,components=event_optics(raw,include_arrivals=True)
        from .light_origin import NAMES
        from .analog_pmt import evaluate
        import numpy as np
        pulse=pulse_plot(onsets,responses,event,role)
        provenance=[];contributions=[]
        for d in range(2):
            tags=np.asarray(origins[d],dtype='u1').reshape(-1,2)
            counts=[int(np.count_nonzero(tags[:,0]==v)) for v in (1,2)]
            code=(1 if counts[0] else 0)|(2 if counts[1] else 0)
            ids,ns=np.unique(tags[tags[:,0]==2,1],return_counts=True)
            provenance.append(dict(detector='AB'[d],kind=NAMES[code],scintillation=counts[0],cherenkov=counts[1],births=[dict(**components[int(i)],photons=int(n)) for i,n in zip(ids,ns)]))
            x=np.asarray(pulse['series'][d]['points'])[:,0]
            for mechanism,name,color in ((1,'Scintillation','#198f8c'),(2,'Cherenkov','#dc8b26')):
                if counts[mechanism-1]:contributions.append(dict(name=f'{name} · {"AB"[d]}',color=color,dashed=bool(d),points=np.column_stack((x,evaluate(np.asarray(onsets[d])[tags[:,0]==mechanism],responses[d],x,current=True))).tolist()))
        # A single response always binds both views to the same immutable event.
        return dict(pulse=pulse,contributions=contributions,provenance=provenance,
                    arrivals=arrival_plot(arrivals,event,role,raw.get('bins',120)))

    @app.post('/api/m1/analysis/info')
    def analysis_info(raw:dict):
        from .streams import inspect_stream
        with controls:
            if manager.active(): raise Conflict('Stop the current simulation before opening streams.')
            paths=paths_for(raw)
            key=tuple((str(p),p.stat().st_dev,p.stat().st_ino) for p in paths)
            attached=imported is not None and import_key==key and imported.progress()['loading']
            if not attached: require_idle()
            streams=[inspect_stream(p) for p in paths]
            # Validate the embedded settings before changing the displayed data
            # source. Preserve the original snapshot for display and export.
            for stream in streams: store.inspect(stream['header'].get('profile',{}))
            source=analysis_store(raw,reload=not attached)
            return {'streams':streams,'profile':streams[0]['header']['profile'],
                    'roles':list(dict.fromkeys(s['header']['role'] for s in streams)),
                    'progress':source.progress()}

    @app.get('/api/m1/import/status')
    def import_status():
        with controls:
            if imported is None: return {'loading':False,'streams':[],'total_events':0,'loaded_bytes':0,'total_bytes':0,'error':None}
            return imported.progress()

    @app.post('/api/m1/import/stop')
    def stop_import():
        with controls:
            if imported is None: raise ValueError('No stream import is open.')
            return imported.stop_import()

    @app.post('/api/m1/analysis/export')
    async def analysis_export(request:Request,raw:dict):
        format=raw.get('format','csv')
        if format not in ('csv','txt'): raise ValueError('Export format must be csv or txt')
        result=await scan(request,raw)
        def rows():
            output=io.StringIO(); writer=csv.writer(output,delimiter=',' if format=='csv' else '\t')
            writer.writerow(['series','detector','primary','metric','unit','bin_left','bin_right','count','events','valid','missing','underflow','overflow'])
            yield output.getvalue(); output.seek(0); output.truncate()
            for series in result['series']:
                for a,b,count in zip(series['edges'],series['edges'][1:],series['counts']):
                    writer.writerow([series['label'],series['detector'],series['primary'],result['metric'],result['unit'],a,b,count,series['events'],series['valid'],series['missing'],series['underflow'],series['overflow']])
                    yield output.getvalue(); output.seek(0); output.truncate()
        return StreamingResponse(rows(),media_type='text/csv' if format=='csv' else 'text/plain',headers={'Content-Disposition':f'attachment; filename="TwinPALS-{result["metric"]}.{format}"'})

    @app.post('/api/m1/browse')
    def browse(raw:dict):
        import tkinter as tk
        from tkinter import filedialog
        kind=raw.get('kind'); initial=store.resolve_path(raw.get('initial') or store.ui['dialog_paths'].get(kind) or '.')
        initialdir=str(initial if initial.is_dir() else initial.parent)
        entry_kind=next((spec for family,spec in FAMILIES.items() if kind in ('open_entry_'+family,'save_entry_'+family)),None)
        if not entry_kind and kind not in ('folder','open_profile','save_profile','open_stream','save_stream','open_table','open_materials','save_materials','open_app_profile','save_app_profile','open_m2','save_m2','open_m3','save_m3','open_pulses','save_pulses','open_components','save_components'): raise ValueError('Unknown file chooser kind')
        window=tk.Tk(); window.withdraw(); window.attributes('-topmost',True)
        try:
            options={'parent':window,'initialdir':initialdir,'title':'TwinPALS'}
            if kind=='folder': value=filedialog.askdirectory(**options)
            else:
                profile='profile' in kind
                app_profile='app_profile' in kind
                material='materials' in kind
                options['filetypes']=[('TwinPALS profile','*.tpprofile')] if app_profile else [('TwinPALS materials','*.tpcatalogue')] if material else [('TwinPALS Module 1','*.tpm1')] if profile else [('Optical property table','*.csv *.txt *.tsv *.dat')] if kind=='open_table' else [('TwinPALS stream','*.tpstream *.tpstream.part')]
                special={'m3':('TwinPALS Module 3','.tpm3'),'m2':('TwinPALS Module 2','.tpm2'),'pulses':('TwinPALS pulse stream','.tppulses'),'components':('TwinPALS components','.tpcomponents')}.get(kind.split('_',1)[-1])
                if special: options['filetypes']=[(special[0],'*'+special[1]+(' *.tppulses.part' if kind=='open_pulses' else ''))]
                if entry_kind: options['filetypes']=[('TwinPALS material entry','*'+entry_kind['extension'])]
                if kind.startswith('save'):
                    options['defaultextension']='.tpprofile' if app_profile else '.tpcatalogue' if material else '.tpm1' if profile else '.tpstream'
                    if special: options['defaultextension']=special[1]
                    if entry_kind: options['defaultextension']=entry_kind['extension']
                    options['confirmoverwrite']=False  # The application owns the replacement confirmation.
                    if not initial.is_dir(): options['initialfile']=initial.name
                    value=filedialog.asksaveasfilename(**options)
                else: value=filedialog.askopenfilename(**options)
            return {'path':str(value) if value else None}
        finally: window.destroy()

    from .m2_api import register as register_module2
    register_module2(app,store,pulse_manager,controls,require_shared_idle)
    from .m3_api import register as register_module3
    register_module3(app,store,lifetime_manager,controls)

    @app.api_route('/api/{path:path}',methods=['GET','POST','PUT','PATCH','DELETE'])
    def unknown_api(path:str):
        raise HTTPException(404,'This API operation is not available.')

    frontend=root/'frontend/dist'
    mount_legal_notices(app, root)
    if frontend.exists(): app.mount('/',StaticFiles(directory=frontend,html=True),name='webui')
    else:
        @app.get('/')
        def unbuilt(): return JSONResponse({'detail':'Build frontend with npm run build in frontend/'},status_code=503)
    return app
