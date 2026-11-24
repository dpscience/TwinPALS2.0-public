# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import copy
import hashlib
import json
from pathlib import Path
import struct
import time
import numpy as np
import pytest
from backend.m2_models import Profile, resolve, reference_profile
from backend.m2_physics import (pair_indices, calibrated_axes, quantize, classify,
    PULSE_DTYPE, source_pulses, acquire, digitize, aperture_errors, input_info, load_libraries)
from backend.m2_stream import Writer, Reader
from backend.m2_engine import PulseManager
from backend.m1_store import ApplicationStore, encode
from backend.streams import MAGIC, StreamError
from test_streams_v1 import event, frame, fixture_header, write

ROOT=Path(__file__).resolve().parents[1]
from backend.photomultiplier import component_entry
ENTRIES=[component_entry(e) for e in json.loads((ROOT/'seed/factory_catalogue.json').read_text(encoding='utf-8'))['items'] if e['category']=='digitizer']

def resolved():
    p=Profile().model_dump(mode='json');p['input_paths']=['one.tpstream','two.tpstream'];p['auto_seed']=False
    for c in p['channels']:c['attenuation_dB']=0
    r=resolve(p,ENTRIES);r['_libraries']=[TestLibrary(),TestLibrary()];return r

def reference_shape(t):
    t=np.maximum(np.asarray(t),0.)
    return t**3*np.exp(3-t)/27


def test_input_cards_and_combinations_use_energy_eligible_pulses(monkeypatch, tmp_path):
    summaries=[]
    for i,role in enumerate(('na22_prompt','na22_annihilation')):
        summaries.append({'header':{'role':role,'run_id':'same','settings_sha256':'same',
            'stream_id':str(i),'physics':{'minimum_energy_keV':50}},
            'completion':{'status':'completed','events':100,
            'detector_counts':{'interaction':[50,60],'response':[45,55]},
            'eligible_response_counts':[[10,20],[30,40]][i]}})
    monkeypatch.setattr('backend.m2_physics.inspect_stream',lambda p:summaries[int(p.stem)])
    info=input_info([tmp_path/'0.tpstream',tmp_path/'1.tpstream'])
    assert info['eligible_response_counts']==[[10,20],[30,40]]
    assert info['directional_combinations']['response']==[400,600]


class TestLibrary:
    # Independent four-stage gamma test pulse, one millivolt per electron.
    responses=[dict(order=4,tau_ns=1.,voltage_scale_mV=float(6*np.exp(3)/27),polarity='negative')]*2
    def onsets(self,row,ch):return np.zeros(int(row))


def pulse(time=0,channel=0,role=0,decay=0,height=30):
    q=np.zeros(1,dtype=PULSE_DTYPE);q['time']=time;q['channel']=channel;q['role']=role;q['decay']=decay;q['height']=height;q['record']=int(height);q['origin']=time;q['span']=40.;q['peak_time']=time+3;q['light_origin']=1
    return q

def libraries(folder,source='na22',count=20):
    from backend.m1_models import Profile as M1
    p=M1().model_dump(mode='json');p['source']=source
    result=[]
    roles=['na22_prompt','na22_annihilation'] if source=='na22' else ['co60_1173','co60_1332']
    for i,role in enumerate(roles):
        header=fixture_header(role);header.update(profile=p,run_id='fixture-run',stream_id=role,settings_sha256=hashlib.sha256(encode(p).encode()).hexdigest())
        from backend.analog_pmt import operating_point
        pmts=[e for e in json.loads((ROOT/'seed/factory_catalogue.json').read_text(encoding='utf-8'))['items'] if e['category']=='pmt']
        header['pmt_snapshot']=pmts
        header['analog_response']=[operating_point(next(e for e in pmts if e['id']==d['pmt_id'])) for d in p['detectors']]
        path=folder/(role+'.tpstream')
        rows=[event(j,a=(100,80,1),b=(120,100,2),mask=(1 if i==0 else 6) if source=='na22' else 3) for j in range(count)]
        write(path,rows,role=role,header=header)
        result.append(str(path))
    return result

