# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Discoverable MCP tools, with bounded replies and durable scientific exports."""
import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from typing import Literal

from pydantic import Field, create_model

from backend import __version__
from backend.app import application_root
from backend.execution import cpu_settings
from backend.release_updates import release_status
from backend.m1_store import atomic_json
from backend.m2_stream import Reader
from backend.m2_engine import wave_json
from backend.streams import inspect_stream
from . import VERSION
from . import knowledge
from .engine import read
from .studies import MODELS, Parameters, Study, encoded, select
from .workbench import archived_spectrum, permitted

TOOLS={}
def tool(name,description, fields=None,model=None):
    def register(func):
        params=model or create_model(name+'Input',__base__=Parameters,**(fields or {}))
        TOOLS[name]=(description,params,func)
        return func
    return register


def listing():
    return [dict(name=n,description=d,inputSchema=p.model_json_schema()) for n,(d,p,_) in TOOLS.items()]


def invoke(service,name,args):
    if name not in TOOLS:
        raise ValueError('Unknown MCP tool.')
    _,model,fn=TOOLS[name]
    values=model.model_validate(args).model_dump()
    result=fn(service,**values)
    data=encoded(result)
    if len(data)>42000:
        key=hashlib.sha256(data.encode('utf-8')).hexdigest()
        path=service.engine.q.root/'responses'/(key+'.json')
        if not path.exists():
            atomic_json(path,result)
        return dict(response_id=key,bytes=path.stat().st_size,path=str(path),
                    read_with='result_read',description='Complete result saved. Read by JSON Pointer or UTF-8 text pages.')
    return result

@tool('capabilities','Discover versions, available CPU resources, Windows recovery and the read-only observer.')
def capabilities(s):
    e=s.engine
    return dict(application_version=__version__,server_version=VERSION,methods=knowledge.PREFIX+knowledge.INDEX,
                software_source=knowledge.source_metadata(),release_update=release_status(e.q.data),**cpu_settings(),cpu_budget=e.limit,
                data_directory=str(e.q.data),observer=s.observer_url,queue_persistence='SQLite + per-stage receipts',
                recovery='Unfinished stages replay with frozen settings and seeds. Completed stages are reused.',
                sign_in_resume='disabled for this service' if e.no_logon else e.logon_error or 'armed while work is pending')

@tool('knowledge_search','Search the offline TwinPALS methods handbook. An empty query lists all topics. Use for units, measurement rules, provenance and reproducible studies.',
      {'query':(str,Field(default='',max_length=500)),'limit':(int,Field(default=8,ge=1,le=20))})
def knowledge_search(s,query,limit):
    return knowledge.search(query,limit)


@tool('knowledge_read','Read a complete local methods topic with its software version, source references, verification references and release citation.',
      {'topic':(str,Field(default='overview',max_length=100))})
def knowledge_read(s,topic):
    return knowledge.read_topic(topic)


@tool('profile_get','Read current editable M1, M2 or M3 settings or its complete validation schema. JSON Pointer selects any nested value.',
      {'module':(Literal[1,2,3],...), 'schema_only':(bool,False),'pointer':(str,'')})
def profile_get(s,module,schema_only,pointer):
    store=s.engine.control.store
    data=MODELS[module].model_json_schema() if schema_only else {1:store.profile,2:store.module2,3:store.module3}[module]
    return select(data,pointer)

@tool('catalogue_list','List material and component IDs, names and revisions. Includes PMTs, scintillators, digitizers and physical materials.',
      {'category':(str,''),'search':(str,'')})
def catalogue_list(s,category,search):
    store=s.engine.control.store
    return [dict(id=e['id'],name=e['name'],category=e['category'],revision=e['revision']) for e in store.entries
            if (not category or e['category']==category) and search.lower() in (e['id']+' '+e['name']).lower()]

@tool('catalogue_get','Read a complete material including units, measurement curves, citations and model assumptions. Use an existing tube as a template.',
      {'id':(str,...),'pointer':(str,'')})
def catalogue_get(s,id,pointer):
    for entry in s.engine.control.store.entries:
        if entry['id']==id:
            return select(entry,pointer)
    raise ValueError('Unknown catalogue ID.')

@tool('catalogue_factory_optics','Preview missing factory photocathode data held for review on a locally modified tube. To adopt the draft, review its curves and sources and use catalogue_save with its revision.',
      {'id':(str,...)})
def catalogue_factory_optics(s,id):
    entry=catalogue_get(s,id,'')
    return s.engine.control.store.database.factory_optics(id,entry)


