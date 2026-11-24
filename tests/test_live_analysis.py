# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import base64
import json
import threading
import time

import numpy as np
import pytest

from backend.live_analysis import AnalysisStore, EVENT_DTYPE, checked_events
from backend.streams import METRICS, StreamError, analyze, inspect_stream
from test_streams_v1 import event, frame, write, record


def loaded(store, timeout=5):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        snapshots=[b.snapshot() for b in store.buffers.values()]
        if all(s.status!='incomplete' for s in snapshots): return
        time.sleep(.01)
    raise AssertionError('Incremental import did not finish')


@pytest.mark.parametrize('role,mask',[('na22_prompt',1),('na22_annihilation',6),('co60_1173',3),('co60_1332',3)])
@pytest.mark.parametrize('metric',list(METRICS))
def test_memory_matches_independent_file_histograms(tmp_path,role,mask,metric):
    rows=[event(0,mask=mask),event(1,(0,0,0),(60,4,3),mask),event(2,(10,1,4),(20,2,5),mask),event(3,(0,0,0),(0,0,0),mask)]
    path=write(tmp_path/'data.tpstream',rows,role=role)
    store=AnalysisStore()
    try:
        store.open_files([path]);loaded(store)
        for category in ('all','none','A','B','both','interaction','transmission','miss'):
            for detector in ('all','A','B'):
                request=dict(metric=metric,category=category,detector=detector,bins=7)
                expected=analyze([path],request);actual=store.query(request)[0]
                assert actual['total_events']==expected['total_events']==4
                assert actual['series']==expected['series']
                order=lambda p:(p['primary'],p['event_id'],p['detector'])
                assert sorted(actual['positions'],key=order)==sorted(expected['positions'],key=order)
                assert actual['markers']==expected['markers']
                assert actual['streams'][0]['completion']['verified']
    finally:store.close()


def test_live_batches_do_not_open_streams(tmp_path,monkeypatch):
    path=write(tmp_path/'header.tpstream')
    header=inspect_stream(path)['header'];path.unlink()
    store=AnalysisStore();store.register(header,path)
    def forbidden(*args,**kwargs): raise AssertionError('Live analysis touched disk')
    monkeypatch.setattr('backend.live_analysis._open_shared_read',forbidden)
    for i in range(3):
        payload=event(i)[12:]
        from test_streams_v1 import analog_record
        store.feed(dict(type='analysis_batch',role='na22_prompt',first=i,count=1,data=base64.b64encode(payload).decode(),analog=base64.b64encode(analog_record(frame(b'EVNT',payload))).decode(),hit_a=base64.b64encode(np.zeros((10,2),dtype='<f4').tobytes()).decode(),hit_b=''))
        results=store.query(dict(metrics=['energy','photon_count','mean_arrival','depth']))
        assert all(r['total_events']==i+1 for r in results)
    store.finish('na22_prompt','completed',3)
    assert store.query({})[0]['complete']
    assert not store.query({})[0]['streams'][0]['completion']['verified'] # No claim of a full disk CRC scan.
    with pytest.raises(StreamError,match='Missing live'):store.feed(dict(type='analysis_batch',role='na22_prompt',first=0,count=1,data=base64.b64encode(payload).decode()))


def test_growing_file_recovers_complete_frames_and_final_rename(tmp_path):
    path=write(tmp_path/'growing.tpstream.part',[event(0)],done=False,suffix=record(event(1))[:100])
    store=AnalysisStore();store.open_files([path])
    try:
        deadline=time.monotonic()+5
        while store.buffers['na22_prompt'].count<1 and time.monotonic()<deadline:time.sleep(.01)
        assert store.query({})[0]['total_events']==1
        with path.open('ab') as file:file.write(record(event(1))[100:]+frame(b'DONE',json.dumps({'status':'completed','events':2}).encode()))
        path.rename(tmp_path/'growing.tpstream')
        loaded(store)
        result=store.query({})[0]
        assert result['complete'] and result['total_events']==2
    finally:store.close()


def test_import_detects_corruption_and_cancellation(tmp_path):
    broken=bytearray(event(0));broken[-1]^=1
    path=write(tmp_path/'bad.tpstream',[bytes(broken)])
    store=AnalysisStore();store.open_files([path])
    try:
        with pytest.raises(StreamError,match='CRC'):loaded(store)
    finally:store.close()
    partial=write(tmp_path/'partial.tpstream.part',done=False)
    store=AnalysisStore();store.open_files([partial]);store.close()
    assert all(not t.is_alive() for t in store.threads)


def test_stop_import_retains_data_and_never_follows_file_growth(tmp_path):
    path=write(tmp_path/'paused.tpstream.part',[event(0)],done=False)
    store=AnalysisStore();store.open_files([path])
    try:
        deadline=time.monotonic()+5
        while store.progress()['total_events']<1 and time.monotonic()<deadline:time.sleep(.01)
        progress=store.stop_import()
        assert not progress['loading'] and progress['total_events']==1
        assert progress['streams'][0]['status']=='stopped'
        assert all(not t.is_alive() for t in store.threads)
        with path.open('ab') as file:file.write(record(event(1)))
        assert store.query({})[0]['total_events']==1
        assert not store.query({})[0]['complete']
        assert len(store.buffers['na22_prompt'].pulses[0].event(0))==10
        assert store.stop_import()['total_events']==1
    finally:store.close()


def test_summary_is_324_bytes_and_validation_rejects_invalid_flags():
    assert EVENT_DTYPE.itemsize==324
    data=np.frombuffer(event(0)[12:],dtype=EVENT_DTYPE).copy()
    data['detectors']['flags'][0,0]|=256
    with pytest.raises(StreamError,match='detector'):checked_events(data.tobytes(),'na22_prompt',0)


def test_maximum_survives_last_edge_roundoff(tmp_path):
    high=33/17
    assert high*80/80<high  # Last generated edge is one ULP below the observation.
    path=write(tmp_path/'endpoint.tpstream',[event(0,(high,1,1)),event(1,(0,0,0))])
    store=AnalysisStore()
    try:
        store.open_files([path]);loaded(store)
        for limits in (None,[0,high]):
            request=dict(metric='energy',detector='A',bins=80,range=limits)
            a=store.query(request)[0];b=analyze([path],request)
            assert a['series']==b['series']
            assert a['series'][0]['counts'][-1]==1
            assert sum(a['series'][0]['counts'])==a['series'][0]['valid']==2
    finally:store.close()