def test_unique_shuffle_unequal_pools_and_correlated_cascades():
    a,b=pair_indices(3,5,15,'na22',True,np.random.default_rng(31))
    assert len(set(zip(a,b)))==15
    for x in range(3):assert sorted(b[a==x])==list(range(5))
    a,b=pair_indices(17,17,17,'co60',True,np.random.default_rng(3))
    assert np.array_equal(a,b) and len(set(a))==17
    with pytest.raises(ValueError,match='at most'):pair_indices(3,5,16,'na22',True,np.random.default_rng(3))
    with pytest.raises(ValueError):pair_indices(3,5,4,'na22',False,np.random.default_rng(3))

@pytest.mark.parametrize('entry',ENTRIES,ids=lambda e:e['id'])
def test_all_digitizer_presets_and_endpoint_convention(entry):
    p=Profile(input_paths=['a.tpstream','b.tpstream']).model_dump(mode='json')
    p['digitization']={'digitizer_id':entry['id']}
    n,rate=entry['default_samples'],entry['default_rate']
    p['acquisition']['trigger_delay_ns']=n/rate*.8
    r=resolve(p,ENTRIES);r['_libraries']=[TestLibrary(),TestLibrary()]
    axes=calibrated_axes({**r['profile']['digitization'],'cell_widths_ns':r['cell_intervals_ns']},entry['architecture'])
    assert r['window_ns']==pytest.approx(n/rate)
    if entry['architecture']=='uniform_adc':assert axes[0,-1]==pytest.approx((n-1)/rate)
    assert axes.shape==(2,n) and np.all(np.diff(axes)>0)
    data,_,_,_=digitize(0,pulse(),r,np.random.default_rng(3),np.zeros((2,n)))
    assert data.shape==(4,n) and np.isfinite(data).all()


def test_setup_cannot_override_database_sampling():
    p=reference_profile(resolved()['profile'])
    p['digitization']['rate_GSps']=5.12
    with pytest.raises(ValueError,match='Extra inputs'):resolve(p,ENTRIES)


def test_cell_width_rotation_and_physical_cell_alignment():
    d={'samples':4,'rate_GSps':1,'cell_widths_ns':[[.8,1.1,.9,1.2],[1.2,.9,1.1,.8]]}
    t=calibrated_axes(d,'switched_capacitor',2)
    assert t[0]==pytest.approx([0,.9,2.1,2.9])
    assert t[0,2]==pytest.approx(t[1,2])
    assert np.diff(t[1])==pytest.approx([1.1,.8,1.2])


def test_physical_cell_errors_rotate_and_repeat_without_random_jitter():
    d={'samples':4,'aperture_jitter_ns':0}
    fixed=np.array([[.001,.002,-.001,-.002],[.003,-.003,.004,-.004]])
    rng=np.random.default_rng(3)
    expected=fixed[:,[2,3,0,1]]
    assert np.array_equal(aperture_errors(d,'switched_capacitor',2,rng,fixed),expected)
    assert np.array_equal(aperture_errors(d,'switched_capacitor',2,rng,fixed),expected)
    assert np.array_equal(aperture_errors(d,'uniform_adc',2,rng,fixed),fixed)


def test_aperture_jitter_rms_independence_and_dlt_coordinate_semantics():
    d={'samples':1024,'aperture_jitter_ns':.0025}
    rng=np.random.default_rng(15);fixed=rng.normal(0,.005,(2,1024))
    assert np.std(fixed)==pytest.approx(.005,rel=.04)
    random=np.array([aperture_errors(d,'switched_capacitor',0,rng,fixed)-fixed for _ in range(128)])
    assert np.std(random)==pytest.approx(.0025,rel=.01)
    assert abs(np.corrcoef(random[0].ravel(),random[1].ravel())[0,1])<.06
    r=resolved();r['profile']['digitization'].update(noise_sigma_mV=0,irf_sigma_ns=0,input_bandwidth_MHz=0)
    waveform,cell,baseline,_=digitize(0,pulse(),r,np.random.default_rng(9),fixed)
    axes=calibrated_axes(r['profile']['digitization'],'switched_capacitor',cell)
    assert not np.array_equal(waveform[[0,2]],axes.astype('<f4'))
    # DLT coordinates are saved and used to evaluate the pulse. A hidden
    # residual error would violate this independently evaluated waveform.
    expected=quantize(-30*reference_shape(waveform[0]),1000,14)
    np.testing.assert_allclose(waveform[1],expected,atol=.0611)
    assert baseline==[0,0] and np.all(np.diff(waveform[[0,2]],axis=1)>0)
    ideal=copy.deepcopy(r);ideal['profile']['digitization']['aperture_jitter_ns']=0
    clean,*_=digitize(0,pulse(),ideal,np.random.default_rng(9),np.zeros((2,1024)))
    assert not np.array_equal(waveform[[1,3]],clean[[1,3]])


