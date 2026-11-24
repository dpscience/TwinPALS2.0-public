# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Local control plane with independently authenticated, GET-only observer routes."""
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


class Service:
    def __init__(self,data,no_logon=False,notice=None):
        self.engine=Engine(data,no_logon,notice)
        self.control=secrets.token_urlsafe(32)
        self.viewer=secrets.token_urlsafe(32)
        self.observer_url=''
        self.server=None

    def overview(self):
        q=self.engine.q
        return dict(studies=q.rows('SELECT id,name,created FROM studies ORDER BY created DESC LIMIT 200'),
                    runs=q.rows("SELECT * FROM (SELECT * FROM runs WHERE status IN ('queued','running','cancelling') UNION ALL SELECT * FROM (SELECT * FROM runs WHERE status NOT IN ('queued','running','cancelling') ORDER BY updated DESC LIMIT 250)) ORDER BY updated DESC"),
                    activity=q.rows('SELECT * FROM activity ORDER BY id DESC LIMIT 50'),
                    cpu_total=self.engine.limit)

    def detail(self,run_id):
        e=self.engine
        q=e.q
        run=q.get_run(run_id)
        folder=q.folder(run)
        item=next(i for i in q.manifest(run['study'])['steps'] if i['id']==run_id)
        preview={}
        with e.lock:
            task=e.active.get(run_id)
            science=task and task['science']
            state=dict(task['last']) if task else {}
        if science:
            # Rendering and histogram scans occur only for the run someone watches.
            with science.workspace.lock:
                if not science.workspace.closed:
                    stamp=time.monotonic()
                    if stamp-task.get('plotted',0)>3:
                        task['plotted']=stamp
                        try:
                            task['plot']=science.preview(science.histogram())
                        except (AttributeError,ValueError,IndexError):
                            pass
                    preview={'plot':task.get('plot'),'trajectories':state.pop('trajectories',[])}
        else:
            receipt=read(folder/'receipt.json',{})
            state=receipt.get('metrics',{})
            preview=read(folder/'preview.json',{})
        profile=science.profile if science else receipt.get('profile',item['profile'])
        return dict(run=run,profile=profile,metrics=state,inputs=item['inputs'],parent=item['parent'],
                    entries=read(folder/'geometry.json',[]) if run['module']==1 else [],**preview)


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
    def overview():
        return service.overview()

    @app.get('/observe/api/releases/latest')
    def releases(refresh: bool = False, manual: bool = False):
        return release_status(service.engine.q.data, refresh=refresh, manual=manual)

    @app.get('/observe/api/runs/{run_id}')
    def detail(run_id:str):
        try:
            return service.detail(run_id)
        except ValueError as exc:
            raise HTTPException(404,str(exc)) from exc

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

