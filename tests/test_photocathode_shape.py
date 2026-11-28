# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Opt-in response options must survive transport, replay and ADC sampling."""
import copy
import json
import time
from pathlib import Path

import numpy as np
import pytest

from backend import analog_pmt as pmt
from backend.m1_models import Profile
from backend.m1_resolve import resolve_profile
from backend.material_readiness import missing_properties
from backend.photocathode_film import normal_incidence_plot
from backend.streams import validate_analog_responses

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT/'seed/factory_catalogue.json'
ENTRIES = json.loads(SEED.read_text(encoding='utf-8'))['items']
TUBES = [e for e in ENTRIES if e['category']=='pmt']


@pytest.mark.parametrize('original', TUBES, ids=lambda e:e['id'])
def test_factory_films_are_optional_sourced_and_conserve_light(original):
    e = copy.deepcopy(original)
    assert e['properties']['cathode_reflections'] is True
    assert not missing_properties(e)
    rows = np.array(normal_incidence_plot(e))
    assert np.all(np.diff(rows[:,0])>0)
    assert np.all((rows[:,1:]>=-1e-12)&(rows[:,1:]<=1+1e-12))
    np.testing.assert_allclose(rows[:,1:].sum(axis=1), 1., atol=1e-12)
    assert np.max(rows[:,1])>.01 and np.max(rows[:,2])>.01


def test_film_requires_all_three_sources_and_common_band_only_when_enabled():
    e = copy.deepcopy(TUBES[0])
    e['properties']['cathode_reflections'] = True
    from backend.material_database import validated_entry
    e['provenance']['references'].append(dict(title='Local optical scan, sample A, run 7',url='',properties=['cathode_k']))
    assert validated_entry(e)['provenance']['references'][-1]['title'].endswith('run 7')
    for ref in e['provenance']['references']:
        ref['properties'] = [key for key in ref['properties'] if key!='cathode_k']
    assert 'Cathode extinction coefficient k reference' in missing_properties(e)
    next(c for c in e['curves'] if c['name']=='cathode_k').update(x_unit='nm',points=[[1000,1.],[1010,1.]])
    assert 'Overlapping cathode n and k spectral range' in missing_properties(e)
    e['properties']['cathode_reflections'] = False
    assert not missing_properties(e)


def test_film_backfill_preserves_user_changes_and_runs_only_once(tmp_path):
    from backend.material_database import MaterialDatabase
    old=copy.deepcopy(TUBES[:4])
    for entry in old:
        for key in ('cathode_reflections','cathode_film_nm'):
            entry['properties'].pop(key)
        entry['curves']=[c for c in entry['curves'] if c['name'] not in ('cathode_n','cathode_k')]
        entry['provenance']['references']=[r for r in entry['provenance']['references']
            if not set(r['properties']).intersection({'cathode_film_nm','cathode_n','cathode_k'})]
    # The immediately preceding catalogue already shipped both curves, switched off.
    removed_curve=copy.deepcopy(TUBES[6])
    removed_curve['builtin']=False
    removed_curve['properties']['cathode_reflections']=False
    removed_curve['curves']=[c for c in removed_curve['curves'] if c['name']!='cathode_n']
    old.append(removed_curve)
    old.extend(copy.deepcopy(TUBES[4:6]))
    for e in old[-2:]:
        e['properties']['cathode_reflections']=False
    prior=tmp_path/'prior.json'
    prior.write_text(json.dumps({**json.loads(SEED.read_text(encoding='utf-8')),'items':old,'factory_updates':[]}),encoding='utf-8')
    db=MaterialDatabase(tmp_path/'db.tpdb',prior)
    edited=db.put(old[1],old[1]['revision'])
    user_off=db.put(old[-1],old[-1]['revision'])
    db.delete(old[2]['id'],old[2]['revision'])
    first=MaterialDatabase(db.path,SEED)
    rows={e['id']:e for e in first.entries()}
    assert rows[old[0]['id']]['properties']['cathode_reflections'] is True
    assert rows[old[-2]['id']]['properties']['cathode_reflections'] is True
    assert rows[user_off['id']]==user_off
    assert rows[removed_curve['id']]==removed_curve
    assert not missing_properties({**rows[old[0]['id']],'properties':{**rows[old[0]['id']]['properties'],'cathode_reflections':True}})
    assert rows[edited['id']]['properties']['cathode_reflections'] is True
    assert not rows[edited['id']]['builtin'] and old[2]['id'] not in rows
    revision=first.revision
    assert MaterialDatabase(db.path,SEED).revision==revision