def test_digitizer_irf_broadens_pair_timing_and_zero_disables_it():
    r=resolved();d=r['profile']['digitization']
    d.update(samples=1024,rate_GSps=50,noise_sigma_mV=0,fixed_jitter_ns=0,
             aperture_jitter_ns=0,input_bandwidth_MHz=0,irf_sigma_ns=.0025)
    r['digitizer'].update(architecture='uniform_adc',adc_bits=24)
    pulses=np.concatenate([pulse(time=4,height=480),pulse(time=4,channel=1,height=480)])
    def cf(t,v):
        y=-v; level=y.max()/2; k=np.flatnonzero(y>=level)[0]
        return t[k-1]+(level-y[k-1])*(t[k]-t[k-1])/(y[k]-y[k-1])
    rng=np.random.default_rng(35775);deltas=[]
    for _ in range(5000):
        w,*_=digitize(0,pulses,r,rng,np.zeros((2,1024)))
        deltas.append(cf(w[2],w[3])-cf(w[0],w[1]))
    assert np.std(deltas)*2.354820045*1000==pytest.approx(8.3255,rel=.035)
    d['irf_sigma_ns']=0
    w,*_=digitize(0,pulses,r,rng,np.zeros((2,1024)))
    assert np.array_equal(w[1],w[3])


@pytest.mark.parametrize('kind',['discrete','gaussian','lorentzian','lognormal'])
def test_distributed_specific_lifetimes_and_exponential_delays(kind):
    from backend.m2_models import Lifetime
    from backend.m2_lifetimes import lifetime_grid,sample_lifetimes
    c=Lifetime(tau_ns=2,intensity=1,distribution=kind,spread=.2,lower_ns=1,upper_ns=4,grid_points=4001).model_dump()
    grid,weight=lifetime_grid(c)
    assert weight.sum()==pytest.approx(1) and (grid>0).all()
    delays,indices=sample_lifetimes([c],250000,np.random.default_rng(87))
    # Mixture moments: E[t]=E[tau], E[t²]=2 E[tau²].
    assert delays.mean()==pytest.approx(np.sum(grid*weight),rel=.012)
    assert np.mean(delays**2)==pytest.approx(2*np.sum(grid**2*weight),rel=.02)
    assert not indices.any() and np.all(delays>=0)
    if kind=='gaussian':assert np.sum(grid*weight)==pytest.approx(2,abs=1e-5)
    if kind=='lorentzian':
        import math
        z=(math.atan(10)-math.atan(-5))/math.pi
        expected=2+.2/(2*math.pi*z)*math.log((2**2+.2**2)/(1**2+.2**2))
        assert np.sum(grid*weight)==pytest.approx(expected,abs=1e-5)
    if kind=='lognormal':assert np.sum(grid*weight)==pytest.approx(2*np.exp(.2**2/2),abs=.003)


def test_five_lifetime_limit_and_distribution_validation():
    from backend.m2_models import Lifetime
    from pydantic import ValidationError
    with pytest.raises(ValidationError):Profile(lifetimes=[Lifetime()]*6)
    with pytest.raises(ValidationError):Lifetime(distribution='gaussian',lower_ns=1,upper_ns=.5)
    with pytest.raises(ValidationError):Lifetime(distribution='lognormal',tau_ns=0)

def test_both_adc_rails():
    assert quantize(np.array([-1e4,-.5,0,.5,1e4]),256,8)==pytest.approx([-128,-1,0,1,127])


