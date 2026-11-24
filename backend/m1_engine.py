# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Own the native processes; stream files are written incrementally by Geant4."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid
from . import __version__
from .native_runtime import engine_path, engine_environment, engine_status
from .m1_store import Conflict, atomic_json, encode
from .m1_resolve import resolve_profile
from .user_errors import friendly_error
from .m1_models import referenced_ids
from .live_analysis import AnalysisStore
from .storage_health import ensure_capacity,exhausted,space_message,StorageSpaceError

ACTIVE = ('queued','running','stopping')
ROLES = {'na22':['na22_prompt','na22_annihilation'], 'co60':['co60_1173','co60_1332']}


def native_path(path):
    value = str(path)
    if os.name == 'nt' and len(value) >= 240 and not value.startswith('\\\\?\\'):
        return '\\\\?\\UNC\\' + value[2:] if value.startswith('\\\\') else '\\\\?\\' + value
    return value


class RunManager:
    def __init__(self, root):
        self.root=Path(root); self.lock=threading.RLock(); self.run=None
        self.process=None; self.thread=None; self.cancel=threading.Event()
        self.started=None; self.ended=None; self.job_dir=None
        self.analysis=None
        self.preview_revision=0; self.preview_versions={}

    def active(self):
        with self.lock: return self.run is not None and self.run['status'] in ACTIVE

    def current(self, preview_after=None, preview_run=None):
        with self.lock:
            if self.run is None: return None
            # The pulse endpoint reconstructs one selected preview. Polling the
            # job must not repeatedly transfer every retained PE time to the UI.
            value=copy.deepcopy({k:v for k,v in self.run.items() if k!='trajectories'})
            history=self.run.get('trajectories',[])
            delta=(preview_after is not None and 0<=preview_after<=self.preview_revision
                   and (preview_run is None or preview_run==self.run['id']))
            value['trajectory_revision']=self.preview_revision
            if delta:
                # Order is authoritative, including evictions from every preview
                # bucket. Retained objects are immutable after publication.
                value['trajectory_order']=[self.preview_key(t) for t in history]
                history=[t for t in history if self.preview_versions.get(self.preview_key(t),0)>preview_after]
            value['trajectories']=[{k:v for k,v in t.items() if k not in ('analog_onsets_ns','cathode_arrivals_ns','light_origins')} for t in history]
            elapsed=max(0,(self.ended or time.monotonic())-(self.started or time.monotonic()))
            value['elapsed_s']=elapsed
            completed=value['completed']; rate=completed/elapsed if elapsed>0 and completed>0 else 0
            value['rate_events_s']=rate
            eta=(value['total']-completed)/rate if value['status']=='running' and completed>=2 and rate>0 else None
            # Progress-rate estimates include initialization. A stalled worker has no firm ETA.
            if time.monotonic()-self.last_progress>30 or value['message'] in ('Verifying stream files','Closing stream','Finalizing streams'): eta=None
            value['eta_s']=max(0,eta) if eta is not None else None
            value['estimated_finish']=(datetime.now().astimezone()+timedelta(seconds=eta)).isoformat() if eta is not None else None
            queued_wait=0.
            for stream in value['streams']:
                remaining=stream['total']-stream['completed']
                # Co projections share one physical cascade; rate_events_s counts projections.
                stream_rate=rate/2 if value['profile']['source']=='co60' else rate
                se=remaining/stream_rate if eta is not None and stream_rate>0 and stream['status'] in ACTIVE else None
                if value['profile']['source']=='na22' and se is not None:
                    own_remaining=se
                    se+=queued_wait
                    queued_wait+=own_remaining
                stream['eta_s']=se
                stream['estimated_finish']=(datetime.now().astimezone()+timedelta(seconds=se)).isoformat() if se is not None else None
                if self.analysis is not None and stream['role'] in self.analysis.buffers:
                    stream['outcomes']=self.analysis.buffers[stream['role']].outcomes()
            return value

    @staticmethod
    def preview_key(trajectory):
        return f"{trajectory['role']}:{trajectory['event_id']}"

    def create(self, store, raw, overwrite=False):
        profile=store.freeze(raw); entries=store.entries; resolved,warnings=resolve_profile(profile,entries)
        material_names={e['id']:e['name'] for e in entries if e['id'] in referenced_ids(profile)}
        status=engine_status(self.root)
        if not status['available']: raise ValueError(status['message'])
        if resolved['threads']>1 and not status.get('multithreaded'): raise ValueError('This Geant4 worker has no multicore support')
        if status.get('worker_version')!=__version__: raise ValueError('The native worker and application versions must match')
        paths=[store.resolve_path(p) for p in profile['run']['output_paths']]
        ensure_capacity([store.root,*[p.parent for p in paths]])
        if len({os.path.normcase(str(p)) for p in paths})!=2: raise ValueError('Choose two different stream paths')
        with self.lock:
            if self.active() or (self.thread and self.thread.is_alive()): raise Conflict('The current simulation is running or finalizing')
            for path in paths:
                for candidate in (path,Path(str(path)+'.part')):
                    if candidate.exists() and not overwrite: raise Conflict(f'Output exists: {candidate}. Confirm replacement first.')
                    if candidate.exists() and not candidate.is_file(): raise ValueError('Output destination is not a file')
            if profile['run']['auto_seed']:
                # Resolve exactly once, only after launch is accepted. The actual
                # value travels with the run, headers and reusable M1 snapshot.
                seed=time.time_ns()%2147483646+1
                if self.run and seed==self.run['profile']['run']['seed']: seed=seed%2147483646+1
                profile['run']['seed']=seed
                resolved['seed']=seed
            identifier=uuid.uuid4().hex
            directory=store.root/'.twinpals-runs'/identifier
            directory.mkdir(parents=True)
            for path in paths: path.parent.mkdir(parents=True,exist_ok=True)
            roles=ROLES[profile['source']]; count=profile['run']['events']
            counts=[count,profile['run']['secondary_events'] if profile['source']=='na22' else count]
            streams=[{'role':role,'path':str(path)+'.part','destination':str(path),'completed':0,'total':n,'status':'queued','eta_s':None,'estimated_finish':None} for role,path,n in zip(roles,paths,counts)]
            self.run={'id':identifier,'status':'queued','completed':0,'total':sum(counts),'elapsed_s':0.,'rate_events_s':0.,'eta_s':None,'estimated_finish':None,
                      'threads':resolved['threads'],'message':'Initializing Geant4','streams':streams,'trajectories':[],'profile':profile,'material_names':material_names,'warnings':warnings,'pmt_snapshot':[e for e in entries if e['id'] in [d['pmt_id'] for d in profile['detectors']]]}
            self.cancel.clear(); self.started=time.monotonic(); self.ended=None; self.last_progress=self.started
            self.preview_revision=0; self.preview_versions={}
            from .preview_history import PreviewHistory
            self.preview_history=PreviewHistory(profile['run']['trajectory_sample_limit'])
            self.job_dir=directory
            if self.analysis is not None: self.analysis.close()
            self.analysis=AnalysisStore()
            for index,stream in enumerate(streams):
                job_number=index if profile['source']=='na22' else 0
                seed=((resolved['seed']-1+job_number*104729)%2147483646)+1
                header={'format':'twinpals-stream','version':6,'run_id':identifier,'stream_id':uuid.uuid4().hex,'analog_response':resolved['analog_response'],
                        'role':stream['role'],'source':resolved['source'],'profile':profile,'physics':resolved['physics'],
                        'resolved':{'detectors':[{k:d[k] for k in ('id','front_mm','axis')} for d in resolved['detectors']]},
                        'material_names':material_names,'pmt_snapshot':self.run['pmt_snapshot'],
                        'settings_sha256':hashlib.sha256(encode(profile).encode()).hexdigest(),
                        'created_at':datetime.now(timezone.utc).isoformat(),'application_version':__version__,'engine':status,
                        'seed':seed,'events':stream['total'],'units':{'position':'mm','energy':'keV','time':'ns','direction':'unit_vector'},
                        'time_origin':'per-stream primary emission; nuclear offsets retained in primary_emission_times_ns',
                        'detectors':['A','B'],'count_semantics':'QE-accepted photons at the photocathode',
                        'depth_semantics':'axial distance from crystal front plane'}
                self.analysis.register(header,stream['path'])
            atomic_json(directory/'module1.tpm1',profile)
            self.thread=threading.Thread(target=self._execute,args=(directory,resolved,status,paths),daemon=True,name='TwinPALS-Geant4')
            self.thread.start()
            return self.current()

    def _execute(self,directory,resolved,engine,paths):
        from .streams import inspect_stream
        storage_failure=None
        next_storage_check=0.
        try:
            with self.lock:
                if not self.cancel.is_set(): self.run['status']='running'
            roles=ROLES[resolved['source']]
            jobs=[[0],[1]] if resolved['source']=='na22' else [[0,1]]
            for job_number,indices in enumerate(jobs):
                if self.cancel.is_set(): break
                job=copy.deepcopy(resolved)
                job['source_role']=roles[indices[0]] if resolved['source']=='na22' else 'co60'
                job['events']=self.run['streams'][indices[0]]['total']
                job['seed']=((resolved['seed']-1+job_number*104729)%2147483646)+1
                # The file is the lossless queue. UI analysis must never hold
                # up the native writer through a full stdout pipe.
                job['output']['live_analysis']=False
                job['streams']=[]
                for index in indices:
                    stream=self.run['streams'][index]
                    header=self.analysis.buffers[stream['role']].header
                    job['streams'].append({'role':stream['role'],'path':native_path(str(paths[index])+'.part'),'header':header})
                    with self.lock:
                        stream['status']='running'
                        self.run['message']='Initializing '+stream['role'].replace('na22_prompt','1275 keV').replace('na22_annihilation','511 keV')
                config_path=directory/f'job-{job_number}.json'; atomic_json(config_path,job)
                with (directory/f'job-{job_number}.log').open('w',encoding='utf-8') as log:
                    process=subprocess.Popen([str(engine_path(self.root)),'--config',native_path(config_path),'--output',native_path(directory)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                                             text=True,encoding='utf-8',errors='replace',env=engine_environment(self.root),cwd=str(self.root),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    with self.lock: self.process=process
                    native_error=None
                    for line in process.stdout:
                        if storage_failure is None:
                            try:
                                if self.analysis.storage_error:raise StorageSpaceError(self.analysis.storage_error)
                                if time.monotonic()>=next_storage_check:
                                    ensure_capacity([directory,*[p.parent for p in paths]])
                                    next_storage_check=time.monotonic()+1.
                            except StorageSpaceError as exc:
                                storage_failure=str(exc)
                                self.stop(self.run['id'])
                                with self.lock:self.run['message']=storage_failure
                        try: message=json.loads(line)
                        except json.JSONDecodeError: log.write(line); continue
                        if not isinstance(message,dict): continue
                        if message.get('type')=='started':
                            for index in indices:self.analysis.follow(roles[index])
                        if message.get('type') in ('analysis_batch','analysis_header'):
                            self.analysis.feed(message)
                            continue
                        if message.get('type')=='trajectory' and 'ancestry_b64' in message:
                            import base64
                            from .provenance import decode, preview_summary
                            header=self.analysis.buffers[message['role']].header
                            tree=decode(base64.b64decode(message.pop('ancestry_b64')),message['event_id'],components=len(header['light_components']))
                            message['ancestry']=preview_summary(tree,header['light_components'],message['role'])
                        # Retained previews are already in the stream. Repeated
                        # multi-megabyte trajectory dumps are not diagnostics.
                        if message.get('type')!='trajectory':log.write(line)
                        if message.get('type')=='error': native_error=message.get('message')
                        with self.lock:
                            if message.get('type') in ('progress','finished'):
                                done=max(0,min(job['events'],int(message.get('completed',0))))
                                for index in indices: self.run['streams'][index]['completed']=done
                                self.run['completed']=sum(s['completed'] for s in self.run['streams'])
                                self.last_progress=time.monotonic()
                                if not self.cancel.is_set(): self.run['message']='Simulating'
                            elif message.get('type')=='trajectory':
                                message['pulse_origins']=[int(__import__('functools').reduce(lambda m,t:m|int(t[0]),tags,0)) for tags in message.get('light_origins',[[],[]])]
                                # Retain recent history plus each detector/category's newest example.
                                self.run['trajectories'],expired=self.preview_history.append(message)
                                for old in expired:self.preview_versions.pop(self.preview_key(old),None)
                                self.preview_revision+=1
                                self.preview_versions[self.preview_key(message)]=self.preview_revision

                    code=process.wait()
                with self.lock: self.process=None
                with self.lock: self.run['message']='Closing stream'
                reader_error=None
                for index in indices:
                    follower=self.analysis.followers.get(roles[index])
                    if follower:follower[0].set()
                # Let the next physical ensemble run while analysis consumes
                # this file's committed tail. Final completion still waits for
                # all validation, and failed workers keep their primary error.
                if code or self.cancel.is_set() or storage_failure:
                    try:self.analysis.drain([roles[index] for index in indices])
                    except Exception as exc:reader_error=exc
                if storage_failure:raise StorageSpaceError(storage_failure)
                if code and not self.cancel.is_set():
                    if reader_error is not None and (exhausted(reader_error) or self.analysis.storage_error):
                        raise StorageSpaceError(self.analysis.storage_error or space_message())
                    raise ValueError(native_error or
                        f'Geant4 worker exited unexpectedly (code {code}, 0x{code & 0xffffffff:08X}). '
                        f'Complete records remain in the .part stream. Diagnostic log: {directory / f"job-{job_number}.log"}')
                if reader_error is not None:raise reader_error
                if self.cancel.is_set(): break
                with self.lock: self.run['message']='Closing stream'
                for index in indices:
                    completion=inspect_stream(Path(str(paths[index])+'.part'))['completion']
                    if completion['status']!='completed' or completion['events']!=job['events']: raise ValueError('Native stream count/status mismatch')
                    with self.lock:
                        self.run['streams'][index]['completed']=job['events']; self.run['streams'][index]['status']='completed'
                        self.run['completed']=sum(s['completed'] for s in self.run['streams'])
            self.analysis.drain(list(self.analysis.followers))
            with self.lock:
                if self.cancel.is_set():
                    self.run['status']='cancelled'; self.run['message']='Stopped; complete records remain in .part files'
                    for s in self.run['streams']:
                        if s['status'] in ACTIVE: s['status']='cancelled'
                        b=self.analysis.buffers[s['role']]
                        if b.status!='completed': self.analysis.finish(s['role'],'cancelled',b.count)
                else:
                    self.run['message']='Finalizing streams'
                    for index,path in enumerate(paths):
                        os.replace(str(path)+'.part',path)
                        self.run['streams'][index]['path']=str(path)
                        self.analysis.finish(roles[index],'completed',self.run['streams'][index]['completed'],path)
                    self.run['status']='completed'; self.run['message']='Completed'
        except BaseException as exc:
            process=self.process
            if process and process.poll() is None:
                process.kill(); process.wait(timeout=5)
            with self.lock:
                self.run['status']='cancelled' if self.cancel.is_set() and storage_failure is None else 'failed'; self.run['message']=friendly_error(str(exc))
                for s in self.run['streams']:
                    if s['status'] in ACTIVE: s['status']=self.run['status']
        finally:
            # Failed initialization, native exceptions and force-stop all leave
            # their complete records available; no reader outlives its writer.
            if self.analysis is not None:
                try:self.analysis.drain(list(self.analysis.followers))
                except Exception as exc:
                    with self.lock:
                        if self.run['status']!='failed':
                            self.run['status']='failed';self.run['message']=friendly_error(str(exc))
            with self.lock:
                self.ended=time.monotonic(); self.process=None
                try:atomic_json(directory/'run.json',self.current())
                except OSError as exc:
                    # A full disk must not hide the in-memory failure behind an
                    # unhandled exception while writing its diagnostic record.
                    self.run['status']='failed'
                    if exhausted(exc):self.run['message']=space_message()
                    else:self.run['message']+='\nRun log could not be saved: '+str(exc)
                    for s in self.run['streams']:
                        if s['status'] in ACTIVE:s['status']='failed'

    def stop(self, identifier):
        with self.lock:
            if not self.run or self.run['id']!=identifier: raise KeyError(identifier)
            if self.run['status'] in ('queued','running'):
                self.run['status']='stopping'
                self.cancel.set(); (self.job_dir/'cancel.flag').touch()
                self.run['message']='Stopping after current events'
                threading.Thread(target=self._stop_timeout,args=(identifier,),daemon=True,name='TwinPALS-stop').start()
            return self.current()

    def _stop_timeout(self, identifier):
        deadline=time.monotonic()+4
        while time.monotonic()<deadline:
            time.sleep(.1)
            with self.lock:
                if not self.run or self.run['id']!=identifier or self.run['status'] not in ACTIVE: return
        with self.lock:
            if self.run and self.run['id']==identifier:
                process=self.process
                if process and process.poll() is None: process.terminate()

    def shutdown(self):
        if self.active(): self.stop(self.run['id'])
        thread=self.thread
        if thread: thread.join(timeout=2)
        with self.lock: process=self.process
        if process and process.poll() is None:
            process.terminate()
            try: process.wait(timeout=3)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=3)
        if thread and thread.is_alive(): thread.join(timeout=3)
        if self.analysis is not None: self.analysis.close()