@pytest.mark.parametrize('gap', [0.,2.])
def test_external_qe_recovered_at_entrance_window(gap):
    from backend.photocathode_film import resolve_film
    from backend.m1_resolve import HC_EV_NM
    e = copy.deepcopy(TUBES[0])
    e['properties'].update(qe_reference_plane='external_tube',cathode_gap_mm=gap,
                           cathode_film_nm=20.,window_thickness_mm=2.)
    for c in e['curves']:
        if c['name'] in ('cathode_n','cathode_k'):
            c.update(x_unit='eV',points=[[2.,2.],[3.,2.]])
    qe=[[2.,.16],[3.,.21]]
    film = resolve_film(e,dict(refractive_index=1.5,absorption_length_mm=40.),qe)
    normal=np.array(film['normal'])[::-1]
    energy=HC_EV_NM/normal[:,0]
    reflect,absorb=normal[:,1],normal[:,2]
    glass_r=.04
    bulk=np.exp(-2./40.)
    forward=(1.-glass_r)*bulk
    returning=glass_r*bulk**2
    if gap:
        forward=forward*(1.-glass_r)/(1.-glass_r*returning)
        returning=glass_r+(1.-glass_r)**2*returning/(1.-glass_r*returning)
    detected=forward*absorb*np.array(film['escape'])[:,1]/(1.-returning*reflect)
    np.testing.assert_allclose(detected,np.interp(energy,*np.transpose(qe)),atol=1.e-12)
    with pytest.raises(ValueError,match='exceeds reference absorption'):
        resolve_film(e,dict(refractive_index=1.5,absorption_length_mm=40.),[[2.,1.],[3.,1.]])


def test_inconsistent_film_is_rejected_before_saving(tmp_path):
    from backend.material_database import MaterialDatabase
    db=MaterialDatabase(tmp_path/'db.tpdb',SEED)
    e=copy.deepcopy(TUBES[0])
    e['properties'].update(cathode_reflections=True,cathode_film_nm=.001)
    revision=db.revision
    with pytest.raises(ValueError,match='exceeds reference absorption'):
        db.put(e,e['revision'])
    assert db.revision==revision


def test_reflections_require_both_catalogue_support_and_detector_choice():
    profile=Profile().model_dump(mode='json')
    a,b=profile['detectors']
    assert a.pop('pmt_cathode_reflections') and b.pop('pmt_cathode_reflections')
    def modes(entries):
        detectors=resolve_profile(profile,entries)[0]['detectors']
        return [('film' in d['sensor'],d['window'].get('bulk_attenuation_disabled_for_external_qe',False)) for d in detectors]
    assert modes(ENTRIES)==[(True,False),(True,False)]
    a['pmt_cathode_reflections']=False
    assert modes(ENTRIES)==[(False,True),(True,False)]
    a['pmt_cathode_reflections'],b['pmt_cathode_reflections']=True,False
    assert modes(ENTRIES)==[(True,False),(False,True)]
    entries=copy.deepcopy(ENTRIES)
    tube=next(e for e in entries if e['id']==a['pmt_id'])
    tube['properties']['cathode_reflections']=False
    tube['curves']=[c for c in tube['curves'] if c['name'] not in ('cathode_n','cathode_k')]
    assert modes(entries)==[(False,True),(False,True)]


def test_unused_film_does_not_invalidate_pmt():
    from backend.material_database import validated_entry
    e=copy.deepcopy(TUBES[0])
    e['properties'].update(cathode_reflections=False,cathode_film_nm=0.)
    next(c for c in e['curves'] if c['name']=='cathode_n')['points'][0][1]=-1.
    assert not missing_properties(validated_entry(e))
    e['properties']['cathode_reflections']=True
    with pytest.raises(ValueError,match='Cathode optics'):
        validated_entry(e)
    next(c for c in e['curves'] if c['name']=='cathode_n')['points']=[]
    e['properties']['cathode_film_nm']=20.
    with pytest.raises(ValueError,match='at least two points'):
        validated_entry(e)
    e['properties']['cathode_reflections']=False
    assert not missing_properties(validated_entry(e))