def test_source_clock_lifetime_and_tts_are_not_double_counted():
    r=resolved();p=r['profile'];p['activity_Bq']=1e6
    p['lifetimes']=[{'name':'sample','origin':'sample','tau_ns':2.,'intensity':1}]
    info={'counts':[50000,50000],'isotope':'na22'}
    class Library:
        values=np.tile([100,1.,100,1.],(50000,1))
        light_origins=np.ones((50000,2),dtype='u1')
        start=np.full((50000,2),17.);span=np.full((50000,2),40.);peaks=np.full((50000,2),100.)
        def __getitem__(self,key):return self.values[key]
    lib=Library()
    pulses,duration,_=source_pulses(r,info,[lib,lib],np.random.default_rng(92),lambda:None,50000)
    one=pulses[(pulses['role']==0)&(pulses['channel']==0)]
    residual=one['time']-one['source_time']-17
    assert np.max(np.abs(residual))<1e-7  # M2 adds no new PMT transit or TTS draw.
    assert abs(np.mean(residual))<.0003
    assert duration/50000==pytest.approx(1000,rel=.02)
    two=pulses[pulses['role']==1]
    assert np.mean(two['lifetime'])==pytest.approx(2,rel=.02)
    a=np.sort(two[two['channel']==0],order='decay');b=np.sort(two[two['channel']==1],order='decay')
    assert np.array_equal(a['lifetime'],b['lifetime'])

def test_subthreshold_pulse_superposition_can_trigger():
    r=resolved();p=r['profile'];p['acquisition'].update(trigger='A',trigger_delay_ns=r['window_ns']-1)
    p['digitization']['noise_sigma_mV']=0
    weak=np.concatenate([pulse(height=6),pulse(height=6,decay=1)])
    rows=list(acquire(weak,r,np.random.default_rng(1),lambda:None,lambda f:None))
    assert len(rows)==1 and rows[0][0]['class']=='pileup'
    assert len(list(acquire(pulse(height=6),r,np.random.default_rng(1),lambda:None,lambda f:None)))==0

def test_nonparalyzable_dead_time_keeps_absolute_source_clock():
    r=resolved();p=r['profile'];p['acquisition'].update(trigger='A',dead_ns=250,trigger_delay_ns=99)
    p['digitization']['noise_sigma_mV']=0
    r['window_ns']=100
    pulses=np.concatenate([pulse(time=t,decay=i) for i,t in enumerate([0,200,400])])
    rows=list(acquire(pulses,r,np.random.default_rng(1),lambda:None,lambda f:None))
    assert len(rows)==2
    assert rows[1][0]['trigger_ns']-rows[0][0]['trigger_ns']==pytest.approx(400,abs=.001)

@pytest.mark.parametrize('pulses,expected',[(np.concatenate([pulse(),pulse(channel=1,role=1)]),'true_A_start'),(np.concatenate([pulse(role=1),pulse(channel=1)]),'true_B_start'),(np.concatenate([pulse(),pulse(channel=1)]),'same_primary_1'),(np.concatenate([pulse(role=1),pulse(channel=1,role=1)]),'same_primary_2'),(np.concatenate([pulse(),pulse(channel=1,decay=2)]),'accidental')])
def test_truth_classification(pulses,expected):assert classify(pulses)[0]==expected

def test_real_stream_contract_rejects_roles_and_validates_every_crc(tmp_path):
    paths=libraries(tmp_path);info=input_info(paths[::-1]);assert info['isotope']=='na22' and info['max_decays']==400
    libs=load_libraries(info,lambda:None,lambda f:None)
    assert libs[0][0]==pytest.approx([80,1,100,2])
    with pytest.raises(ValueError):input_info([paths[0],paths[0]])
    payload=bytearray(Path(paths[0]).read_bytes());payload[-80]^=1;Path(paths[0]).write_bytes(payload)
    with pytest.raises(StreamError,match='CRC'):load_libraries(info,lambda:None,lambda f:None)

