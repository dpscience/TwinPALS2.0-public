# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Module 3 live measurement boundaries, PHS and additive spectral components."""
from collections import OrderedDict
import copy
import threading
import numpy as np
import pytest
from backend.m2_stream import Reader
from backend.m3_engine import Acquisition, LifetimeManager, CATEGORIES, ORIGINS, DIRECTIONS
from backend.m3_blocks import measured_blocks, library, RESULT
from backend.m3_measurements import classify, rejection_counts, PulseHeights
from backend.m3_models import Profile, View
from backend.m3_signal import process
from test_module3 import pair, pulse_stream


def test_live_processing_boundary_before_next_uncommitted_batch(pulse_stream,monkeypatch):
    reader=Reader(pulse_stream);header=reader.header;reader.close()
    entered=threading.Event();release=threading.Event()
    original=Acquisition.commit
    def hold(a,items,file):
        original(a,items,file)
        if a.seen==32:
            entered.set();assert release.wait(10)
    monkeypatch.setattr(Acquisition,'commit',hold)
    p=Profile(input_paths=[str(pulse_stream)]).model_dump()
    a=Acquisition(p,[pulse_stream],[header])
    try:
        assert entered.wait(10)
        prior=a.state()
        state=a.set_workers(1)
        for key in ('revision','preview_generation','epoch','total_processed','accepted'):
            assert state[key]==prior[key]
        assert state['profile']['workers']==1 and not state['pending']
        ch=copy.deepcopy(p['channels']);ch[0]['median_samples']=3;ch[1]['cfd_percent']=33
        ch[0]['start']['phs']['low']=120
        response=a.configure(ch,0)
        assert response['revision']==0 and response['pending'] and response['processed']==32
        # Editing is separate from the disk counters. The old pair stays inspectable.
        before=a.waveform(1);preview=a.waveform(1,ch)
        assert preview['revision']==0 and preview['smoothed'][0] and before['smoothed']==[None,None]
        assert a.state()['processed']==32
        release.set();a.thread.join(30)
        q=a.query({'compact':True})
        assert q['status']=='completed' and q['epoch']==0 and q['revision']==1 and q['revision_first']==33
        assert q['history'][0]['last']==32 and q['processed']==q['total_processed']
        assert a.waveform(32)['revision']==0 and a.waveform(33)['revision']==1
        assert q['accepted']+sum(q['rejected'].values())==q['processed']
        assert all(h['selected']==q['accepted'] for h in q['phs'])
    finally:release.set();a.close()


@pytest.mark.skipif(library() is None,reason='Native lifetime reader is unavailable')
def test_native_writer_finishes_previous_revision_before_live_change(pulse_stream,monkeypatch):
    from backend import m3_engine
    from backend.m3_measurements import POSITION
    waiting=threading.Event()
    resume_writer=threading.Event()
    next_block=threading.Event()
    applied=[]
    classify_rows=m3_engine.classify

    def slow_classify(rows,channels):
        if rows[0]['id']==1:
            waiting.set()
            assert resume_writer.wait(10)
        return classify_rows(rows,channels)

    def batches(reader,register,settings,cancel,index):
        for i in (1,2):
            if i==2:assert next_block.wait(10)
            cancel()
            profile=settings()
            applied.append((profile['workers'],profile['channels'][0]['cfd_percent']))
            rows=np.zeros(1,dtype=RESULT)
            rows['id']=i
            rows['values'][0,:,0]=(180,60)
            yield np.array([reader.start+i],dtype='<u8'),rows,reader.start+i

    monkeypatch.setattr(m3_engine,'measured_blocks',batches)
    monkeypatch.setattr(m3_engine,'classify',slow_classify)
    monkeypatch.setattr(Acquisition,'_scalar',Acquisition._native)
    reader=Reader(pulse_stream);header=reader.header;reader.close()
    profile=Profile(workers=1,input_paths=[str(pulse_stream)]).model_dump()
    job=Acquisition(profile,[pulse_stream],[header])
    try:
        assert waiting.wait(10)
        channels=copy.deepcopy(profile['channels'])
        channels[0]['cfd_percent']=37
        job.set_workers(3)
        assert job.configure(channels,0)['pending']
        next_block.set();resume_writer.set();job.thread.join(10)
        assert job.status=='completed' and job.seen==2,job.error
        assert applied==[(1,profile['channels'][0]['cfd_percent']),(3,37)]
        assert job.history[0]['last']==1 and job.revision_first==2
        assert np.fromfile(job.positions.name,dtype=POSITION)['revision'].tolist()==[0,1]
    finally:
        next_block.set();resume_writer.set();job.close()


def test_class_mix_per_bin_phs_reset_and_empty_view():
    a=Acquisition(Profile().model_dump(),[],[])
    try:
        a.thread.join(5)
        examples=[]
        for i in range(60):
            item=pair(a=180 if i%3==0 else 60,b=180 if i%3==1 else 60)
            item[1]['id']=i
            if i%2:item[1]['pulses'][1]['decay']=27
            if i%5==0:item[1]['pulses'].append(dict(item[1]['pulses'][0]))
            examples.append(process(item))
        a.commit(examples,0)
        all_data=a.query({'individual':True})
        for subset in ([],['correlated'],['correlated','accidental'],CATEGORIES):
            query=a.query({'categories':subset,'individual':True,'compact':True,'zero_ps':37,'bin_ps':10})
            for s in query['spectra']:
                expected={}
                for c in s['contributions']:
                    for x,count in c['points']:expected[x]=expected.get(x,0)+count
                assert dict(s['points'])==expected
                assert s['counts']==sum(query['direction_counts'][s['direction']][k] for k in subset)
            assert query['processed']==60 and query['accepted']==60
        assert all(sum(h['before'])==sum(h['accepted'])==60 for h in all_data['phs'])
        a.reset()
        assert not any(p['measured'] for p in a.query({})['phs'])
        with pytest.raises(ValueError):View(categories=['accidental','accidental'])
    finally:a.close()


