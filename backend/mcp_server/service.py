# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Local control plane with independently authenticated, GET-only observer routes."""
from functools import lru_cache
import hmac
import logging
import os
import secrets
import socket
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from backend.legal_notices import mount_legal_notices
from backend.release_updates import release_status
from starlette.middleware.trustedhost import TrustedHostMiddleware

from backend.app import application_root
from backend.instance import WorkspaceLock
from backend.windows_tray import TrayRegistration
from backend.m1_store import atomic_json
from . import platform
from .engine import Engine, read
from .tools import invoke
from .observer import archived_charts, query_charts


class Service:
    def __init__(self,data,no_logon=False,notice=None):
        self.engine=Engine(data,no_logon,notice)
        self.control=secrets.token_urlsafe(32)
        self.viewer=secrets.token_urlsafe(32)
        self.observer_url=''
        self.server=None

    def overview(self,study=None):
        q=self.engine.q
        if study:
            studies=q.rows('SELECT id,name,created FROM studies WHERE id=?',study)
            runs=q.rows('SELECT * FROM runs WHERE study=? ORDER BY rowid',study)
            events=q.rows('SELECT * FROM activity WHERE study=? ORDER BY id DESC LIMIT 50',study)
        else:
            studies=q.rows('SELECT id,name,created FROM studies ORDER BY created DESC LIMIT 200')
            runs=q.rows("SELECT * FROM (SELECT *,rowid AS submission_order FROM runs WHERE status IN ('queued','running','cancelling') UNION ALL SELECT * FROM (SELECT *,rowid AS submission_order FROM runs WHERE status NOT IN ('queued','running','cancelling') ORDER BY updated DESC LIMIT 250)) ORDER BY submission_order")
            events=q.rows('SELECT * FROM activity ORDER BY id DESC LIMIT 50')
            listed={s['id'] for s in studies}
            for sid in dict.fromkeys(r['study'] for r in runs if r['study'] not in listed):
                studies.extend(q.rows('SELECT id,name,created FROM studies WHERE id=?',sid))
        return dict(studies=studies,runs=runs,activity=events,cpu_total=self.engine.limit)

    def detail(self,run_id):
        e=self.engine
        with e.lock:
            run=e.q.get_run(run_id)
            task=e.active.get(run_id) if run['status'] in ('running','cancelling') else None
            science=task and task['science']
            state=dict(task['last']) if task else {}
        folder=e.q.folder(run)
        manifest=study_manifest(folder.parent.parent/'manifest.json')
        steps=manifest['steps']
        item=next(s for s in steps if s['id']==run_id)
        context=dict(objective=manifest['objective'],step=steps.index(item)+1,steps=len(steps),
                     operation=item['operation'],parent=next((s['key'] for s in steps if s['id']==item['parent']),None),
                     queries=[q['name'] for q in item['queries']])
        receipt={}
        plots=[]
        trajectories=state.pop('trajectories',[])
        profile=item['profile']
        geometry=folder/'geometry.json'
        committed=run['status'] in ('completed','partial')
        if committed:
            receipt=read(folder/'receipt.json',{})
            if receipt:
                state=receipt['metrics']
                profile=receipt['profile']
                plots,trajectories=committed_preview(folder,run['module'])
        elif science and state:
            profile=science.profile
            with science.workspace.lock:
                if not science.workspace.closed:
                    stamp=time.monotonic()
                    if stamp-task.get('plotted',0)>3:
                        task['plotted']=stamp
                        try:
                            task['charts']=science.observer_charts()
                        except (AttributeError,ValueError,IndexError):
                            task['charts']=[]
                    plots=task.get('charts',[])
        recorded=bool(receipt or science and state)
        if item['operation']=='import' and not recorded:
            profile={}
        inputs=receipt.get('inputs',item['inputs'])
        return dict(run=run,profile=profile,metrics=state,context=context,charts=plots,
                    input_files=[Path(p['path']).name for p in inputs],parent=item['parent'],
                    inputs=inputs,plot=plots[0] if plots else None,trajectories=trajectories,
                    geometry=bool(run['module']==1 and recorded and geometry.is_file()),
                    entries=read(geometry,[]) if run['module']==1 and recorded else [],
                    saved_queries=list(receipt.get('queries',{})))

    def comparison(self,run_id):
        run=self.engine.q.get_run(run_id)
        manifest=study_manifest(self.engine.q.root/run['study']/'manifest.json')
        item=next(s for s in manifest['steps'] if s['id']==run_id)
        peers=[s for s in manifest['steps'] if (s['module'],s['operation'])==(item['module'],item['operation'])]
        runs={r['id']:r for r in self.engine.q.study(run['study'])['runs']}
        names={s['id']:s['key'] for s in manifest['steps']}
        keys,settings=varying_settings(tuple(s['id'] for s in peers),self.engine.q.root/run['study']/'manifest.json')
        rows=[]
        for peer in peers:
            r=runs[peer['id']]
            values={}
            if r['status'] in ('completed','partial'):
                values=committed_counts(self.engine.q.folder(r))
            rows.append(dict(id=r['id'],name=r['name'],status=r['status'],settings=settings[r['id']],
                             source=names.get(peer['parent']) or ', '.join(Path(p['path']).name+' · '+p['edge_sha256'][:8] for p in peer['inputs']),
                             **values))
        return dict(fields=keys,rows=rows,documents=study_documents(self.engine.q.root/run['study']))

    def query_artifact(self,run_id,name):
        run=self.engine.q.get_run(run_id)
        folder=self.engine.q.folder(run)
        receipt=read(folder/'receipt.json',{}) if run['status'] in ('completed','partial') else {}
        if receipt.get('queries',{}).get(name)!='query-'+name+'.json':
            raise ValueError('No committed query with this name.')
        return folder/receipt['queries'][name]