@tool('catalogue_save','Create a component or update an existing one in the shared TwinPALS database. Send the full entry and its expected revision on update.',
      {'entry':(dict,...),'expected_revision':(int|None,None)})
def catalogue_save(s,entry,expected_revision):
    with s.engine.lock:
        s.engine.control.store.put_entry(entry,expected_revision)
        s.engine.q.event('Catalogue saved: '+entry['id'])
        return catalogue_get(s,entry['id'],'')

@tool('stream_inspect','Inspect one local TwinPALS transport or pulse stream header and completion without replaying it. Paths may be relative to the data directory.',
      {'path':(str,...),'pointer':(str,'')})
def stream_inspect(s,path,pointer):
    file=(s.engine.q.data/path).resolve(strict=True)
    if file.name.endswith(('.tpstream','.tpstream.part')):
        data=inspect_stream(file)
    elif file.name.endswith(('.tppulses','.tppulses.part')):
        reader=Reader(file)
        try:
            data=dict(path=str(file),bytes=reader.limit,header=reader.header,completion=reader.inspect_completion())
        finally:
            reader.close()
    else:
        raise ValueError('Choose a .tpstream or .tppulses stream.')
    return select(data,pointer)

@tool('stream_list','List TwinPALS streams in a local directory with their byte sizes, including recordings from the desktop app.',
      {'directory':(str,'runs'),'offset':(int,Field(0,ge=0)),'limit':(int,Field(100,ge=1,le=500))})
def stream_list(s,directory,offset,limit):
    folder=(s.engine.q.data/directory).resolve(strict=True)
    files=sorted(p for p in folder.iterdir() if p.is_file() and p.name.endswith(('.tpstream','.tppulses','.tpstream.part','.tppulses.part')))
    return dict(total=len(files),streams=[dict(name=p.name,path=str(p),bytes=p.stat().st_size) for p in files[offset:offset+limit]])

@tool('study_submit','Commit and start an offline-capable study. List ordered steps and dependencies. A stable request_id makes reconnect retries safe. Return immediately with study/run IDs.',model=Study)
def study_submit(s,**spec):
    return s.engine.submit(spec)

@tool('study_list','List durable studies, newest first.',{'limit':(int,Field(50,ge=1,le=500)),'offset':(int,Field(0,ge=0))})
def study_list(s,limit,offset):
    return s.engine.q.rows('SELECT id,name,created,request_id FROM studies ORDER BY created DESC LIMIT ? OFFSET ?',limit,offset)

@tool('study_status','Read run IDs, dependencies, progress, attempts and error details. Include the manifest for frozen profiles, input identities and seeds.',
      {'study_id':(str,...),'manifest':(bool,False),'pointer':(str,'')})
def study_status(s,study_id,manifest,pointer):
    q=s.engine.q
    return select(q.manifest(study_id) if manifest else q.study(study_id),pointer)

@tool('run_cancel','Cancel one run. Dependent steps become blocked. Other experiments continue.',{'run_id':(str,...)})
def run_cancel(s,run_id):
    return s.engine.cancel(run_id)

@tool('run_retry','Retry one failed, blocked or cancelled step using the original frozen inputs and seed. Each attempt owns its files.',{'run_id':(str,...)})
def run_retry(s,run_id):
    return s.engine.retry(run_id)

@tool('run_result','Read a completed run receipt, default analysis, preview, or named saved query. JSON Pointer selects a metric, spectrum, class or array.',
      {'run_id':(str,...),'artifact':(str,'receipt'),'pointer':(str,'')})
def run_result(s,run_id,artifact,pointer):
    q=s.engine.q
    run=q.get_run(run_id)
    folder=q.folder(run)
    if run['status'] not in ('completed','partial'):
        return dict(status=run['status'],message=run['message'],progress=run['progress'])
    receipt=read(folder/'receipt.json')
    names={'receipt':'receipt.json','analysis':'analysis.json','preview':'preview.json',**receipt['queries']}
    if artifact not in names:
        raise ValueError('Unknown result. Available: '+', '.join(names))
    return select(read(folder/names[artifact]),pointer)

@tool('spectrum_query','Rebin a completed M3 lifetime and pulse-height journal, before and after filters, with contribution classes/subtypes. No waveform reread.',
      {'run_id':(str,...),'direction':(Literal['merged','AB','BA','SS'],'merged'),'display':(dict,Field(default_factory=dict)),'pointer':(str,'')})