def test_symmetric_channel_rejection_counts_and_bounded_height_overflow():
    reason=np.array([[0,5],[5,0],[5,5],[0,0]],dtype='u1')
    assert rejection_counts(reason,np.ones(4,dtype=bool))=={'Outside PHS windows':2,'Outside PHS windows / Outside PHS windows':1,'Both channels in Start windows':1}
    phs=PulseHeights([]);rows=np.zeros(2,dtype=RESULT);rows['values'][0,:,0]=1e20;rows['values'][1,:,0]=20
    phs.add(rows,np.array([True,False]))
    assert all(h['overflow']==[1,1] and h['selected']==1 and h['measured']==2 for h in phs.snapshot())


def test_restart_clears_every_monitor_and_preserves_an_inflight_reader(pulse_stream,monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace
    store=SimpleNamespace(resolve_path=Path)
    profile=Profile(input_paths=[str(pulse_stream)],workers=1).model_dump()
    manager=LifetimeManager()
    try:
        manager.start(store,profile)
        with manager.borrow() as old:
            old.thread.join(30)
            assert old.status=='completed'
            first=old.waveform(1)
            path=Path(old.temporary.name)
            specs=[dict(kind=kind,channel=ch,nx=16,ny=16) for kind in ('phs','area','shape') for ch in (0,1)]
            view=dict(compact=True,plots=specs)
            original=old.query(view)
            assert original['processed'] and original['preview'] and any(v['total'] for v in original['plots'])
            old.reset_plot('phs','A')
            old.reset_plot('area','B')
            old.reset_plot('shape','A')
            for direction in DIRECTIONS:old.reset_plot('spectrum',direction)
            run=Acquisition.run
            release=threading.Event()
            def wait_before_reading(acq):
                assert release.wait(20)
                run(acq)
            monkeypatch.setattr(Acquisition,'run',wait_before_reading)
            manager.start(store,profile,restart=old.id)
            try:
                with manager.borrow() as fresh:
                    empty=fresh.query(view)
                    assert empty['processed']==empty['total_processed']==empty['accepted']==empty['bytes_read']==0
                    assert empty['preview']==[] and empty['history']==[] and empty['spectrum_first']==[1,1,1]
                    assert all(p['total']==0 for p in empty['plots'])
                    assert all(p['measured']==0 for p in empty['phs'])
                    assert all(p['counts']==0 for p in empty['spectra'])
                    release.set()
                    fresh.thread.join(30)
                    replay=fresh.query(view)
                    assert replay['status']=='completed' and replay['processed']==original['processed']
                    for key in ('accepted','rejected','plots','spectra','phs','direction_counts'):
                        assert replay[key]==original[key],key
                    assert fresh.waveform(1)['features']==first['features']
            finally:release.set()
            assert manager.current()['id']!=old.id and path.exists()
            assert old.waveform(1)['id']==first['id']
            assert old.query({'bin_ps':12,'compact':True})['processed']==old.seen
        assert not path.exists()
    finally:manager.shutdown()


@pytest.mark.skipif(library() is None,reason='Native lifetime reader is unavailable')
@pytest.mark.parametrize('median,cfd,method,rule',[(1,25,'linear','highest'),(3,37,'linear','first'),(1,25,'cubic','first'),(3,37,'akima','highest'),(5,25,'akima','first'),(21,37,'cubic','highest')])
@pytest.mark.parametrize('reference',['readout','pre_pulse'])
def test_native_reference_classification_and_features(pulse_stream,median,cfd,method,rule,reference):
    reader=Reader(pulse_stream);scalar=Reader(pulse_stream)
    profile=Profile(workers=3,pulse_selection=rule).model_dump();profile['channels'][0].update(median_samples=median,cfd_percent=cfd,interpolation=method,baseline_mode=reference,baseline_gap=6)
    archive=Acquisition(profile,[],[]);archive.thread.join()
    try:
        enriched=OrderedDict();expected=[]
        for offset,meta,data in scalar.records():
            archive._enrich(scalar,meta,enriched)
            expected.append(process((offset,meta,data,profile,scalar.header['isotope'])))
        blocks=list(measured_blocks(reader,lambda rows:None,lambda:profile,lambda:None))
        offsets=np.concatenate([v[0] for v in blocks]);rows=np.concatenate([v[1] for v in blocks])
        assert len(rows)==len(expected)>0
        directions,_=classify(rows,profile['channels'])
        for offset,record,d,ref in zip(offsets,rows,directions,expected):
            assert offset==ref['offset'] and record['id']==ref['id']
            assert (None if d<0 else DIRECTIONS[d])==ref['direction']
            assert (CATEGORIES[record['category']],ORIGINS[record['origin']],int(record['scatter']))==(ref['truth']['category'],ref['truth']['origin'],ref['truth']['scatter_mask'])
            for ch,f in enumerate(ref['features']):
                assert (record['reason'][ch]==0)==f['valid']
                if f['valid']:
                    np.testing.assert_allclose(record['values'][ch],np.asarray([f[k] for k in ['height','area','rise_ns','fall_ns','cfd_ns']],dtype=float),rtol=2e-12,atol=2e-12)
    finally:reader.close();scalar.close();archive.close()