def study_documents(root):
    docs=[]
    if (root/'report.md').is_file():
        docs.append(dict(id='report',name='Study report',file='report.md'))
    for evidence in sorted((root/'documents').glob('*/evidence.json')):
        doc=document_info(evidence)
        if doc:
            docs.append(doc)
    return docs


@lru_cache(maxsize=256)
def document_info(evidence):
    meta=read(evidence,{})
    name=Path(meta.get('path','')).name
    if not name or not (evidence.parent/name).is_file():
        return None
    return dict(id=evidence.parent.name,name=name,file=name)


@lru_cache(maxsize=2048)
def committed_counts(folder):
    state=read(folder/'receipt.json',{}).get('metrics',{})
    return {k:state[k] for k in ('completed','total_events','waveforms','accepted','total_processed') if k in state}


@lru_cache(maxsize=16)
def varying_settings(ids,path):
    def flatten(value, prefix, out):
        if isinstance(value,dict):
            for key,child in value.items():
                if key not in ('threads','workers','output_paths','output_path','input_paths'):
                    flatten(child,(*prefix,key),out)
        elif isinstance(value,list):
            for i,child in enumerate(value):
                label='AB'[i] if i<2 and prefix[-1:] in (('channels',),('detectors',)) else str(i+1)
                flatten(child,(*prefix,label),out)
        else:
            out[' / '.join(prefix)]=value
    wanted=set(ids)
    values={}
    for step in study_manifest(path)['steps']:
        if step['id'] in wanted:
            flat={}
            if step['operation']!='import':
                flatten(step['profile'],(),flat)
            values[step['id']]=flat
    all_keys=dict.fromkeys(k for row in values.values() for k in row)
    keys=[k for k in all_keys if len({row.get(k) for row in values.values()})>1]
    return keys,{key:[row.get(k) for k in keys] for key,row in values.items()}


@lru_cache(maxsize=8)
def study_manifest(path):
    return read(path)


@lru_cache(maxsize=12)
def committed_preview(folder,module):
    preview=read(folder/'preview.json',{})
    plots=preview.get('charts') if preview.get('version')==2 else archived_charts(folder,module)
    return plots or [],preview.get('trajectories',[])