@pytest.mark.parametrize('isotope',['na22','co60'])
def test_legacy_class_setting_writes_one_flagged_stream_and_reimports(tmp_path,isotope):
    paths=libraries(tmp_path,isotope,30)
    store=ApplicationStore(tmp_path/'state',ROOT/'seed/factory_catalogue.json');manager=PulseManager()
    try:
        p=copy.deepcopy(store.module2);p.update(input_paths=paths,auto_seed=False,waveform_pairs=30,output_mode='classes')
        p['acquisition']['trigger']='either';p['activity_Bq']=1e7
        partial=copy.deepcopy(p)
        partial['lifetimes'][0]['intensity']=.1
        if isotope=='co60':
            p=partial  # The prompt cascade is independent of stored positron-lifetime settings.
        else:
            with pytest.raises(ValueError,match='intensities must add up'):
                manager.check(store,partial)
        job=manager.create(store,p);manager.thread.join(20)
        result=manager.current();assert result['status']=='completed',result['message']
        assert result['waveforms']>0 and len(result['paths'])==1
        assert result['header']['profile']['output_mode']=='combined'
        before=manager.analysis.query({});wave=manager.analysis.waveform(0)
        manager.import_streams(store,result['paths']);manager.thread.join(20)
        assert manager.current()['status']=='completed',manager.current()['message']
        after=manager.analysis.query({});assert manager.analysis.waveform(0)['timeline']==wave['timeline']
        assert before['counts']==after['counts'] and before['total']==after['total']
        assert before['persistence']==after['persistence']
        for a,b in zip(before['plots'],after['plots']):assert a==b
        # Original primary origin and record IDs survive combined output.
        assert all(q['role'] in (0,1) for q in wave['pulses'])
    finally:manager.shutdown();store.close()


def trigger_model():
    # A private uniform test instrument, not a shipped generic database entry.
    e=copy.deepcopy(next(e for e in ENTRIES if e['architecture']=='uniform_adc'))
    e.update(id='test-instrument',default_rate=5.12,default_samples=512,
        default_noise_sigma_mV=0,default_irf_sigma_ps=0,default_dead_ns=0,
        voltage_min_mV=-500,voltage_max_mV=500,input_bandwidth_MHz=0)
    p=Profile(input_paths=['one.tpstream','two.tpstream']).model_dump(mode='json')
    p['digitization']={'digitizer_id':e['id']}
    p['acquisition'].update(trigger_delay_ns=80,coincidence_ns=10)
    for c in p['channels']:c['attenuation_dB']=0
    r=resolve(p,[e]);r['_libraries']=[TestLibrary(),TestLibrary()];return r


@pytest.mark.parametrize('logic,expected',[('A',3),('B',3),('either',4),('coincidence',2)])
def test_all_trigger_logics_and_no_empty_windows(logic,expected):
    r=trigger_model();r['profile']['acquisition']['trigger']=logic
    q=np.concatenate([pulse(time=t,channel=ch,decay=i) for i,(t,ch) in enumerate([(0,0),(8,1),(500,1),(508,0),(1000,0),(1600,1)])])
    records=list(acquire(q,r,np.random.default_rng(76),lambda:None,lambda f:None))
    assert len(records)==expected
    assert all(m['pulses'] for m,_ in records)
    if logic in ('A','B'):assert all(m['trigger_channel']=='AB'.index(logic) for m,_ in records)
    if logic=='coincidence':assert [m['trigger_channel'] for m,_ in records]==[1,0]


@pytest.mark.parametrize('spacing,accepted',[(9.99,True),(10.01,False)])
def test_coincidence_crossing_interval_boundary(spacing,accepted):
    r=trigger_model();q=np.concatenate([pulse(),pulse(time=spacing,channel=1)])
    records=list(acquire(q,r,np.random.default_rng(5),lambda:None,lambda f:None))
    assert bool(records)==accepted
    if accepted:
        c=r['profile']['channels'][1]
        grid=np.linspace(0,3,300001);expected=spacing+np.interp(c['threshold_mV']/30,reference_shape(grid),grid)
        assert records[0][0]['trigger_ns']==pytest.approx(expected,abs=.002)