def test_profile_legacy_unity_and_independent_fractional_response():
    profile = Profile().model_dump(mode='json')
    a,b=profile['detectors']
    assert a.pop('pmt_shape_factor')==1. and a.pop('pmt_shape_enabled') is False
    ref=resolve_profile(profile,ENTRIES)[0]['analog_response']
    a.update(pmt_shape_enabled=False,pmt_shape_factor=.4)
    b.update(pmt_shape_enabled=True,pmt_shape_factor=1.)
    assert resolve_profile(profile,ENTRIES)[0]['analog_response']==ref
    a.update(pmt_shape_enabled=True,pmt_shape_factor=2.37/ref[0]['order'])
    changed=resolve_profile(profile,ENTRIES)[0]['analog_response']
    assert changed[1]==ref[1]
    assert changed[0]['order']==pytest.approx(2.37)
    for key in ('gain','charge_C','rise_ns','transit_ns','tts_sigma_ns'):
        assert changed[0][key]==ref[0][key]
    assert changed[0]['tau_ns']!=ref[0]['tau_ns']
    validate_analog_responses(changed)
    a['pmt_shape_factor']=.0001
    with pytest.raises(ValueError,match='effective order'):
        resolve_profile(profile,ENTRIES)


@pytest.mark.parametrize('order,ratio',[(2.37,.25),(5.5,1.),(12.25,3.),(30.75,10.)])
def test_fractional_filtered_pulse_matches_independent_convolution(order,ratio):
    if pmt.native_library() is None:
        pytest.skip('Native digitizer unavailable')
    from backend.native_digitizer import binding,sample_channel
    from backend.m2_physics import quantize
    from types import SimpleNamespace
    tau=.5
    response=dict(order=order,tau_ns=tau,polarity='positive',voltage_scale_mV=20.)
    pole=tau*ratio
    onsets=np.array([0.,.46,1.1])
    t=np.linspace(0.,max(40,12*pole),1101)
    z,w=np.polynomial.legendre.leggauss(180)
    total=np.zeros_like(t)
    for onset in onsets:
        age=np.maximum(0,t-onset)[:,None]
        u=age*(z+1)/2
        total+=((age/2)*w*pmt.kernel(u,order,tau)*np.exp(-(age-u)/pole)/pole).sum(axis=1)
    expected=total*20
    actual=pmt.evaluate(onsets,response,t,filter_tau_ns=pole)
    np.testing.assert_allclose(actual,expected,atol=2.e-8,rtol=2.e-8)
    digitization=dict(input_bandwidth_MHz=1000/(2*np.pi*pole),voltage_min_mV=-50,voltage_max_mV=50,full_range_mV=100)
    resolved={'_libraries':[SimpleNamespace(responses=[response],onsets=lambda rec,ch:onsets)],
              'digitizer':{'adc_bits':14},'profile':{'channels':[{'attenuation_dB':0}],'digitization':digitization}}
    out=np.empty(len(t),np.float32)
    assert not sample_channel(binding(),t,np.zeros_like(t),[dict(role=0,record=1,origin=0.)],resolved,0,out)
    np.testing.assert_array_equal(out,quantize(expected,100,14,-50).astype('f4'))