def web_app(service):
    app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=['127.0.0.1','localhost','testserver'])

    @app.middleware('http')
    async def check(request:Request,next_handler):
        from fastapi.responses import JSONResponse
        path=request.url.path
        token=request.headers.get('authorization','')
        if path.startswith('/control/'):
            if request.headers.get('origin') or not hmac.compare_digest(token,'Bearer '+service.control):
                return JSONResponse({'detail':'Control credential required'},403)
        elif path.startswith('/observe/api/'):
            if request.method!='GET' or not hmac.compare_digest(token,'Bearer '+service.viewer):
                return JSONResponse({'detail':'Read-only observer credential required'},403)
        result=await next_handler(request)
        result.headers['Referrer-Policy']='no-referrer'
        result.headers['X-Content-Type-Options']='nosniff'
        if path.startswith(('/control/','/observe')):
            result.headers['Cache-Control']='no-store'
        return result

    @app.get('/control/ping')
    def ping():
        return {'service':'TwinPALS','pid':os.getpid()}

    @app.post('/control/tool')
    def call(raw:dict):
        try:
            return {'value':invoke(service,raw['name'],raw.get('arguments',{}))}
        except (ValueError,KeyError,IndexError,TypeError,OSError) as exc:
            return {'error':str(exc)}
        except Exception:
            logging.exception('MCP tool failed')
            return {'error':'Internal TwinPALS error. See the local service.log.'}

    @app.post('/control/shutdown')
    def shutdown():
        service.server.should_exit=True
        return {'stopping':True}

    @app.get('/observe/api/status')
    def overview(study:str|None=None):
        return service.overview(study)

    @app.get('/observe/api/releases/latest')
    def releases(refresh: bool = False, manual: bool = False):
        return release_status(service.engine.q.data, refresh=refresh, manual=manual)

    @app.get('/observe/api/runs/{run_id}')
    def detail(run_id:str):
        try:
            return service.detail(run_id)
        except ValueError as exc:
            raise HTTPException(404,str(exc)) from exc

    @app.get('/observe/api/runs/{run_id}/comparison')
    def comparison(run_id:str):
        try:
            return service.comparison(run_id)
        except ValueError as exc:
            raise HTTPException(404,str(exc)) from exc

    @app.get('/observe/api/runs/{run_id}/documents/{doc_id}')
    def document(run_id:str,doc_id:str):
        try:
            run=service.engine.q.get_run(run_id)
        except ValueError as exc:
            raise HTTPException(404,str(exc)) from exc
        root=service.engine.q.root/run['study']
        doc=next((d for d in study_documents(root) if d['id']==doc_id),None)
        if doc is None:
            raise HTTPException(404,'Unknown study document')
        path=root/'report.md' if doc_id=='report' else root/'documents'/doc_id/doc['file']
        return FileResponse(path,filename=doc['file'],media_type='application/octet-stream')

    @app.get('/observe/api/runs/{run_id}/queries/{name}/charts')
    def saved_charts(run_id:str,name:str):
        try:
            path=service.query_artifact(run_id,name)
            return {'charts':query_charts(path.parent,run_id,name)}
        except ValueError as exc:
            raise HTTPException(404,str(exc)) from exc

    @app.get('/observe/api/runs/{run_id}/queries/{name}')
    def saved_query(run_id:str,name:str):
        try:
            path=service.query_artifact(run_id,name)
        except ValueError as exc:
            raise HTTPException(404,str(exc)) from exc
        return FileResponse(path,filename=path.name,media_type='application/json')

    mount_legal_notices(app, application_root())
    dist=application_root()/'frontend/dist'
    @app.get('/observe')
    def dashboard():
        return FileResponse(dist/'index.html')
    @app.get('/favicon.svg')
    def favicon_svg():
        return FileResponse(dist/'favicon.svg',media_type='image/svg+xml')
    @app.get('/favicon.ico')
    def favicon_ico():
        return FileResponse(dist/'favicon.ico',media_type='image/x-icon')
    if (dist/'assets').is_dir():
        app.mount('/assets',StaticFiles(directory=dist/'assets'))
    return app


def serve(data,no_logon=False):
    root=data/'studies'
    try:
        owner=WorkspaceLock(root/'service')
    except RuntimeError:
        return 0  # Another client started the same coordinator.
    service=None
    tray=TrayRegistration('mcp',data)
    try:
        platform.child_job()
        tray.__enter__()
        with socket.socket() as listener:
            if hasattr(socket,'SO_EXCLUSIVEADDRUSE'):
                listener.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
            listener.bind(('127.0.0.1',0))
            tray.port=listener.getsockname()[1]
            service=Service(data,no_logon,tray.notify)
            base=f'http://127.0.0.1:{tray.port}'
            service.observer_url=base+'/observe#'+service.viewer
            service.server=uvicorn.Server(uvicorn.Config(web_app(service),host='127.0.0.1',access_log=False,log_level='warning'))
            def activity():
                with service.engine.lock:
                    count=len(service.engine.active)
                if count:
                    return f'{count} active study step' + ('s' if count != 1 else '')
                return 'Study steps queued' if service.engine.pending() else ''
            def open_observer(study):
                target=base+'/observe'+('?study='+study if study else '')+'#'+service.viewer
                webbrowser.open(target)
            tray.attach(activity,open_observer,lambda: setattr(service.server,'should_exit',True),lambda: service.server.started)
            atomic_json(root/'endpoint.json',{'url':base,'token':service.control,'pid':os.getpid()})
            service.server.run(sockets=[listener])
    finally:
        tray.phase='Stopping'
        try:
            if service:
                try:
                    service.engine.close()
                finally:
                    (root/'endpoint.json').unlink(missing_ok=True)
        finally:
            tray.__exit__(None,None,None)
            owner.close()
    return 0

