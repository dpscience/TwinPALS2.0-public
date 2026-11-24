# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import json
import time
from pathlib import Path

import pytest
from backend.mcp_server.engine import Engine
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
    engine=Engine(tmp_path,no_logon=True)
    try:
        spec=example()
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
        assert m2['inputs']==a['outputs'] and m3['inputs']==m2['outputs']
        assert m2['metrics']['waveforms']==m3['metrics']['total_processed']==8
        from types import SimpleNamespace
        service=SimpleNamespace(engine=engine)
        assert waveform_read(service,runs[-2]['id'],5,'/waveform')==waveform_read(service,runs[-1]['id'],5,'/waveform')
        recorded=json.loads((engine.q.folder(runs[-1])/'analysis.json').read_bytes())['comparisons']['merged']
        regenerated=archived_spectrum(engine.q.folder(runs[-1]),'merged',{'individual':True})
        for field in ('extent','stages','gated_pairs'):
            assert recorded[field]==regenerated[field]
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