def test_trigger_delay_shifts_saved_window_without_changing_crossing():
    r=trigger_model();r['profile']['acquisition']['trigger']='A'
    result=[]
    for delay in (10,80,100):
        r['profile']['acquisition']['trigger_delay_ns']=delay
        m,w=next(acquire(pulse(time=200),r,np.random.default_rng(9),lambda:None,lambda f:None))
        assert m['end_ns']-m['trigger_ns']==pytest.approx(delay)
        assert m['end_ns']-m['start_ns']==pytest.approx(100)
        assert w[0,-1]==pytest.approx(100-1/5.12)
        assert m['pulses'][0]['onset_ns']+m['start_ns']==200
        result.append(m['trigger_ns'])
    assert result==[result[0]]*3
    r['profile']['acquisition']['trigger_delay_ns']=101
    with pytest.raises(ValueError,match='trigger delay'):resolve(reference_profile(r['profile']),[r['digitizer']])


@pytest.mark.parametrize('logic',['A','B','either','coincidence'])
def test_independent_channel_thresholds_keep_one_common_acquisition_delay(logic):
    r=trigger_model();p=r['profile'];p['acquisition']['trigger']=logic
    channels=p['channels'];channels[0]['threshold_mV']=5;channels[1]['threshold_mV']=20
    q=np.concatenate([pulse(time=200,channel=0),pulse(time=200,channel=1)])
    grid=np.linspace(0,3,300001);expected=[200+np.interp(c['threshold_mV']/30,reference_shape(grid),grid) for c in channels]
    records=list(acquire(q,r,np.random.default_rng(9),lambda:None,lambda f:None))
    assert len(records)==1
    m,w=records[0];accepted=0 if logic in ('A','either') else 1
    assert m['trigger_channel']==accepted
    assert m['trigger_ns']==pytest.approx(expected[accepted],abs=.002)
    assert m['end_ns']-m['trigger_ns']==pytest.approx(80)
    assert m['end_ns']-m['start_ns']==pytest.approx(100)
    assert np.array_equal(w[0],w[2])  # Both channels share the saved interval.
    # Changing only B cannot suppress A, but it must suppress B-only and AND.
    channels[1]['threshold_mV']=40
    changed=list(acquire(q,r,np.random.default_rng(9),lambda:None,lambda f:None))
    assert len(changed)==(1 if logic in ('A','either') else 0)
    if changed:assert changed[0][0]['trigger_ns']==pytest.approx(expected[0],abs=.002)


def test_dead_time_context_preserves_unrecorded_contributions_and_rearms():
    r=trigger_model();r['profile']['acquisition'].update(trigger='A',dead_ns=250,trigger_delay_ns=80)
    q=np.concatenate([pulse(time=t,decay=i) for i,t in enumerate([100,250,500])])
    rows=list(acquire(q,r,np.random.default_rng(2),lambda:None,lambda f:None))
    assert len(rows)==2
    first=rows[0][0]
    assert len(first['pulses'])==1
    assert [p['decay'] for p in first['timeline']['pulses']]==[0,1]
    assert first['busy_until_ns']==pytest.approx(first['end_ns']+250)
    assert rows[1][0]['trigger_ns']-first['trigger_ns']==pytest.approx(400,abs=.002)


def test_long_dead_time_context_is_bounded_without_losing_waveform_truth():
    from backend.m2_physics import timeline_context
    q=np.concatenate([pulse(time=t,decay=t) for t in range(10000)])
    context=timeline_context(q,0,100,9999)
    assert context['total']==10000 and len(context['pulses'])==256
    assert context['pulses'][0]['decay']==0 and context['pulses'][-1]['decay']==9999
    assert set(range(100))<=set(p['decay'] for p in context['pulses'])


def test_simultaneous_or_crossings_are_one_trigger_with_zero_stop_delay():
    r=trigger_model();r['profile']['acquisition'].update(trigger='either',trigger_delay_ns=0,dead_ns=0)
    q=np.concatenate([pulse(),pulse(channel=1,role=1)])
    rows=list(acquire(q,r,np.random.default_rng(10),lambda:None,lambda f:None))
    assert len(rows)==1 and rows[0][0]['class']=='true_A_start'
    assert rows[0][0]['end_ns']==rows[0][0]['trigger_ns']
