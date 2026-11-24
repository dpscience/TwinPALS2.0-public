# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""The MCP and the desktop call the same application routes and physics engines."""
import asyncio
import copy
import json
import re
import shutil
import threading
from pathlib import Path

import httpx
from backend.app import create_app
from backend.m1_store import atomic_json
from backend.m3_models import SpectrumDisplay
from backend.m3_spectra import SpectrumJournal
from .studies import MODELS, fingerprint

# Study starts and output ownership belong to the durable scheduler. Scientific
# queries, validation, component editing and setting transfers use the desktop API.
LOCAL_ACTIONS = {'/api/session','/api/client/connect','/api/client/close','/api/m1/browse',
                 '/api/m1/runs','/api/m1/import/stop','/api/m1/analysis/info','/api/m2/runs',
                 '/api/m2/analysis/open','/api/m3/start','/api/m3/restart','/api/m3/stop',
                 '/api/m3/configure','/api/m3/reset','/api/m3/plot/reset','/api/m3/workers',
                 '/api/m3/hold','/api/m3/resume','/api/files/text'}
LIVE_QUERIES = {'analysis','batch','query','monitor','state','current','pulse','previews','pmt-response',
                'density-bank','cathode-map','persistence','event-plots','export','autofit','context','status'}


def permitted(method,path,live):
    if not re.fullmatch(r'/api/(?:[a-zA-Z0-9_{}-]+/)*[a-zA-Z0-9_{}-]+',path) or path in LOCAL_ACTIONS or path.endswith('/stop'):
        return False
    if live:
        return bool(re.fullmatch(r'/api/m[123]/(?:waveforms?/\d+|[\w/-]+)',path)) and (
            path.split('/')[-1] in LIVE_QUERIES or re.fullmatch(r'/api/m[23]/waveforms?/\d+',path))
    return not re.search(r'/m[23]/(?:waveforms?|analysis|monitor|query|autofit)(?:/|$)',path)


class Workbench:
    def __init__(self, data, catalogue):
        self.app = create_app(data_dir=data,catalogue_path=catalogue)
        self.token = self.app.state.clients.acquire()
        self.lock = threading.RLock()
        self.closed = False

    @property
    def store(self):
        return self.app.state.store

    def request(self,method,path,body=None,params=None):
        async def call():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),base_url='http://127.0.0.1',trust_env=False) as client:
                res=await client.request(method,path,json=body if method!='GET' else None,params=params,
                                         headers={'x-twinpals-client':self.token})
                if res.is_error:
                    raise ValueError(res.json().get('detail',res.text))
                return res.json() if 'application/json' in res.headers.get('content-type','') else res.text
        with self.lock:
            if self.closed:
                raise ValueError('The run has finished. Read its artifacts or submit an import for a new query.')
            return asyncio.run(call())

    def close(self):
        with self.lock:
            if not self.closed:
                self.closed=True
                async def finish():
                    async with self.app.router.lifespan_context(self.app):
                        pass
                asyncio.run(finish())

    def routes(self):
        return [{'method':method,'path':r.path, 'description':getattr(r,'summary',None) or r.name}
                for r in self.app.routes if hasattr(r,'methods') and r.path.startswith('/api/')
                for method in sorted(r.methods) if permitted(method,r.path,False) or permitted(method,re.sub(r'\{\w+\}','0',r.path),True)]

    def accepts(self,method,path):
        return any(method in (getattr(route,'methods',None) or ()) and route.path!='/api/{path:path}'
                   and route.path_regex.fullmatch(path) for route in self.app.routes)


def slim(state):
    keys=('status','progress','message','phase','error','completed','total','eta_s','elapsed_s',
          'rate_events_s','waveforms','counts','target_pairs','processed_decays','source_duration_ns',
          'acquisition_rate_Hz','total_processed','accepted','rejected','measurement_ns','bytes_read',
          'streams','file_pairs','stop_reason','total_events','loaded_bytes','total_bytes')
    return {key:state[key] for key in keys if key in state}


