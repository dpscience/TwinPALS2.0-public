# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Analytic waveform, truth isolation, bounded replay and persistence contracts."""
import copy
import json
import time
from pathlib import Path
import numpy as np
import pytest
from backend.m3_models import Profile, Channel, View
from backend.m3_signal import extract, gate, process, provenance
from backend.m3_engine import Acquisition
from backend.m1_store import ApplicationStore
from backend.m2_engine import PulseManager
from test_module2_physics import libraries, ROOT


def triangle(height=60, shift=0, positive=False):
    t=np.arange(0,80,.1)
    y=np.interp(t-shift,[0,20,24,34,80],[0,0,height,0,0])
    return t,y if positive else -y


def test_cfd_and_10_90_edges_independent_of_amplitude_polarity():
    for h in (30,180):
        for positive in (True,False):
            s=Channel(polarity='positive' if positive else 'negative').model_dump()
            f=extract(*triangle(h,1.7,positive),s)
            assert f['valid']
            assert f['cfd_ns']==pytest.approx(22.7,abs=1e-10)
            assert f['rise_ns']==pytest.approx(3.2,abs=1e-10)
            assert f['fall_ns']==pytest.approx(8,abs=1e-10)
            assert f['area']==pytest.approx(7*h,rel=.001)


def test_median_suppresses_isolated_spike_and_invalid_samples_are_rejected():
    t,v=triangle();v[600]=-600
    s=Channel(median_samples=3).model_dump()
    assert extract(t,v,s)['cfd_ns']==pytest.approx(21,abs=.1)
    t[8]=np.nan
    assert not extract(t,v,s)['valid']
    with pytest.raises(ValueError):Channel(median_samples=2)
    with pytest.raises(ValueError):Channel(start={'phs':{'low':50,'high':200}})


def pair(a=180,b=60,shift=1.2):
    ta,va=triangle(a);tb,vb=triangle(b,shift)
    meta=dict(id=8,start_ns=0,clipped=[False,False],pulses=[dict(channel=c,role=c,decay=4,record=c,onset_ns=20+c*shift,end_ns=34+c*shift,light_origin='scintillation') for c in (0,1)])
    return (100,meta,np.array([ta,va,tb,vb]),Profile().model_dump(),'na22')


@pytest.mark.parametrize('a,b,d,dt',[(180,60,'AB',1.2),(60,180,'BA',-1.2),(60,60,'SS',1.2),(180,180,None,None)])
def test_direction_stop_stop_and_no_double_counts(a,b,d,dt):
    r=process(pair(a,b));assert r['direction']==d
    assert r['dt_ns']==pytest.approx(dt) if dt is not None else r['dt_ns'] is None


def test_provenance_never_changes_cfd_or_gate_and_retains_pileup():
    item=pair();a=process(item)
    item[1]['pulses'].append(dict(item[1]['pulses'][0],decay=99,light_origin='cherenkov'))
    b=process(item)
    assert (a['features'],a['gates'],a['dt_ns'])==(b['features'],b['gates'],b['dt_ns'])
    assert b['truth']['category']=='pileup_multiple_decays' and b['truth']['origin']=='mixed'
    p=pair(60,60);p[1]['pulses'][0].update(role=1,record=1,primary_ids=[1]);p[1]['pulses'][1].update(primary_ids=[2])
    assert process(p)['truth']['category']=='annihilation_pair'
    p[1]['pulses'][0]['record']=2
    assert process(p)['truth']['category']=='unresolved'


def test_area_and_rotated_shape_filter():
    item=pair();f=process(item)['features'][0];s=item[3]['channels'][0]
    assert gate(f,s,False)[0]=='start'
    s['start']['area'].update(enabled=True,slope=7,below=1,above=1)
    assert gate(f,s,False)[0]=='start'
    s['start']['area']['intercept']=20
    assert gate(f,s,False)[1]=='Area filter'
    s['start']['area']['enabled']=False
    s['start']['shape'].update(enabled=True,rise=3.2,fall=8,radius_rise=.2,radius_fall=.2,angle_deg=40)
    assert gate(f,s,False)[0]=='start'
    assert gate(f,s,True)[1]=='ADC clipping'


