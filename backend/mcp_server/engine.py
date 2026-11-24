# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Run isolated module workspaces under a machine-wide service CPU budget."""
import json
import logging
import os
import threading
import time
from contextlib import closing
from pathlib import Path

from backend.execution import cpu_settings
from backend.m1_store import atomic_json
from . import platform
from .studies import Queue, TERMINAL, digest, fingerprint, scientific_runtime
from .workbench import Measurement, Workbench


def read(path,default=None):
    try:
        return json.loads(path.read_bytes())
    except FileNotFoundError:
        return default


class Engine:
    def __init__(self,data,no_logon=False,notice=None):
        self.notice=notice
        self.q=Queue(data)
        control_dir=self.q.root/'workbench'
        saved=self.q.data/'app-state.json'
        if saved.is_file() and not (control_dir/'app-state.json').is_file():
            atomic_json(control_dir/'app-state.json',read(saved))
        self.control=Workbench(control_dir,self.q.data/'catalogue.tpdb')
        self.limit=min(os.cpu_count() or 1,256)
        self.active={}
        self.lock=threading.RLock()
        self.wake=threading.Event()
        self.exit=threading.Event()
        self.no_logon=no_logon
        self.registered=None
        self.logon_error=None
        self.recover()
        self.thread=threading.Thread(target=self.schedule,name='TwinPALS study queue',daemon=True)
        self.thread.start()

    def pending(self):
        return bool(self.q.rows("SELECT id FROM runs WHERE status IN ('queued','running','cancelling') LIMIT 1"))

    def registration(self,enabled):
        if self.no_logon or enabled==self.registered:
            return
        try:
            platform.logon(self.q.data,enabled)
            self.registered=enabled
            self.logon_error=None
        except OSError as exc:
            message=f'Windows sign-in recovery unavailable: {exc}'
            if message!=self.logon_error:
                self.q.event(message)
            self.logon_error=message

    def recover(self):
        for run in self.q.rows("SELECT * FROM runs WHERE status IN ('running','cancelling')"):
            receipt=read(self.q.folder(run)/'receipt.json')
            if run['status']=='cancelling':
                self.set_state(run,'cancelled','Cancellation restored')
            elif receipt and receipt['run_id']==run['id'] and receipt['attempt']==run['attempt']:
                self.set_state(run,receipt['status'],'Recovered committed result',1.)
            else:
                self.set_state(run,'queued','Interrupted attempt; replay from saved inputs and seed')

    def set_state(self,run,status,message,progress=0.):
        with closing(self.q.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('UPDATE runs SET status=?,message=?,progress=?,updated=? WHERE id=?',
                       (status,message,progress,time.time(),run['id']))
            db.execute('INSERT INTO activity(at,study,run,message) VALUES(?,?,?,?)',
                       (time.time(),run['study'],run['id'],message))
            db.commit()
        if status=='failed' and self.notice:
            self.notice('failed',run['study'],run['name'])

    def submit(self,args):
        with self.lock:
            # Arm sign-in recovery ahead of the durable commit, including a
            # power cut between committing a queue row and acknowledging it.
            self.registration(True)
            try:
                result=self.q.submit(args,self.control.store)
            finally:
                self.registration(self.pending())
            self.wake.set()
            return result

    def cancel(self,run_id):
        with self.lock:
            run=self.q.get_run(run_id)
            if run['status']=='running':
                self.set_state(run,'cancelling','Cancellation requested',run['progress'])
                self.active[run_id]['cancel'].set()
            elif run['status']=='queued':
                self.set_state(run,'cancelled','Cancelled before launch')
            self.wake.set()
            return self.q.get_run(run_id)

    def retry(self,run_id):
        with self.lock:
            run=self.q.get_run(run_id)
            if run['status'] not in ('failed','cancelled','blocked'):
                raise ValueError('Only a failed, cancelled or blocked run can be retried.')
            self.set_state(run,'queued','Retry queued; saved seed and inputs retained')
            self.registration(True)
            self.wake.set()
            return self.q.get_run(run_id)

    def schedule(self):
        while not self.exit.is_set():
            try:
                with self.lock:
                    if self.exit.is_set():
                        break
                    self.dispatch()
                    self.registration(self.pending())
            except Exception:
                logging.exception('Study queue update failed')
            self.wake.wait(1)
            self.wake.clear()

    def dispatch(self):
        rows=self.q.rows("SELECT r.*,s.name AS study_name,s.parallel,s.budget,p.status AS parent_status FROM runs r JOIN studies s ON s.id=r.study LEFT JOIN runs p ON p.id=r.parent WHERE r.status='queued' ORDER BY r.rowid")
        for run in rows:
            if run['parent'] and run['parent_status'] not in ('completed','partial'):
                if run['parent_status'] in TERMINAL:
                    self.set_state(run,'blocked','Upstream run '+run['parent_status'])
                continue
            active=[a['run'] for a in self.active.values()]
            same=[r for r in active if r['study']==run['study']]
            if (len(same)>=run['parallel'] or sum(r['workers'] for r in same)+run['workers']>run['budget']
                    or sum(r['workers'] for r in active)+run['workers']>self.limit):
                continue
            with closing(self.q.connect()) as db:
                first = self.notice and not db.execute("SELECT 1 FROM runs WHERE study=? AND attempt>0 LIMIT 1",(run['study'],)).fetchone()
                db.execute("UPDATE runs SET status='running',attempt=attempt+1,updated=? WHERE id=?",(time.time(),run['id']))
            if first:
                self.notice('started',run['study'],run['study_name'])
            run=self.q.get_run(run['id'])
            task={'run':run,'cancel':threading.Event(),'science':None,'last':{}}
            self.active[run['id']]=task
            task['thread']=threading.Thread(target=self.execute,args=(task,),daemon=True,name='study-'+run['name'])
            self.q.event(f"Starting attempt {run['attempt']} on {run['workers']} CPU(s)",run['study'],run['id'])
            task['thread'].start()

    def execute(self,task):
        run=task['run']
        folder=self.q.folder(run)
        workspace=None
        try:
            manifest=self.q.manifest(run['study'])
            if manifest.get('runtime',scientific_runtime())!=scientific_runtime():
                raise ValueError('The scientific runtime changed. Resume with the recorded build or submit a new study.')
            item=next(s for s in manifest['steps'] if s['id']==run['id'])
            inputs=item['inputs']
            if item['parent']:
                parent=self.q.get_run(item['parent'])
                inputs=read(self.q.folder(parent)/'receipt.json')['outputs']
            for source in inputs:
                if source!=fingerprint(source['path']):
                    raise ValueError('Input stream changed since submission: '+source['path'])
            folder.mkdir(parents=True)
            workspace=Workbench(folder/'workbench',self.q.root/run['study']/'catalogue.tpdb')
            science=Measurement(workspace,item,folder,[v['path'] for v in inputs])
            task['science']=science
            started=time.time()
            science.start()
            if science.module==1:
                from backend.m1_models import referenced_ids
                ids=referenced_ids(science.profile)
                geometry_entries=[{k:e[k] for k in ('id','name','properties')} for e in workspace.store.entries if e['id'] in ids]
                atomic_json(folder/'geometry.json',geometry_entries)
            last_save=0.
            stopping=False
            while True:
                if (task['cancel'].is_set() or self.exit.is_set()) and not stopping:
                    stopping=True
                    science.stop()
                state=science.status()
                task['last']=state
                if state['status'] in ('stopped','completed','failed','cancelled','partial'):
                    break
                now=time.monotonic()
                if now-last_save>=1.0:
                    last_save=now
                    with closing(self.q.connect()) as db:
                        db.execute("UPDATE runs SET progress=?,message=?,updated=? WHERE id=? AND status='running'",
                                   (state.get('progress',0),state.get('phase') or state.get('message') or state['status'],time.time(),run['id']))
                task['cancel'].wait(.3) if not stopping else time.sleep(.2)
            if self.exit.is_set() or task['cancel'].is_set():
                raise InterruptedError('Interrupted')
            if state['status'] not in ('completed','partial'):
                raise ValueError(state.get('error') or state.get('message') or state['status'])
            result=science.finish()
            for source in inputs:
                if source!=fingerprint(source['path']):
                    raise ValueError('An input changed during the measurement: '+source['path'])
            preview={'plot':science.plots,'trajectories':state.pop('trajectories',[])}
            atomic_json(folder/'preview.json',preview)
            receipt=dict(run_id=run['id'],study_id=run['study'],attempt=run['attempt'],module=run['module'],
                         status=state['status'],started=started,finished=time.time(),workers=run['workers'],
                         profile=science.profile,profile_sha256=digest(science.profile),inputs=inputs,
                         catalogue_sha256=manifest['catalogue_sha256'],application_version=manifest['application_version'],
                         mcp_version=manifest['mcp_version'],runtime=scientific_runtime(),metrics=state,**result)
            with self.lock:
                if task['cancel'].is_set() or self.exit.is_set():
                    raise InterruptedError('Interrupted during export')
                atomic_json(folder/'receipt.json',receipt)
                self.set_state(run,state['status'],'Results committed',1.)
        except Exception as exc:
            with self.lock:
                if task['cancel'].is_set():
                    self.set_state(run,'cancelled','Cancelled by client')
                elif self.exit.is_set():
                    self.set_state(run,'queued','Service stopped; replay pending')
                else:
                    logging.exception('Failed study step %s',run['id'])
                    self.set_state(run,'failed',str(exc) or type(exc).__name__)
        finally:
            try:
                if workspace:
                    workspace.close()
            finally:
                with self.lock:
                    self.active.pop(run['id'],None)
                    self.wake.set()

    def close(self):
        self.exit.set()
        self.wake.set()
        self.thread.join()
        with self.lock:
            threads=[t['thread'] for t in self.active.values()]
        for thread in threads:
            thread.join()
        self.registration(self.pending())
        self.control.close()

