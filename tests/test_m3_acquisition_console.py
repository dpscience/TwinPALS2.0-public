# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Module 3 peak selection, full-readout area, settling, journal replay and independent resets."""
import threading
import numpy as np
import pytest
from backend.m3_signal import extract, gate
from backend.m3_models import Channel, Profile
from backend.m3_blocks import RESULT
from backend.m3_monitor import FeatureJournal
from backend.m3_engine import Acquisition
from backend.m3_context import selection_error
from test_module3 import pair, process, pulse_stream


def measured(points,rule='highest',**options):
    t=np.arange(80,dtype=float)
    v=-np.interp(t,*zip(*points))
    return extract(t,v,Channel(baseline_samples=8,**options).model_dump(),rule)


@pytest.mark.parametrize('method',['linear','cubic','akima'])
def test_first_and_highest_same_waveform_area_and_separate_flanks(method):
    points=[(0,0),(12,0),(16,40),(22,0),(34,0),(42,90),(58,0),(79,0)]
    a=measured(points,'first',interpolation=method);b=measured(points,'highest',interpolation=method)
    assert a['peak_ns']==16 and b['peak_ns']==42 and a['cfd_ns']<b['cfd_ns']
    assert a['area']==b['area']==pytest.approx(40*10/2+90*24/2)
    assert a['support'][1]<34 and b['support'][0]>22 and a['fall_ns']<b['fall_ns']


def test_valley_then_second_hump_and_incomplete_tail():
    # First falling 10% crossing near 26 ns is followed by a second 96% peak.
    points=[(0,0),(12,0),(18,100),(26,5),(32,96),(45,0),(79,0)]
    f=measured(points,'first')
    assert f['settled'] and f['f90']>32 and f['f10']>f['f90']
    assert f['fall_ns']==pytest.approx(13*80/96)
    unfinished=measured([(0,0),(12,0),(18,100),(26,5),(35,60),(79,3)],'first')
    assert unfinished['valid'] and not unfinished['settled'] and unfinished['fall_ns'] is None
    ch=Channel().model_dump();assert gate(unfinished,ch,False)==('start','')
    ch['start']['shape']['enabled']=True
    assert gate(unfinished,ch,False)==(None,'Rise/fall filter')


def test_settling_requires_three_samples_and_lower_secondary_hump():
    # Both selected peaks reach 100 mV. Only the length of the quiet gap changes.
    points=[(0,0),(12,0),(18,100),(25,0),(26,0),(27,5),(31,60),(41,0),(79,0)]
    connected=measured(points,'first')
    separated=measured([*points[:5],(27,0),*points[6:]],'first')
    assert connected['f90']==pytest.approx(18.7)
    assert connected['f10']==pytest.approx(41-10/6)
    assert connected['fall_ns']==pytest.approx(connected['f10']-18.7)
    assert separated['f90']==pytest.approx(18.7)
    assert separated['f10']==pytest.approx(24.3)
    assert separated['support'][1]==25 and connected['support'][1]==41


def test_area_includes_opposite_sign_interval_and_calibrated_time():
    t=np.r_[np.arange(45.)*.25,np.arange(45.,80.)*.33]
    y=np.interp(t,[0,4,6,8,13,17,19,24,28],[0,0,35,0,0,-4,0,0,0])
    settings=Channel(baseline_samples=8).model_dump();f=extract(t,4-y,settings)
    assert f['valid']
    expected=sum(abs((y[i]+y[i+1])/2)*(t[i+1]-t[i]) for i in range(len(t)-1))
    assert f['area']==pytest.approx(expected) and f['area']>70


def test_interpolation_on_calibrated_grid_against_scipy():
    si=pytest.importorskip('scipy.interpolate')
    from backend.m3_interpolation import slopes,evaluate
    rng=np.random.default_rng(43);t=np.cumsum(rng.uniform(.06,.19,130));y=np.sin(t)+.1*np.cos(2*t)
    i=np.arange(len(t)-1);u=np.full(len(i),.37);x=t[i]+u*np.diff(t)
    for method,ref in [('cubic',si.CubicSpline(t,y,bc_type='natural')),('akima',si.Akima1DInterpolator(t,y))]:
        np.testing.assert_allclose(evaluate(t,y,slopes(t,y,method),i,u),ref(x),rtol=1e-12,atol=1e-12)