@pytest.fixture(scope='module')
def pulse_stream(tmp_path_factory):
    root=tmp_path_factory.mktemp('m3');paths=libraries(root,count=16)
    store=ApplicationStore(root/'state',ROOT/'seed/factory_catalogue.json');manager=PulseManager()
    try:
        p=copy.deepcopy(store.module2);p.update(input_paths=paths,auto_seed=False,maximum=True,threads=1,output_path=str(root/'input.tppulses'))
        device=next(e for e in store.database.entries() if e['id']==p['digitization']['digitizer_id'])
        device['properties']['default_dead_ns']=2000;store.database.put(device,device['revision'])
        p['acquisition']['trigger']='either'
        manager.create(store,p);manager.thread.join(40)
        assert manager.current()['status']=='completed',manager.current()
        yield Path(manager.current()['paths'][0])
    finally:manager.shutdown();store.close()


def test_real_stream_serial_parallel_reset_rebin_and_restart(pulse_stream):
    from backend.m2_stream import Reader
    reader=Reader(pulse_stream);header=reader.header;reader.close()
    results=[]
    for workers in (1,2):
        profile=Profile(workers=workers,input_paths=[str(pulse_stream)],preview_count=7).model_dump()
        for c in profile['channels']:
            c['start']['phs']={'low':400,'high':500};c['stop']['phs']={'low':1,'high':400};c['minimum_height_mV']=1
        a=Acquisition(profile,[pulse_stream],[header])
        try:
            a.thread.join(40);assert a.status=='completed',a.state()
            assert a.seen>0 and len(a.preview)<=7 and len(a.diagnostics)<=6000
            q=a.query(View(low_ns=-100,high_ns=100,bin_ps=5).model_dump());assert a.accepted>0,q['rejected']
            results.append((a.accepted,q['spectra']))
            rebinned=a.query(View(low_ns=-100,high_ns=100,bin_ps=20,zero_ps=25).model_dump())
            assert sum(s['counts'] for s in q['spectra'])==sum(s['counts'] for s in rebinned['spectra'])
            assert 'headers' not in q
            wave=a.waveform(a.preview[-1]['sequence']);assert len(wave['samples'])==4 and wave['transport_truth']
            seen=a.seen;a.reset();assert a.state()['processed']==0 and a.seen==seen
            assert sum(s['counts'] for s in a.query(View().model_dump())['spectra'])==0
        finally:a.close()
    assert results[0]==results[1]


def test_private_state_and_profile_roundtrip(tmp_path):
    store=ApplicationStore(tmp_path,ROOT/'seed/factory_catalogue.json')
    try:
        assert store.module3['channels'][0]['cfd_percent']==25
        draft=copy.deepcopy(store.module3);draft['preview_count']=17
        store.save(store.profile,store.ui,'test',1,store.module2,draft)
    finally:store.close()
    store=ApplicationStore(tmp_path,ROOT/'seed/factory_catalogue.json')
    try:assert store.module3['preview_count']==17
    finally:store.close()


def test_settings_api_roundtrip_and_invalid_import(tmp_path):
    from api_client import TestClient
    from backend.app import create_app
    from backend.m3_models import Settings
    app=create_app(tmp_path/'state',ROOT)
    settings=Settings().model_dump(mode='json')
    settings['display'].update(bin_ps=10,zero_ps=125,scatter='shield',origin='mixed')
    path=str(tmp_path/'analysis.tpm3')
    with TestClient(app) as client:
        payload=dict(path=path,settings=settings)
        assert client.post('/api/m3/settings/save',json=payload).status_code==200
        assert client.post('/api/m3/settings/save',json=payload).status_code==409
        assert client.post('/api/m3/settings/open',json={'path':path}).json()==settings
        Path(path).write_text('{"format":"wrong"}')
        assert client.post('/api/m3/settings/open',json={'path':path}).status_code==422
        assert client.get('/api/m3/state').json()['profile']['channels'][0]['cfd_percent']==25


