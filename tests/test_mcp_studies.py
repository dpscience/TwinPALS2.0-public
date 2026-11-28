# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import json
import time
from pathlib import Path

import pytest
from backend.mcp_server.engine import Engine
from backend.mcp_server.observer import lifetime, query_charts, archived_charts
from backend.mcp_server.service import Service, web_app
from backend.m3_models import SpectrumDisplay
from backend.m2_physics import input_info, load_libraries
from fastapi.testclient import TestClient
from backend.mcp_server.studies import TERMINAL
from backend.mcp_server.workbench import archived_spectrum
from backend.mcp_server.cli import rpc
from backend.mcp_server.tools import waveform_read


def example():
    detector={'/run/events':512,'/run/secondary_events':512,'/run/auto_seed':False,'/run/seed':48315}
    acquisition={'/waveform_pairs':8,'/activity_Bq':10000,'/channels/0/threshold_mV':1,
                 '/channels/1/threshold_mV':1,'/acquisition/trigger':'either','/auto_seed':False}
    return dict(request_id='pipeline-v1',name='Detector comparison',max_parallel=2,cpu_budget=2,steps=[
        dict(key='source',module=1,changes=detector),
        dict(key='cascade',module=1,changes={**detector,'/source':'co60'}),
        dict(key='readout',module=2,input_from='source',changes=acquisition),
        dict(key='spectrum',module=3,input_from='readout')])


def test_real_parallel_pipeline_and_archive(tmp_path):
    service=Service(tmp_path,no_logon=True)
    engine=service.engine
    try:
        spec=example()
        for step in spec['steps'][:2]:
            step['changes'].update({'/detectors/0/distance_mm': 2, '/detectors/1/distance_mm': 2})
        spec['objective']='Compare primary responses, then measure the recorded pairs.'
        spec['steps'][2]['queries']=[dict(name='height',path='/api/m2/analysis',body={'bins':40})]
        spec['steps'][3]['queries']=[dict(name='timing',path='/api/m3/analysis',body={'SS':{'low_ns':-3,'high_ns':4,'bin_ps':17}})]
        study=engine.submit(spec)
        assert engine.submit(spec)['id']==study['id']
        with pytest.raises(ValueError,match='different'):
            engine.submit({**spec,'name':'changed'})
        deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            runs=engine.q.study(study['id'])['runs']
            if all(r['status'] in TERMINAL for r in runs):
                break
            time.sleep(.25)
        assert all(r['status']=='completed' for r in runs),[(r['name'],r['status'],r['message']) for r in runs]
        results=[json.loads((engine.q.folder(r)/'receipt.json').read_bytes()) for r in runs]
        a,b,m2,m3=results
        assert max(a['started'],b['started'])<min(a['finished'],b['finished'])
        assert a['metrics']['completed']==b['metrics']['completed']==1024
        # Independently decode both Co-60 event records, including detector B,
        # and verify the writer's directional cascade totals against those records.
        cascade_dir = engine.q.folder(runs[1])
        cascade = input_info([cascade_dir/'primary-1.tpstream', cascade_dir/'primary-2.tpstream'])
        libraries = load_libraries({**cascade, '_reference_reader': True}, lambda: None, lambda _: None)
        for library in libraries:
            library.close()
        assert sum(cascade['directional_combinations']['response']) > 0
        assert m2['inputs']==a['outputs'] and m3['inputs']==m2['outputs']
        assert m2['metrics']['waveforms']==m3['metrics']['total_processed']==8
        assert waveform_read(service,runs[-2]['id'],5,'/waveform')==waveform_read(service,runs[-1]['id'],5,'/waveform')
        recorded=json.loads((engine.q.folder(runs[-1])/'analysis.json').read_bytes())['comparisons']['merged']
        regenerated=archived_spectrum(engine.q.folder(runs[-1]),'merged',{'individual':True})
        for field in ('extent','stages','gated_pairs'):
            assert recorded[field]==regenerated[field]
        detail=[service.detail(r['id']) for r in runs]
        assert [len(d['charts']) for d in detail]==[1,1,3,4]
        assert all(d['geometry'] and d['entries'] for d in detail[:2])
        assert detail[3]['context']==dict(objective=spec['objective'],step=4,steps=4,operation='run',parent='readout',queries=['timing'])
        assert detail[2]['input_files']==['primary-1.tpstream','primary-2.tpstream']
        for d in detail[:2]:
            assert sum(s['outcomes']['total'] for s in d['metrics']['streams'])==1024
            for trace,raw in zip(d['charts'][0]['series'],json.loads((engine.q.folder(d['run'])/'analysis.json').read_bytes())['series']):
                assert sum(b['count'] for b in trace['bins'])<=raw['valid']
        assert set(service.comparison(runs[0]['id'])['fields'])=={'source'}
        assert service.overview('absent')['runs']==[]
        with TestClient(web_app(service)) as client:
            endpoint='/observe/api/runs/'+runs[-1]['id']+'/queries/timing'
            auth={'Authorization':'Bearer '+service.viewer}
            assert client.get(endpoint).status_code==403 and client.post(endpoint,headers=auth).status_code==403
            assert client.get(endpoint+'/charts',headers=auth).json()['charts'][0]['title']=='Stop–Stop lifetime'
            assert '17 ps' in client.get(endpoint+'/charts',headers=auth).json()['charts'][0]['note']
            assert client.get(endpoint,headers=auth).json()['comparisons'].keys()=={'SS'}
            assert client.get(endpoint.replace('timing','missing'),headers=auth).status_code==404
        selected=query_charts(engine.q.folder(runs[2]),runs[2]['id'],'height')
        assert len(selected)==3 and len(selected[0]['series'][0]['bins'])==40
        # Reconstruct the lifetime plot of an earlier-format archive from analysis.json.
        assert archived_charts(engine.q.folder(runs[-1]),3)==detail[-1]['charts']
        # Import a complete M1 source and the first three committed pairs of an M2 stream.
        import struct
        offset=struct.unpack_from('=Q',(engine.q.folder(runs[2])/'waveform-offsets.bin').read_bytes(),3*8)[0]
        prefix=tmp_path/'short.tppulses.part'
        prefix.write_bytes(Path(m2['outputs'][0]['path']).read_bytes()[:offset])
        imported=engine.submit(dict(request_id='observer-imports',name='Import inspection',steps=[
            dict(key='transport',operation='import',module=1,inputs=[v['path'] for v in a['outputs']]),
            dict(key='partial',operation='import',module=2,inputs=[str(prefix)])]))
        deadline=time.monotonic()+50
        while time.monotonic()<deadline:
            rows=engine.q.study(imported['id'])['runs']
            if all(r['status'] in TERMINAL for r in rows):
                break
            time.sleep(.15)
        assert [r['status'] for r in rows]==['completed','partial'],rows
        first,second=[service.detail(r['id']) for r in rows]
        assert first['geometry'] and first['metrics']['total_events']==1024
        assert second['metrics']['waveforms']==3 and len(second['charts'])==3
        assert all(r['study']==imported['id'] for r in service.overview(imported['id'])['activity'])
    finally:
        engine.close()