def test_all_data_exact_odd_bin_replay_stable_axes_and_reset(tmp_path):
    rng=np.random.default_rng(37);rows=np.zeros(22341,dtype=RESULT);rows['values']=rng.uniform(0,1,(len(rows),2,5))*[499,1300,3,7,200]
    rows['values'][7000:,:,1:4]*=7;rows['values'][::13,1,3]=np.nan
    journal=FeatureJournal(tmp_path,threading.RLock(),[500,500],Profile().model_dump()['channels'])
    try:
        a=dict(kind='area',channel=0,nx=77,ny=53);b=dict(kind='shape',channel=1,nx=81,ny=49)
        journal.prepare_many([a,b])
        for block in np.array_split(rows,31):journal.append(block)
        for spec in [a,b,{**a,'nx':113},{**b,'axes':[0,17,0,29]}]:
            view=journal.snapshot(journal.prepare_many([spec]))[0]
            x,y=(0,1) if spec['kind']=='area' else (2,3)
            vals=rows['values'][:,spec['channel']];limits=view['axes']
            hist=np.histogram2d(vals[:,y],vals[:,x],bins=[view['ny'],view['nx']],range=[limits[2:],limits[:2]])[0]
            assert view['total']==len(rows) and view['visible']==int(hist.sum())
            assert dict(view['cells'])=={i:int(hist.flat[i]) for i in np.flatnonzero(hist)}
        journal.reset('area',0)
        assert [v['total'] for v in journal.snapshot(journal.prepare_many([a,b]))]==[0,len(rows)]
        journal.append(rows[:10]);assert journal.snapshot(journal.prepare_many([{**a,'ny':99}]))[0]['total']==10
    finally:journal.close()


def test_direction_resets_survive_rebin_and_filter_resets():
    a=Acquisition(Profile().model_dump(),[],[]);a.thread.join()
    try:
        items=[process(pair(160,60)),process(pair(60,160)),process(pair(60,60))]
        a.commit(items,0);a.reset_plot('spectrum','AB')
        q=a.query({'bin_ps':11,'compact':True});assert [s['counts'] for s in q['spectra']]==[0,1,1]
        a.reset_plot('phs','A');a.reset_plot('shape','B');a.commit(items,0)
        q=a.query({'bin_ps':13,'plots':[dict(kind=k,channel=i) for k in ('phs','area','shape') for i in (0,1)]})
        assert [s['counts'] for s in q['spectra']]==[1,2,2] and q['processed']==6
        assert [m['total'] for m in q['plots']]==[3,6,6,6,6,3]
    finally:a.close()


def test_multi_stream_compatibility():
    h=dict(run_id='run1',stream_id='s1',class_filter='all',settings_sha256='hash')
    assert selection_error([h])==''
    assert selection_error([h,{**h,'run_id':'run2','stream_id':'s2'}])
    assert selection_error([h,h]) and selection_error([h,{**h,'class_filter':'single'}])
    assert selection_error([{**h,'class_filter':'single'}])==''
    assert selection_error([{**h,'class_filter':'single'},{**h,'stream_id':'s2','class_filter':'pileup'}])


def test_finalized_queued_partial_keeps_its_original_record_boundary(pulse_stream,tmp_path):
    from backend.m2_stream import Reader
    from backend.m3_engine import open_snapshot
    from backend.m3_blocks import library,measured_blocks
    final=tmp_path/'queued.tppulses'
    final.write_bytes(pulse_stream.read_bytes())
    queued=final.with_suffix('.tppulses.part')
    r=Reader(final)
    try:
        entries=[(off,meta['id']) for off,meta,_ in r.records()]
    finally:r.close()
    assert len(entries)>2
    cutoff=entries[2][0]+20
    for native in ([False,True] if library() else [False]):
        r=open_snapshot(queued,cutoff)
        try:
            if native:
                ids=[int(i) for _,rows,_ in measured_blocks(r,lambda _:None,lambda:Profile().model_dump(),lambda:None) for i in rows['id']]
            else:ids=[meta['id'] for _,meta,_ in r.records()]
            assert ids==[m[1] for m in entries[:2]]
        finally:r.close()


def test_acquisition_requires_one_stream_even_for_distinct_runs(pulse_stream):
    with pytest.raises(ValueError,match='one Module 2'):
        Acquisition(Profile().model_dump(),[pulse_stream,pulse_stream],[{},{}])


def test_phs_overflow_and_full_area_population():
    from backend.m3_monitor import Grid,PlotSpec
    points=np.array([[499.,180.,1.,2.],[500.1,320.,1.,2.],[601.,900.,1.,2.]])
    p=Grid(PlotSpec(kind='phs',channel=0,nx=10,windows=[dict(low=450,high=500),dict(low=50,high=100)]),500)
    p.add(points)
    assert p.total==3 and p.cells[0,-1]==3 and p.above_adc==2 and p.windows==[1,0]
    g=Grid(PlotSpec(kind='area',channel=0,nx=83,ny=31),500)
    g.add(points[:1]);g.add(points[1:])
    hist=np.histogram2d(points[:,1],points[:,0],bins=[31,83],range=[g.axes[2:],g.axes[:2]])[0]
    assert g.total==g.cells.sum()==3
    np.testing.assert_array_equal(g.cells,hist)