def test_cached_partitions_and_reset_boundary(pulse_stream):
    from backend.m2_stream import Reader
    from backend.m3_context import source_context
    from backend.m3_engine import CATEGORIES, ORIGINS
    reader=Reader(pulse_stream);header=reader.header;reader.close()
    assert source_context([pulse_stream],[header])['streams'][0]['source']=='na22'
    a=Acquisition(Profile().model_dump(),[],[])
    try:
        a.thread.join(5)
        # Commit on either side of a count-reset boundary, as the ordered reader does.
        a.commit([process(pair())],0)
        a.reset()
        records=[]
        for i in range(12):
            item=pair();item[1]['id']=100+i
            if i%2:item[1]['pulses'][1]['decay']=99
            if i%3==0:item[1]['pulses'][0]['light_origin']='cherenkov'
            records.append(process(item))
        a.commit(records,0)
        def counts(**kw):return sum(s['counts'] for s in a.query(View(**kw).model_dump())['spectra'])
        total=counts()
        assert total==12 and a.state()['processed']==12 and a.seen==13
        assert sum(counts(category=c) for c in CATEGORIES)==total
        assert sum(counts(origin=o) for o in ORIGINS)==total
        assert counts(scatter='none')+counts(scatter='any')==total
        assert counts(bin_ps=20,zero_ps=20)==total
        a.reset();assert counts()==0
    finally:a.close()


def test_live_reset_stop_and_restart(pulse_stream, monkeypatch):
    """Pause the actual reader between commits; no timing-sensitive sleep assertions."""
    import threading
    from backend.m2_stream import Reader
    r=Reader(pulse_stream);header=r.header;r.close()
    entered=threading.Event();resume=threading.Event()
    original=Acquisition.commit
    def controlled_commit(self, items, file):
        original(self,items,file)
        if self.seen==32:
            entered.set()
            if not resume.wait(15):raise TimeoutError('Test reader was not released')
    monkeypatch.setattr(Acquisition,'commit',controlled_commit)
    profile=Profile(input_paths=[str(pulse_stream)],preview_count=5).model_dump()
    a=Acquisition(profile,[pulse_stream],[header])
    try:
        assert entered.wait(15)
        assert a.thread.is_alive() and a.seen==32
        a.reset()
        assert a.state()['processed']==0 and a.accepted==0
        resume.set();a.thread.join(20)
        assert a.status=='completed' and a.seen>32
        assert a.state()['processed']==a.seen-32 and a.epoch==1
        assert len(a.preview)<=5
        full_count=a.seen
    finally:resume.set();a.close()
    entered.clear();resume.clear()
    a=Acquisition(profile,[pulse_stream],[header])
    try:
        assert entered.wait(15)
        a.cancel.set();resume.set();a.thread.join(10)
        assert not a.thread.is_alive() and a.status=='stopped' and a.seen==32
    finally:resume.set();a.close()
    monkeypatch.setattr(Acquisition,'commit',original)
    a=Acquisition(profile,[pulse_stream],[header])
    try:
        a.thread.join(20)
        assert a.status=='completed' and a.seen==full_count and a.epoch==0
        assert a.state()['processed']==full_count
    finally:a.close()



def test_nonuniform_sample_times_preserve_analytic_cfd_and_edges():
    rng=np.random.default_rng(87)
    t=np.r_[0,np.cumsum(rng.uniform(.045,.18,800))]
    for positive in (False,True):
        v=np.interp(t,[0,20,24,34,120],[0,0,180,0,0])
        s=Channel(polarity='positive' if positive else 'negative').model_dump()
        f=extract(t,v if positive else -v,s)
        assert f['valid']
        assert f['cfd_ns']==pytest.approx(21,abs=.03)
        assert f['rise_ns']==pytest.approx(3.2,abs=.03)
        assert f['fall_ns']==pytest.approx(8,abs=.06)
        assert f['area']==pytest.approx(1260,rel=.002)