def test_mcp_handshake_and_notifications():
    for version in ('2024-11-05','2025-03-26','2025-06-18','2025-11-25'):
        response=rpc({'jsonrpc':'2.0','id':'init','method':'initialize','params':{'protocolVersion':version}},None)
        assert response['result']['protocolVersion']==version
        assert response['id']=='init' and 'tools' in response['result']['capabilities']
    assert rpc({'jsonrpc':'2.0','method':'notifications/initialized'},None) is None
    assert rpc({'jsonrpc':'2.0','id':2,'method':'missing'},None)['error']['code']==-32601


def test_cancel_and_retry_isolated_runs(tmp_path):
    engine=Engine(tmp_path,no_logon=True)
    try:
        spec=example()
        spec['max_parallel']=1
        first,second=spec['steps'][:2]
        first['changes']['/run/events']=1500
        spec['steps']=[first,second]
        with engine.lock:
            runs=engine.submit(spec)['runs']
            cancelled=engine.cancel(runs[1]['id'])
            assert cancelled['status']=='cancelled' and cancelled['attempt']==0
            retried=engine.retry(runs[1]['id'])
            assert retried['id']==cancelled['id'] and retried['status']=='queued'
            engine.cancel(runs[1]['id'])
            engine.cancel(runs[0]['id'])
        assert all(r['status']=='cancelled' for r in engine.q.study(runs[0]['study'])['runs'])
    finally:
        engine.close()



def test_observer_sparse_lifetime_coordinates_filters_and_counts():
    def stage(sparse,total):
        return dict(lifetime={'bins':sparse,'counts':sum(n for i,n in sparse)},phs=[{'counts':total}])
    view=SpectrumDisplay(low_ns=-3,high_ns=4.005,bin_ps=10)
    stages=[stage([[120,4],[500,2],[700,1]],10),stage([[120,1]],2)]
    comparison={'stages':stages,'filter_active':True}
    result=lifetime('BA',comparison,view)
    assert result['series'][0]['bins']==[
        dict(low=pytest.approx(-1.8),high=pytest.approx(-1.79),count=4),
        dict(low=2,high=pytest.approx(2.01),count=2),
        dict(low=4,high=4.005,count=1)]
    assert result['series'][1]['bins'][0]['count']==1
    assert '7 in range, 3 outside' in result['note'] and '1 in range, 1 outside' in result['note']
    empty=lifetime('SS',dict(stages=[stage([],9),stage([],9)],filter_active=False),view)
    assert len(empty['series'])==1 and empty['series'][0]['points']==[] and '9 outside' in empty['note']
    counts=[[k,k%7+1] for k in range(5000)]
    dense=lifetime('merged',dict(stages=[stage(counts,20000)],filter_active=False),SpectrumDisplay())
    assert sum(b['count'] for b in dense['series'][0]['bins'])==sum(n for _,n in counts)
    assert len(dense['series'][0]['bins'])<=1200


def test_observer_failed_blocked_queued_and_retry(tmp_path):
    service=Service(tmp_path,no_logon=True)
    engine=service.engine
    try:
        stream=tmp_path/'bad.tpstream'
        stream.write_bytes(b'not a transport recording')
        spec=dict(name='Invalid source',request_id='observer-failure',steps=[
            dict(key='bad-import',module=1,operation='import',inputs=[str(stream)]),
            dict(key='dependent',module=2,input_from='bad-import')])
        with engine.lock:
            jobs=engine.submit(spec)['runs']
            d=service.detail(jobs[0]['id'])
            assert d['run']['status']=='queued' and d['profile']=={} and not d['geometry'] and not d['charts']
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            details=[service.detail(r['id']) for r in jobs]
            if all(d['run']['status'] in TERMINAL for d in details):
                break
            time.sleep(.1)
        assert [d['run']['status'] for d in details]==['failed','blocked']
        assert all(not d['metrics'] and not d['charts'] and d['run']['message'] for d in details)
        with engine.lock:
            engine.retry(jobs[0]['id'])
            engine.cancel(jobs[0]['id'])
            d=service.detail(jobs[0]['id'])
            assert d['run']['status']=='cancelled' and not d['charts']
    finally:
        engine.close()