def spectrum_query(s,run_id,direction,display,pointer):
    q=s.engine.q
    run=q.get_run(run_id)
    if run['module']!=3 or run['status'] not in ('completed','partial'):
        raise ValueError('Choose a completed Module 3 run.')
    return select(archived_spectrum(q.folder(run),direction,display),pointer)

@tool('waveform_read','Seek directly to one recorded pair in a completed M2 or M3 run, with full A/B ADC samples and recorded metadata. Index starts at zero.',
      {'run_id':(str,...),'index':(int,Field(ge=0)),'pointer':(str,'')})
def waveform_read(s,run_id,index,pointer):
    from backend.m3_measurements import POSITION
    import struct
    import numpy as np
    q=s.engine.q
    run=q.get_run(run_id)
    folder=q.folder(run)
    receipt=read(folder/'receipt.json')
    if run['module'] not in (2,3) or not receipt:
        raise ValueError('Choose a completed digitizer or lifetime run.')
    pulse_run=run['module']==2
    source=(receipt['outputs'] if pulse_run else receipt['inputs'])[0]
    records=receipt['metrics']['waveforms' if pulse_run else 'total_processed']
    if index>=records:
        raise ValueError(f'This run contains {records} waveform pairs.')
    from .studies import fingerprint
    if fingerprint(source['path'])!=source:
        raise ValueError('The recorded stream changed after measurement.')
    if pulse_run:
        with (folder/'waveform-offsets.bin').open('rb') as f:
            f.seek(index*8)
            offset=struct.unpack('<Q',f.read(8))[0]
    else:
        with (folder/'waveform-positions.bin').open('rb') as f:
            f.seek(index*POSITION.itemsize)
            row=np.frombuffer(f.read(POSITION.itemsize),dtype=POSITION,count=1)[0]
            offset=int(row['offset'])
    reader=Reader(Path(source['path']))
    try:
        return select(wave_json(*reader.record(offset),limit=65536),pointer)
    finally:
        reader.close()

@tool('workbench_routes','Discover desktop scientific API operations for geometry validation, material exchange, PMT response, stream analysis, fitting, waveform inspection and settings.',
      {'search':(str,'')})
def workbench_routes(s,search):
    return [r for r in s.engine.control.routes() if search.casefold() in r['path'].casefold()]

@tool('workbench_call','Call a discovered scientific endpoint. Supply run_id for a live scientific workspace. To retain custom results, include the query in study_submit. Use the catalog and profile routes on the control workspace.',
      {'method':(Literal['GET','POST','DELETE'],'POST'),'path':(str,...),'body':(dict,Field(default_factory=dict)),
       'params':(dict,Field(default_factory=dict)),'run_id':(str,''),'pointer':(str,'')})
def workbench_call(s,method,path,body,params,run_id,pointer):
    if not permitted(method,path,bool(run_id)):
        raise ValueError('Use a scheduled study for processing. Discover callable endpoints with workbench_routes.')
    e=s.engine
    if run_id:
        run=e.q.get_run(run_id)
        if not path.startswith(f"/api/m{run['module']}/"):
            raise ValueError('Choose an endpoint of this run module.')
        with e.lock:
            task=e.active.get(run_id)
            science=task and task['science']
        if not science:
            raise ValueError('Use run_result or spectrum_query on a finished run. Submit an import to repeat a waveform analysis.')
        if science.module==1 and science.importing and method=='POST':
            body={**body,'paths':science.inputs}
        bench=science.workspace
    else:
        bench=e.control
    if not bench.accepts(method,path):
        raise ValueError('Unknown workbench operation or HTTP method.')
    result=bench.request(method,path,body,params)
    if not run_id and method!='GET' and ('materials' in path or 'profile' in path):
        e.q.event(method+' '+path)
    return select(result,pointer)

@tool('result_read','Read a large tool response by JSON Pointer with array/object pagination. Use text mode to read long strings or the complete serialized JSON in pages.',
      {'response_id':(str,...),'pointer':(str,''),'offset':(int,Field(0,ge=0)),'limit':(int,Field(25,ge=1,le=25000)),'text_mode':(bool,False)})
def result_read(s,response_id,pointer,offset,limit,text_mode):
    if not re.fullmatch(r'(?:[a-f0-9]{32}|[a-f0-9]{64})',response_id):
        raise ValueError('Invalid response ID.')
    path=s.engine.q.root/'responses'/(response_id+'.json')
    if text_mode and not pointer:
        with path.open('r',encoding='utf-8') as f:
            rest=offset
            while rest:
                chunk=f.read(min(65536,rest))
                if not chunk:
                    break
                rest-=len(chunk)
            return dict(text=f.read(limit),offset=offset)
    value=select(json.loads(path.read_bytes()),pointer)
    if text_mode:
        value=encoded(value)
    if isinstance(value,dict):
        return dict(total=len(value),keys=list(value)[offset:offset+limit])
    if isinstance(value,(list,str)):
        return dict(total=len(value),offset=offset,items=value[offset:offset+limit])
    return value

