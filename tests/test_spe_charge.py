# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import copy
import json
from pathlib import Path
from threading import Event

import numpy as np
import pytest

from backend import analog_pmt as pmt
from backend.material_database import MaterialDatabase
from backend.persistence import PulseCloud, accumulate, axes
from backend.streams import StreamError, validate_analog_responses

SEED = Path(__file__).resolve().parents[1] / 'seed/factory_catalogue.json'
FIELD = 'spe_charge_spread_percent'


def tube(spread):
    entry = next(e for e in json.loads(SEED.read_text(encoding='utf-8'))['items']
                 if e['id'] == 'hamamatsu-r11265u-200')
    if spread is None:
        entry['properties'].pop(FIELD)
    else:
        entry['properties'][FIELD] = spread
    return pmt.operating_point(entry, 900)


@pytest.mark.parametrize('percent', [1., 30., 36., 45., 50., 80., 99.])
def test_charge_law_matches_positive_mean_and_cv(percent, monkeypatch):
    response = tube(percent)
    onsets = np.arange(50000.)
    weights = pmt.spe_weights(onsets, response, 728)
    assert weights.min() > 0
    assert weights.mean() == pytest.approx(1., abs=.014)
    assert weights.std()/weights.mean() == pytest.approx(percent/100., abs=.015)
    with monkeypatch.context() as patch:
        patch.setattr(pmt, 'native_library', lambda: None)
        scalar = pmt.spe_weights(onsets[:128], response, 728)
    np.testing.assert_allclose(scalar, weights[:128], rtol=1e-12)


def test_record_replay_and_optical_contributions(monkeypatch):
    old = tube(None)
    assert old == tube(0)
    r = tube(50)
    for key in ('gain','tau_ns','order','tts_sigma_ns','onset_delay_ns','voltage_scale_mV'):
        assert old[key] == r[key]
    a, b = pmt.stream_responses([r, r], 1234, 0)
    other, _ = pmt.stream_responses([r, r], 1234, 1)
    t = np.array([2.2, 1.8, 2.4, 1.8, 1.9])
    x = np.linspace(.5, 25, 1201)
    pick = np.array([True, False, True, True, False])
    weights = pmt.spe_weights(t, a, 3)
    for response, event in ((b, 3), (other, 3), (a, 4)):
        assert not np.array_equal(weights, pmt.spe_weights(t, response, event))
    total = pmt.evaluate(t, a, x, current=True, event=3)
    parts = [pmt.evaluate(t[k], a, x, current=True, weights=weights[k]) for k in (pick, ~pick)]
    np.testing.assert_allclose(sum(parts), total, atol=1.e-12)
    np.testing.assert_allclose(pmt.evaluate(np.sort(t), a, x, current=True, event=3), total, atol=1.e-12)
    assert np.trapezoid(-total, x) == pytest.approx(weights.sum()*a['charge_C']*1e12, rel=1.e-9)
    with monkeypatch.context() as patch:
        patch.setattr(pmt, 'native_library', lambda: None)
        np.testing.assert_allclose(pmt.evaluate(t, a, x, current=True, event=3), total, atol=1.e-12)
    validate_analog_responses([a, b])
    for invalid in (dict(charge_seed=-1), dict(charge_scale=-1), {FIELD:100}):
        with pytest.raises(StreamError):
            validate_analog_responses([{**a, **invalid}, b])


def test_weighted_native_adc_matches_reference_grid():
    from backend.native_digitizer import binding, sample_channel
    from backend.m2_physics import event_voltage, quantize
    from types import SimpleNamespace

    fn = binding()
    if fn is None:
        pytest.skip('Native digitizer unavailable')
    response = tube(50)
    onsets = np.random.default_rng(73125).uniform(2, 5, 70)
    library = SimpleNamespace(responses=[response, response], onsets=lambda record, ch: onsets)
    resolved = {'_libraries':[library], 'digitizer':{'adc_bits':14},
                'profile':{'channels':[{'attenuation_dB':1}],
                           'digitization':dict(input_bandwidth_MHz=700, voltage_min_mV=-500,
                                               voltage_max_mV=500, full_range_mV=1000)}}
    t = np.linspace(0., 40., 1024)
    noise = np.random.default_rng(132).normal(0,.15,len(t))
    pulses = [dict(role=0, record=rec, channel=0, origin=origin) for rec,origin in ((731,0.),(209,2.))]
    reference = quantize(sum(event_voltage(t,p,resolved) for p in pulses)+noise, 1000,14,-500)
    output = np.empty(len(t), np.float32)
    clipped = sample_channel(fn,t,noise,pulses,resolved,0,output)
    np.testing.assert_array_equal(output, reference.astype('f4'))
    assert not clipped


def test_charge_normalized_persistence_batch_and_incremental_cache():
    cloud = PulseCloud()
    try:
        r = tube(50)
        for event in range(1,15):
            cloud.append(np.random.default_rng(event).uniform(1.,3.,9*event), event)
        axis = axes([(cloud, r)], 60)
        for response in (r,{**r,'charge_seed':55},tube(None)):
            grids,totals = accumulate(cloud,response,60,axis,14,Event(),False)
            cloud.cache.clear()
            accumulate(cloud,response,60,axis,9,Event(),True)
            other,counts = accumulate(cloud,response,60,axis,14,Event(),True)
            np.testing.assert_array_equal(grids, other)
            np.testing.assert_array_equal(totals,counts)
    finally:
        cloud.finalizer()


def test_factory_charge_backfill_preserves_user_entries(tmp_path):
    raw = json.loads(SEED.read_text(encoding='utf-8'))
    tubes = [e for e in raw['items'] if e['category']=='pmt']
    assert len(tubes) == 16
    for e in tubes:
        assert 0 < e['properties'][FIELD] < 100
        refs = [r for r in e['provenance']['references'] if FIELD in r['properties']]
        assert refs and all(r['url'] and r['comment'] for r in refs)
    old = copy.deepcopy(tubes[:4])
    for e in old:
        e['properties'].pop(FIELD)
        e['provenance']['references'] = [r for r in e['provenance']['references'] if FIELD not in r['properties']]
    prior = tmp_path/'old.json'
    prior.write_text(json.dumps({**raw,'items':old,'factory_updates':[]}),encoding='utf-8')
    path = tmp_path/'catalogue.tpdb'
    db = MaterialDatabase(path, prior)
    edited = db.put(old[1], old[1]['revision'])
    kept = {**old[2],'properties':{**old[2]['properties'], FIELD:0}}
    kept = db.put(kept, kept['revision'])
    db.delete(old[3]['id'], old[3]['revision'])
    before = db.revision
    db = MaterialDatabase(path, SEED)
    rows = {e['id']:e for e in db.entries()}
    assert len(rows)==3
    assert rows[edited['id']]['properties'][FIELD]==tubes[1]['properties'][FIELD]
    assert rows[kept['id']]==kept
    assert rows[old[0]['id']]['properties'][FIELD]==tubes[0]['properties'][FIELD]
    assert db.revision==before+1
    assert MaterialDatabase(path,SEED).revision==db.revision