class Measurement:
    def __init__(self, workspace, item, folder, inputs):
        self.workspace=workspace
        self.module=item['module']
        self.importing=item['operation']=='import'
        self.profile=copy.deepcopy(item['profile'])
        self.folder=folder
        self.inputs=[str(p) for p in inputs]
        self.workers=item['workers']
        state=workspace.app.state
        self.manager={1:state.manager,2:state.pulse_manager,3:state.lifetime_manager}[self.module]
        self.queries=item['queries']
        self.outputs=[]
        self.plots={}
        self.display={direction:SpectrumDisplay(individual=True) for direction in ('merged','AB','BA','SS')}

    def start(self):
        p=self.profile
        manager=self.manager
        store=self.workspace.store
        if self.importing:
            self.outputs=self.inputs
            if self.module==1:
                selection=self.workspace.request('POST','/api/m1/analysis/info',{'paths':self.inputs,'workers':self.workers})
                self.profile=selection['profile']
            else:
                selection=manager.import_streams(store,self.inputs,self.workers)
                self.profile=selection['header']['profile']
        elif self.module==1:
            self.outputs=[str(self.folder/f'primary-{i+1}.tpstream') for i in range(2)]
            p['run'].update(threads=self.workers,output_paths=self.outputs)
            manager.create(store,p)
        elif self.module==2:
            self.outputs=[str(self.folder/'pairs.tppulses')]
            p.update(threads=self.workers,input_paths=self.inputs,output_path=self.outputs[0])
            manager.create(store,p)
        else:
            p.update(workers=self.workers,input_paths=self.inputs)
            manager.start(store,p)

    def status(self):
        if self.module==1 and self.importing:
            state=self.workspace.request('GET','/api/m1/import/status')
            status='running' if state['loading'] else 'failed' if state['error'] else 'completed' if all(s['verified'] for s in state['streams']) else 'partial'
            return dict(**slim(state),status=status,progress=state['loaded_bytes']/max(1,state['total_bytes']))
        state=self.manager.current()
        result=slim(state)
        if self.module==1:
            result['progress']=state['completed']/max(1,state['total'])
            result['trajectories']=state['trajectories'][-1:]
        return result

    def stop(self):
        if self.importing and self.module==1:
            self.workspace.request('POST','/api/m1/import/stop',{})
        elif self.module==3:
            self.manager.stop()
        else:
            state=self.manager.current()
            if state:
                self.manager.stop(state['id'])

    def histogram(self):
        if self.module==1:
            query={'metric':'energy','detector':'all','bins':80}
            if self.importing:
                return self.workspace.request('POST','/api/m1/analysis',{**query,'paths':self.inputs})
            return self.manager.analysis.query(query)[0]
        if self.module==2:
            return self.manager.analysis.query({'bins':100})
        return self.manager.session.spectra({'merged':SpectrumDisplay(bin_ps=100, low_ns=-5,high_ns=15)})

    def preview(self,data):
        if self.module==1:
            items=data['series']
            title='Deposited energy'
            unit=data['unit']
        elif self.module==2:
            chart=data['plots'][0]
            items=chart['series']
            title=chart['title']
            unit=chart['unit']
        else:
            value=data['comparisons']['merged']['stages'][0]['lifetime']
            return dict(title='Merged lifetime · before filters',xLabel='Time difference (ns)',yLabel='Pairs / bin',
                        series=[dict(name='All pairs',color='#198f8c',points=[[-5+(i+.5)*.1,n] for i,n in value['bins']])])
        colors=['#198f8c','#6987cf','#986aba','#d08628']
        return dict(title=title,xLabel=f'{title} ({unit})',yLabel='Counts / bin',
                    series=[dict(name=s.get('label') or s.get('name',''),color=colors[i%len(colors)],
                                 points=[[(a+b)/2,n] for a,b,n in zip(s['edges'],s['edges'][1:],s['counts'])])
                            for i,s in enumerate(items)])

    def finish(self):
        results={}
        hist=self.histogram()
        self.plots=self.preview(hist)
        if self.module==2:
            # Module 2 has a single combined stream. Keep its verified seek
            # offsets so an agent can inspect one full waveform after restart.
            with (self.folder/'waveform-offsets.bin').open('wb') as dest:
                self.manager.analysis.offsets.tofile(dest)
        if self.module==3:
            job=self.manager.session
            job.positions.flush()
            shutil.copyfile(job.positions.name,self.folder/'waveform-positions.bin')
            hist=job.spectra(self.display)
            journal=job.comparison
            count,floors=journal.capture()
            shutil.copyfile(journal.file.name,self.folder/'spectrum-pairs.bin')
            atomic_json(self.folder/'journal.json',dict(count=count,floors=floors,sub_names=journal.sub_names,
                        maxima=journal.maxima,delays=journal.delays,isotope=journal.isotope,categories=hist['categories']))
        atomic_json(self.folder/'analysis.json',hist)
        for q in self.queries:
            if not permitted(q['method'],q['path'],True) or not self.workspace.accepts(q['method'],q['path']) or not q['path'].startswith(f'/api/m{self.module}/'):
                raise ValueError(f"Unsupported scientific query: {q['path']}")
            body=q['body']
            if self.importing and self.module==1:
                body={**body,'paths':self.inputs}
            result=self.workspace.request(q['method'],q['path'],body)
            name='query-'+q['name']+'.json'
            atomic_json(self.folder/name,result)
            results[q['name']]=name
        return dict(analysis='analysis.json',queries=results,outputs=[fingerprint(path) for path in self.outputs])

def archived_spectrum(folder,direction,display):
    if direction not in ('merged','AB','BA','SS'):
        raise ValueError('Choose merged, AB, BA or SS.')
    meta=json.loads((folder/'journal.json').read_bytes())
    with SpectrumJournal.open_archive(folder/'spectrum-pairs.bin',meta) as journal:
        return journal.query((meta['count'],meta['floors']),direction,SpectrumDisplay.model_validate(display),meta['categories'])

