# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Direction, time calibration, provenance and replay invariants of the Analysis workbench."""
from copy import deepcopy

import numpy as np
import pytest

from backend.m3_blocks import RESULT
from backend.m3_engine import Acquisition
from backend.m3_measurements import classify
from backend.m3_models import Profile, Settings, SpectrumDisplay
from backend.m3_spectra import SpectrumJournal
from backend.view_settings import LifetimeViews


def fixture_rows():
    # AB good, AB area failure, BA good, BA shape failure, SS, Start/Start,
    # below the stop window, clipped A and a channel without a CF time.
    rows = np.zeros(9, dtype=RESULT)
    rows['values'][:, 0, 0] = [160, 200, 50, 50, 70, 160, 9, 200, 160]
    rows['values'][:, 1, 0] = [50, 50, 210, 210, 50, 210, 50, 50, 50]
    rows['values'][:, :, 2:4] = [2, 8]
    rows['values'][1, 0, 1] = 2000
    rows['values'][3, 1, 2] = np.nan
    rows['values'][:, 0, 4] = 11
    # B's cable is 2.25 ns longer. Corrected Stop minus Start is 1.125 ns
    # for the valid AB and BA rows, and -0.375 ns for Stop/Stop.
    rows['values'][:, 1, 4] = 11 + np.array([3.375, 2.75, 1.125, 0.5, 1.875, 2, 2, 2, 2])
    rows['category'] = [0, 3, 3, 0, 0, 0, 0, 0, 0]
    rows['origin'][1] = 1
    rows['scatter'][1] = 3
    rows['clipped'][7, 0] = 1
    rows['reason'][8, 0] = 3
    p = Profile().model_dump()
    p['channels'][0]['start']['area'].update(enabled=True, slope=0, intercept=0, below=1, above=1)
    p['channels'][1]['start']['shape']['enabled'] = True
    return rows, p


def test_directional_comparison_conserves_measured_pairs_and_corrects_signed_cables(tmp_path):
    rows, p = fixture_rows()
    header = {'profile': {'channels': [{'cable_delay_ns': 0.75}, {'cable_delay_ns': 3.0}]}}
    journal = SpectrumJournal(tmp_path, header, [500, 500])
    view = SpectrumDisplay(low_ns=-1, high_ns=2, bin_ps=250, individual=True, phs_bins=(13, 17))
    classes = ['correlated', 'accidental']
    try:
        post, reasons = classify(rows, p['channels'])
        assert list(post) == [0, -1, 1, -1, 2, -1, -1, -1, -1]
        journal.append(rows, post, reasons, rows['values'][:, 1, 4]-rows['values'][:, 0, 4], p['channels'])
        capture = journal.capture()
        results = {d: journal.query(capture, d, view, classes) for d in ('merged', 'AB', 'BA', 'SS')}
        for d, counts in [('merged', [4, 2]), ('AB', [2, 1]), ('BA', [2, 1]), ('SS', [1, 1])]:
            for stage, expected in zip(results[d]['stages'], counts):
                assert sum(stage['classes'].values()) == expected
                for h in [stage['lifetime'], *stage['phs']]:
                    assert h['counts'] == sum(n for _, n in h['bins']) == expected
                    assert sum(n for bins in h['layers'].values() for _, n in bins) == expected
        assert results['merged']['stages'][1]['lifetime']['bins'] == [[8, 2]]
        assert results['SS']['stages'][1]['lifetime']['bins'] == [[2, 1]]
        assert results['merged']['extent'] == (.5, 1.75)
        restricted = view.model_copy(update=dict(zero_ps=250, low_ns=0., high_ns=1., categories=['accidental'], origin='cherenkov', scatter='shield'))
        before = journal.query(capture, 'merged', restricted, classes)['stages'][0]
        assert before['lifetime']['bins'] == [[1, 1], [3, 2]]
        assert before['lifetime']['layers'] == {'accidental': [[1, 1]]}
        assert before['phs'][0]['counts'] == 4
        assert sum(n for _, n in before['phs'][1]['layers']['accidental']) == 1
    finally:
        journal.file.close()


def test_live_revisions_independent_resets_and_report_snapshot():
    rows, p = fixture_rows()
    acq = Acquisition(p, [], [])
    try:
        acq.thread.join(5)
        view = SpectrumDisplay(bin_ps=75)
        views = {d: view for d in ('merged', 'AB', 'BA', 'SS')}
        def commit():
            direct, reason = classify(rows, acq.profile['channels'])
            acq._record(np.arange(len(rows)), rows, direct, reason, 0)
        commit()
        snap = acq.spectra(views)
        assert [snap['comparisons'][d]['filter_active'] for d in views] == [True, True, True, False]
        assert snap['cable_delays_ns'] == [None, None]
        assert snap['comparisons']['merged']['gated_pairs'] == 4
        acq.reset_plot('spectrum','merged')
        acq.profile = deepcopy(acq.profile)
        acq.profile['channels'][0]['start']['area']['enabled'] = False
        acq.profile['channels'][1]['start']['shape']['enabled'] = False
        commit()
        cap = acq.query({'compact':True, 'comparison_displays':{d:v.model_dump() for d,v in views.items()}})
        assert cap['total_processed'] == 18
        c = cap['comparison']['comparisons']
        assert [s['lifetime']['counts'] for s in c['merged']['stages']] == [4, 4]
        assert [s['lifetime']['counts'] for s in c['AB']['stages']] == [4, 3]
        assert not c['merged']['filter_active'] and c['merged']['gated_pairs'] == 0
        acq.reset_plot('spectrum','AB')
        acq.reset_plot('phs','B')
        c = acq.spectra(views)['comparisons']
        assert c['AB']['stages'][0]['phs'][1]['counts'] == 0
        assert c['merged']['stages'][1]['phs'][1]['counts'] == 4
        acq.reset()
        assert all(s['lifetime']['counts'] == 0 for v in acq.spectra(views)['comparisons'].values() for s in v['stages'])
    finally:
        acq.close()