@tool('study_compare','Compare a numeric result across runs in the same study. Choose the JSON Pointer and ranking direction, for example /accepted or /acquisition_rate_Hz.',
      {'study_id':(str,...),'metric':(str,...),'higher_is_better':(bool,True)})
def study_compare(s,study_id,metric,higher_is_better):
    q=s.engine.q
    rows=[]
    for run in q.study(study_id)['runs']:
        receipt=read(q.folder(run)/'receipt.json')
        if not receipt:
            continue
        try:
            value=select(receipt['metrics'],metric)
        except (KeyError,IndexError,TypeError):
            continue
        if type(value) in (float,int):
            rows.append(dict(run_id=run['id'],step=run['name'],value=value,status=run['status']))
    return sorted(rows,key=lambda row:row['value'],reverse=higher_is_better)

@tool('study_report','Write a standalone Markdown study report with measured results, runtime, frozen settings, input identities and links to analysis artifacts.',
      {'study_id':(str,...)})
def study_report(s,study_id):
    q=s.engine.q
    manifest=q.manifest(study_id)
    jobs=q.study(study_id)['runs']
    lines=['# '+manifest['name'],'',manifest['objective'],'',
           f"TwinPALS {__version__} · Study \u0060{study_id}\u0060",'',
           '| Step | Module | Status | Workers | Recorded result |','|---|---|---|---|---|']
    for r in jobs:
        receipt=read(q.folder(r)/'receipt.json',{})
        fields=receipt.get('metrics',{})
        values=[f'{k.replace("_"," ")} {fields[k]}' for k in ('completed','waveforms','accepted','total_processed','measurement_ns') if k in fields]
        lines.append(f"| {r['name']} | {r['module']} | {r['status']} | {r['workers']} | {', '.join(values) or '—'} |")
    lines+=['','## Reproduction','','[Frozen study definition](manifest.json) · [Material snapshot](catalogue.tpdb)','']
    for r in jobs:
        if (q.folder(r)/'receipt.json').exists():
            relative=q.folder(r).relative_to(q.root/study_id).as_posix()
            lines.append(f"- {r['name']} · [Run receipt]({relative}/receipt.json) · [Analysis]({relative}/analysis.json)")
    lines.extend(['', '## Scientific basis', '', 'Dominik Boras (2024), doctoral dissertation, Universität Würzburg. [Dissertation](https://doi.org/10.25972/OPUS-37663)', '', 'TwinPALS 2.0 · © 2026 Danny Petschke · twinpals@proton.me'])
    path=q.root/study_id/'report.md'
    write_text(path,'\n'.join(lines)+'\n')
    return dict(path=str(path),runs=len(jobs))

def write_text(path,content):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(uuid.uuid4().hex+'.tmp')
    try:
        with tmp.open('x',encoding='utf-8',newline='\n') as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        tmp.unlink(missing_ok=True)

@tool('study_document','Save a manuscript, methods section or CSV table alongside study evidence. Provide source run IDs. Every version receives a new artifact ID.',
      {'study_id':(str,...),'filename':(str,...),'content':(str,Field(max_length=2_000_000)),
       'run_ids':(list[str],...)})
def study_document(s,study_id,filename,content,run_ids):
    q=s.engine.q
    study=q.study(study_id)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_. -]{0,100}\.(md|html|csv|json|txt|tex)',filename,re.I):
        raise ValueError('Use a simple manuscript or table filename.')
    if not run_ids or not set(run_ids)<=set(r['id'] for r in study['runs'] if r['status'] in ('completed','partial')):
        raise ValueError('Cite at least one completed run belonging to this study.')
    folder=q.root/study_id/'documents'/uuid.uuid4().hex
    path=folder/filename
    write_text(path,content)
    evidence=dict(path=str(path),run_ids=run_ids,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    atomic_json(folder/'evidence.json',evidence)
    return evidence

@tool('observer_open','Return a local read-only live dashboard. Optionally open it in the default browser on this computer.',{'open_browser':(bool,False)})
def observer_open(s,open_browser):
    if open_browser:
        import webbrowser
        webbrowser.open(s.observer_url)
    return {'url':s.observer_url,'access':'read-only'}

