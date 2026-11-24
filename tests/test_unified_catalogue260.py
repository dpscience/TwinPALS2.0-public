# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""One catalogue, nested PMT optics, geometry ownership and pulse projection."""
import copy
import json
from pathlib import Path
import pytest
from backend.m1_store import ApplicationStore
from backend.m1_models import Profile
from backend.m1_resolve import resolve_profile
from backend.material_database import validated_entry
from backend.material_readiness import missing_properties
from backend.photomultiplier import component_entry

ROOT=Path(__file__).resolve().parents[1]
SEED=ROOT/'seed/factory_catalogue.json'
ENTRIES=json.loads(SEED.read_text(encoding='utf-8'))['items']
PMTS=[e for e in ENTRIES if e['category']=='pmt']

@pytest.mark.parametrize('entry',PMTS,ids=lambda e:e['id'])
def test_complete_pmt_has_sourced_window_qe_geometry_and_timing(entry):
    assert not missing_properties(entry)
    p=entry['properties']; assert 'tube_wall_mm' not in p
    assert p['cathode_gap_mm']==0
    square=p.get('tube_shape')=='square'
    envelope='tube_width_mm' if square else 'tube_diameter_mm'
    assert p[envelope]>p['photocathode_width_mm' if square else 'photocathode_diameter_mm']
    assert {c['name'] for c in p['window_material']['curves']}=={'refractive_index','absorption_length'}
    assert entry['curves'][0]['name']=='quantum_efficiency'
    cited={k for r in entry['provenance']['references'] for k in r['properties']}
    for key in ['window_thickness_mm',envelope,'tube_length_mm','cathode_gap_mm','tts_ns','transit_ns','quantum_efficiency']: assert key in cited
    assumptions=[r['comment'] for r in entry['provenance']['references'] if 'window_thickness_mm' in r['properties']]
    assert any('assum' in s.lower() for s in assumptions)
    from backend.analog_pmt import operating_point, FWHM_SIGMA
    response=operating_point(entry)
    assert response['transit_ns']==p['transit_ns']
    assert response['tts_sigma_ns']==pytest.approx(p['tts_ns']/(FWHM_SIGMA if p['tts_convention']=='fwhm' else 1))
    with pytest.raises(ValueError,match='belongs to Module 1'):component_entry(entry)

def test_window_thickness_is_owned_by_database_and_used_by_transport(tmp_path):
    store=ApplicationStore(tmp_path,SEED)
    try:
        assert store.components.path==store.database.path
        assert [p.name for p in tmp_path.glob('*.tpdb')]==['catalogue.tpdb']
        profile=store.freeze(store.profile)
        assert all(set(d).isdisjoint({'window_thickness_mm','window_id','photosensor_id','photocathode_shape'}) for d in profile['detectors'])
        pmt=next(e for e in store.entries if e['id']==profile['detectors'][0]['pmt_id'])
        pmt['properties']['window_thickness_mm']=3.75
        store.database.put(pmt,pmt['revision'])
        resolved,_=resolve_profile(profile,store.entries)
        assert all(d['window']['thickness_mm']==3.75 for d in resolved['detectors'])
        bad=copy.deepcopy(profile);bad['detectors'][0]['window_thickness_mm']=9
        with pytest.raises(ValueError): Profile.model_validate(bad)
    finally:store.close()

@pytest.mark.parametrize('patch',[
    {'cathode_gap_mm':-1}, {'window_thickness_mm':0}, {'tube_length_mm':2},
    {'tube_diameter_mm':20}, {'window_shape':'rect','window_width_mm':60,'window_height_mm':60},
    {'tts_ns':-1}, {'transit_ns':float('nan')},
])
def test_invalid_pmt_geometry_or_timing_rejected(patch):
    e=copy.deepcopy(PMTS[0]);e['properties'].update(patch)
    with pytest.raises(ValueError):validated_entry(e)

def test_positive_gap_and_rectangular_apertures_supported():
    e=copy.deepcopy(PMTS[0]);e['properties'].update(cathode_gap_mm=3,window_shape='rect',window_width_mm=32,window_height_mm=22,photocathode_shape='rect',photocathode_width_mm=28,photocathode_height_mm=18)
    assert validated_entry(e)['properties']['cathode_gap_mm']==3

@pytest.mark.parametrize('key',['window_material','window_thickness_mm','tts_ns','transit_ns','tube_length_mm'])
def test_incomplete_pmt_is_saved_as_draft_but_not_selectable(key):
    e=copy.deepcopy(PMTS[0]);e['properties'].pop(key)
    validated_entry(e);assert missing_properties(e)
    with pytest.raises(ValueError,match='belongs to Module 1'):component_entry(e)
    profile=Profile().model_dump(mode='json')
    profile['detectors'][0]['pmt_id']=e['id']
    with pytest.raises(ValueError,match='incomplete'):resolve_profile(profile,[x for x in ENTRIES if x['id']!=e['id']]+[e])