def test_baseline_overlay_uses_measured_channel_samples_and_is_display_only(pulse_stream):
    from backend.m2_stream import Reader
    from backend.m3_models import Settings
    reader=Reader(pulse_stream)
    try:
        header=reader.header
    finally:
        reader.close()
    profile=Profile(workers=1).model_dump()
    acquisition=Acquisition(profile,[pulse_stream],[header])
    try:
        acquisition.thread.join(30)
        before=(acquisition.seen,acquisition.accepted,acquisition.revision)
        channels=Profile().model_dump()['channels']
        for channel,count in zip(channels,(21,47)):
            channel.update(baseline_samples=count,median_samples=5,minimum_height_mV=1e6)
        wave=acquisition.waveform(1,channels)
        for ch,count in enumerate((21,47)):
            t,raw=wave['samples'][2*ch:2*ch+2]
            feature=wave['features'][ch]
            assert not feature['valid']
            assert feature['baseline_region']==dict(count=count,start_ns=t[0],end_ns=t[count-1])
            assert feature['baseline']==pytest.approx(np.median(raw[:count]))
        channels[0]['baseline_samples']=4096
        invalid=acquisition.waveform(1,channels)['features'][0]
        assert not invalid['valid'] and 'baseline_region' not in invalid
        assert before==(acquisition.seen,acquisition.accepted,acquisition.revision)
        imported=Settings.model_validate({'monitor':{'autoscale':[True,False]}})
        assert imported.monitor.show_baseline is False
        imported.monitor.show_baseline=True
        assert Settings.model_validate_json(imported.model_dump_json()).monitor.show_baseline
    finally:
        acquisition.close()

def test_independent_phs_binning_preserves_gate_counts_and_reset_boundary(tmp_path):
    from pydantic import ValidationError
    from backend.m3_models import MonitorView
    assert MonitorView().phs_bins==(512,512)
    view=MonitorView(phs_bins=(73,1025))
    assert MonitorView.model_validate_json(view.model_dump_json()).phs_bins==(73,1025)
    for invalid in [(7,512),(512,2049),(48,)]:
        with pytest.raises(ValidationError):
            MonitorView(phs_bins=invalid)
    profile=Profile().model_dump()
    journal=FeatureJournal(tmp_path,threading.RLock(),[500,500],profile['channels'])
    rows=np.zeros(767,dtype=RESULT)
    rows['values'][:,0,0]=np.linspace(5,505,len(rows))
    rows['values'][:,1,0]=np.linspace(550,0,len(rows))
    def phs(bins):
        specs=[dict(kind='phs',channel=i,nx=n,windows=[profile['channels'][i][role]['phs'] for role in ('start','stop')]) for i,n in enumerate(bins)]
        return journal.snapshot(journal.prepare_many(specs))
    try:
        journal.append(rows)
        original=phs((512,512))
        for bins in [view.phs_bins,(8,2048)]:
            for i,grid in enumerate(phs(bins)):
                assert grid['nx']==bins[i] and grid['windows']==original[i]['windows']
                assert grid['total']==grid['visible']==sum(n for _,n in grid['cells'])==len(rows)
        journal.reset('phs',0)
        journal.append(rows[:17])
        left,right=phs((181,85))
        assert (left['total'],right['total'])==(17,len(rows)+17)
    finally:
        journal.close()

@pytest.mark.parametrize('sign',[1,-1])
def test_local_reference_uses_raw_window_before_the_selected_onset(sign):
    t=np.arange(120,dtype='f4')*.2
    drift=np.interp(np.arange(120),[0,16,38,119],[0,0,4,4])
    pulse=np.interp(np.arange(120),[0,56,62,77,119],[0,0,90,0,0])
    v=np.asarray(sign*(drift+pulse),dtype='f4')
    config=Channel(baseline_mode='pre_pulse',baseline_gap=5,baseline_samples=12,
                   polarity='positive' if sign==1 else 'negative').model_dump()
    f=extract(t,v,config)
    assert f['valid'] and f['peak_ns']==t[62] and f['height']==pytest.approx(90)
    assert f['onset_ns']==t[57] and f['baseline_start']==57-5-12
    assert f['baseline']==4*sign and f['cfd_ns']==pytest.approx(11.5)
    reference=extract(t,v,{**config,'baseline_mode':'readout'})
    assert reference['height']==94 and reference['cfd_ns']!=f['cfd_ns']
    missing=extract(t,v,{**config,'baseline_gap':60})
    assert not missing['valid'] and missing['reason']=='Insufficient pre-pulse baseline' and 'baseline_start' not in missing


def test_preview_revision_never_publishes_pre_edit_batch_and_counts_continue():
    a=Acquisition(Profile(preview_count=3).model_dump(),[],[])
    a.thread.join()
    try:
        a.status='running'
        sample=process(pair())
        a.commit([sample]*5,0)
        edit=[{**c,'baseline_mode':'pre_pulse'} for c in a.profile['channels']]
        generation=a.configure(edit,preview_count=2)['preview_generation']
        assert not a.preview
        a.commit([sample]*3,0)
        assert not a.preview and a.seen==8
        a._begin_batch();a.commit([sample]*3,0)
        assert a.state()['preview_generation']==generation
        assert [v['sequence'] for v in a.preview]==[10,11] and a.accepted==11
        assert not a.configure(edit,preview_count=4)['preview']
        assert a.configure(edit,preview_count=4)['preview_generation']==generation+1
    finally:a.close()


def test_saved_playlist_keeps_controls_and_requires_single_new_choice():
    old=Profile(workers=4).model_dump()
    raw={**old,'input_paths':['first.tppulses','second.tppulses']}
    assert Profile.from_saved(raw).model_dump()==old
    with pytest.raises(ValueError):Profile.model_validate(raw)