@pytest.mark.skipif(not (ROOT/'.runtime/bin/twinpals-worker.exe').exists(),reason='Geant4 worker is unavailable')
@pytest.mark.parametrize('gap',[0.0,1.0])
def test_opt_in_transport_and_replay(tmp_path,gap):
    from backend.m1_engine import RunManager
    from backend.m1_store import ApplicationStore
    from backend.streams import _Snapshot,_open_shared_read
    store=ApplicationStore(tmp_path/'data',SEED)
    manager=RunManager(ROOT)
    try:
        profile=store.profile
        tube=next(e for e in store.entries if e['id']==profile['detectors'][0]['pmt_id'])
        assert tube['properties']['cathode_reflections'] is True
        tube['properties']['cathode_gap_mm']=gap
        store.database.put(tube,tube['revision'])
        profile['detectors'][1]['pmt_cathode_reflections']=False
        profile['detectors'][0].update(pmt_shape_enabled=True,pmt_shape_factor=2.37/tube['properties']['dynodes'])
        paths=[tmp_path/'prompt.tpstream',tmp_path/'annihilation.tpstream']
        profile['run'].update(events=300,secondary_events=300,auto_seed=False,seed=73125,
                              threads=2,output_paths=[str(p) for p in paths])
        manager.create(store,profile,True)
        deadline=time.monotonic()+110
        while manager.active() and time.monotonic()<deadline:
            time.sleep(.05)
        run=manager.current()
        assert run['status']=='completed',run['message']
        counts=[0,0]
        film_counts=[0,0]
        for path in paths:
            with _open_shared_read(path) as stream:
                snap=_Snapshot(path,stream)
                assert snap.header['analog_response'][0]['order']==pytest.approx(2.37)
                for prefix,ds in snap.events():
                    for ch in (0,1):
                        film_counts[ch]+=ds[ch][13]
                        a=snap.analog[ch]
                        if not len(a):continue
                        if not counts[ch]:
                            response=snap.header['analog_response'][ch]
                            t=np.linspace(a[:,1].min(),a[:,1].max()+pmt.tail_span(response['order'],response['tau_ns']),8000)
                            peak=np.abs(pmt.evaluate(a[:,1],response,t,event=prefix[0])).max()
                            assert peak==pytest.approx(max(-ds[ch][11],ds[ch][12]),rel=1e-3)
                        counts[ch]+=len(a)
        assert min(counts)>0
        assert film_counts[0]>0 and film_counts[1]==0

        from backend.m2_engine import PulseManager
        from backend.m3_engine import LifetimeManager
        digitizer=PulseManager()
        analysis=LifetimeManager()
        try:
            output=tmp_path/'film-and-shape.tppulses'
            acquisition=copy.deepcopy(store.module2)
            acquisition.update(input_paths=[str(p) for p in paths],output_path=str(output),
                               threads=2,auto_seed=False,seed=73125,waveform_pairs=16)
            acquisition['acquisition']['trigger']='either'
            digitizer.create(store,acquisition)
            digitizer.thread.join(60)
            assert digitizer.current()['status']=='completed',digitizer.current().get('message')
            analysis.start(store,{**store.module3,'input_paths':[str(output)],'workers':2})
            analysis.session.thread.join(30)
            assert analysis.session.status=='completed',analysis.session.state()
            assert analysis.session.seen==16
        finally:
            analysis.shutdown()
            digitizer.shutdown()
    finally:
        manager.shutdown()
        store.close()