def test_all_spectra_reset_and_report_keep_the_same_acquisition_boundary():
    rows, profile = fixture_rows()
    acq = Acquisition(profile, [], [])
    try:
        acq.thread.join(5)
        passed, reasons = classify(rows, profile['channels'])
        acq._record(np.arange(len(rows)), rows, passed, reasons, 0)
        views = {d:SpectrumDisplay(origin='cherenkov' if d == 'merged' else 'all',
                                   individual=True) for d in ('AB','BA','SS','merged')}
        def report():
            return acq.query({'compact':True, 'report_all_paths':True,
                              'comparison_displays':{k:v.model_dump() for k,v in views.items()}})
        first = report()
        merged = first['comparison']['comparisons']['merged']['stages'][0]
        complete = first['comparison']['all_paths']['merged']['stages'][0]
        assert set(first['comparison']['all_paths']) == {'merged'}
        assert merged['phs'][0]['counts'] == complete['phs'][0]['counts'] == 4
        assert sum(merged['classes'].values()) == 1
        assert sum(complete['classes'].values()) == 4
        acq.reset_plot('spectrum', 'all')
        cleared = report()
        for field in ('total_processed', 'accepted', 'phs', 'preview', 'revision', 'epoch'):
            assert first[field] == cleared[field]
        assert all(h['counts'] == 0 for d in cleared['comparison']['comparisons'].values()
                   for s in d['stages'] for h in [s['lifetime'], *s['phs']])
        assert all(s['counts'] == 0 for s in cleared['spectra'])
        acq._record(np.arange(len(rows)), rows, passed, reasons, 0)
        assert report()['comparison']['comparisons'] == first['comparison']['comparisons']
    finally:
        acq.close()


def test_direction_settings_validate_and_old_files_keep_their_display():
    base = Settings.model_validate({'display':{'bin_ps':17}}).model_dump()
    assert base['analysis'] == {'direction':'merged','displays':{}}
    assert base['display']['bin_ps'] == 17
    analysis = {'direction':'BA','displays':{'AB':{'bin_ps':12,'phs_bins':[200,700]},'BA':{'bin_ps':36,'log_scale':False}}}
    parsed = Settings(analysis=analysis).analysis
    assert LifetimeViews(analysis=analysis).analysis == parsed
    assert parsed.displays['AB'].phs_bins == (200,700) and parsed.displays['BA'].bin_ps == 36
    assert parsed.displays['AB'].show_total and parsed.displays['AB'].phs_views[0].mode == 'full'
    assert parsed.displays['AB'].time_view is None
    display = SpectrumDisplay(show_total=False, time_view=(-1, 4), phs_views=[{'mode':'custom','limits':[17,47]}, {'mode':'stop'}])
    assert SpectrumDisplay.model_validate_json(display.model_dump_json()) == display
    for limits in ((-6, 1), (0, 51), (4, 4), (4, 0)):
        with pytest.raises(ValueError): SpectrumDisplay(low_ns=-5, high_ns=50, time_view=limits)
    for bad in ({'mode':'custom'}, {'mode':'custom','limits':[4,3]}, {'mode':'custom','limits':[-1,1]}):
        with pytest.raises(ValueError): SpectrumDisplay(phs_views=[bad,{}])
    with pytest.raises(ValueError): Settings(analysis={'displays':{'XX':{}}})


def test_scalar_waveform_fallback_matches_reference_before_and_after_each_gate():
    from backend.m3_signal import process
    from test_module3 import pair
    p = Profile().model_dump()
    p['channels'][0]['start']['area'].update(enabled=True, slope=0, intercept=1260, below=2, above=2)
    p['channels'][0]['stop']['shape'].update(enabled=True, rise=3.2, fall=8, radius_rise=.15, radius_fall=.2)
    a = Acquisition(p, [], [])
    try:
        a.thread.join(5)
        items = []
        for i, (ha, hb) in enumerate([(180,60),(200,60),(60,180),(60,60),(180,180),(200,60),(9,180)]):
            offset, meta, samples, _, isotope = pair(ha,hb)
            meta['clipped'][1] = i == 5
            items.append((offset,meta,samples,p,isotope))
        after = [process(item) for item in items]
        a.commit(after,0)
        raw = deepcopy(p)
        for ch in raw['channels']:
            for role in ('start','stop'):
                for gate in ('area','shape'):ch[role][gate]['enabled'] = False
        before = [process((offset,meta,samples,raw,isotope)) for offset,meta,samples,_,isotope in items]
        views = {d:SpectrumDisplay(individual=True) for d in ('AB','BA','SS','merged')}
        snap = a.spectra(views)
        for d, comparison in snap['comparisons'].items():
            select = ('AB','BA') if d == 'merged' else (d,)
            for stage, source in zip(comparison['stages'], (before,after)):
                good = [r for r in source if r['direction'] in select]
                assert stage['lifetime']['counts'] == len(good)
                assert all(h['counts'] == len(good) for h in stage['phs'])
        assert len([r for r in after if r['direction']]) < len([r for r in before if r['direction']])
    finally:
        a.close()