def test_optics_update_field_ownership_review_and_repeated_starts(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from backend.material_database import MaterialDatabase
    raw=json.loads(SEED.read_text(encoding='utf-8'))
    entries=copy.deepcopy(TUBES[:3])
    for entry in entries:
        for key in ('cathode_reflections','cathode_film_nm','spe_charge_spread_percent'):
            del entry['properties'][key]
        entry['curves']=[c for c in entry['curves'] if c['name'] not in ('cathode_n','cathode_k')]
        entry['provenance']['references']=[r for r in entry['provenance']['references'] if
            not {'cathode_n','cathode_k','cathode_film_nm','spe_charge_spread_percent'}.intersection(r['properties'])]
    prior=tmp_path/'before.json'
    prior.write_text(json.dumps({**raw,'items':entries,'factory_updates':[]}),encoding='utf-8')
    db=MaterialDatabase(tmp_path/'sample.tpdb',prior)
    local=entries[0]
    local['name']='My calibrated tube'
    local['properties'].update(gain=1234567,cathode_reflections=False,cathode_film_nm=25)
    local_n=copy.deepcopy(next(c for c in TUBES[0]['curves'] if c['name']=='cathode_n'))
    local_n['points'][0][1]=2.35
    local['curves'].append(local_n)
    ref=dict(title='My measurement',url='',properties=['cathode_n','cathode_film_nm'])
    local['provenance']['references'].append(ref)
    local=db.put(local,local['revision'])
    modified=entries[1]
    qe=next(c for c in modified['curves'] if c['name']=='quantum_efficiency')
    qe['points'][1][1]*=.9
    modified['properties'].setdefault('datasheet',{})['Photocathode']='Custom cathode'
    modified=db.put(modified,modified['revision'])
    custom=db.put({**entries[2],'id':'personal-tube','name':'Custom'})
    db.delete(entries[2]['id'],entries[2]['revision'])

    # Mirror a database written before migration bookkeeping existed.
    with db.connect() as conn:
        conn.execute('DROP TABLE factory_updates')
        conn.execute('DROP TABLE factory_optics_review')
    with ThreadPoolExecutor(max_workers=2) as pool:
        opens=list(pool.map(lambda _:MaterialDatabase(db.path,SEED),range(2)))
    db=opens[0]
    rows={e['id']:e for e in db.entries()}
    saved=rows[local['id']]
    assert saved['revision']==local['revision']+1
    assert saved['name']==local['name'] and saved['properties']['gain']==1234567
    assert saved['properties']['cathode_film_nm']==25 and saved['properties']['cathode_reflections'] is False
    assert next(c for c in saved['curves'] if c['name']=='cathode_n')==local_n
    for field in ('cathode_n','cathode_film_nm'):
        assert [r for r in saved['provenance']['references'] if field in r['properties']]==[ref]
    assert any('cathode_k' in r['properties'] for r in saved['provenance']['references'])
    assert rows[custom['id']]==custom and entries[2]['id'] not in rows
    pending=rows[modified['id']]
    assert 'cathode_film_nm' not in pending['properties'] and 'spe_charge_spread_percent' in pending['properties']
    before=db.revision
    assert db.factory_optics(local['id'])=={'available':False}
    draft=copy.deepcopy(pending)
    draft['name']='Unsaved edit'
    from types import SimpleNamespace
    from backend.mcp_server.tools import invoke
    store=SimpleNamespace(entries=db.entries(),database=db)
    service=SimpleNamespace(engine=SimpleNamespace(control=SimpleNamespace(store=store)))
    via_mcp=invoke(service,'catalogue_factory_optics',{'id':draft['id']})
    assert via_mcp['entry']['properties']['cathode_reflections'] is False
    review=db.factory_optics(draft['id'],draft)
    assert review['available'] and review['entry']['name']=='Unsaved edit'
    assert review['entry']['properties']['cathode_reflections'] is False
    assert next(c for c in review['entry']['curves'] if c['name']=='quantum_efficiency')==qe
    assert db.revision==before
    saved_review=db.put(review['entry'],draft['revision'])
    assert db.factory_optics(draft['id'])=={'available':False}
    # Deliberate removal after adoption must survive restarts, even with the same factory ID.
    saved_review['curves']=[c for c in saved_review['curves'] if c['name']!='cathode_n']
    saved_review=db.put(saved_review,saved_review['revision'])
    assert saved_review in MaterialDatabase(db.path,SEED).entries()


def test_catalogue_introductions_rollback_and_skipped_releases(tmp_path):
    from backend.material_database import MaterialDatabase
    raw=json.loads(SEED.read_text(encoding='utf-8'))
    current=copy.deepcopy(TUBES[:1])
    future=[{**current[0],'id':i} for i in ('new-tube','next-tube')]
    path=tmp_path/'db.tpdb'
    def seed(items,history):
        p=tmp_path/'seed.json'
        p.write_text(json.dumps({**raw,'items':items,'factory_updates':history}),encoding='utf-8')
        return p
    db=MaterialDatabase(path,seed(current,[]))
    db.delete(current[0]['id'],current[0]['revision'])
    releases=[dict(release=str(i),introduced_ids=[e['id']],additions=[]) for i,e in enumerate(future)]
    latest=seed(current+future,releases)
    with db.connect() as conn:
        conn.execute("CREATE TRIGGER reject_second BEFORE INSERT ON materials WHEN NEW.id='next-tube' BEGIN SELECT RAISE(ABORT,'test interruption'); END")
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError,match='test interruption'):
        MaterialDatabase(path,latest)
    assert db.entries()==[]
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM factory_updates').fetchone()==(0,)
        conn.execute('DROP TRIGGER reject_second')
    db=MaterialDatabase(path,latest)
    assert {e['id'] for e in db.entries()}=={'new-tube','next-tube'}
    db.delete('new-tube',future[0]['revision'])
    assert [e['id'] for e in MaterialDatabase(path,latest).entries()]==['next-tube']
    fresh=MaterialDatabase(tmp_path/'fresh.tpdb',latest)
    fresh.delete('next-tube',future[1]['revision'])
    assert 'next-tube' not in {e['id'] for e in MaterialDatabase(fresh.path,latest).entries()}
