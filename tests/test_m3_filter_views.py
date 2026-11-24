# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import threading

import numpy as np
import pytest
from pydantic import ValidationError

from backend.m3_blocks import RESULT
from backend.m3_context import recorded_apparatus, source_context
from backend.m3_models import DensityView, Profile, Settings
from backend.m3_monitor import FeatureJournal, Grid, PlotSpec


@pytest.fixture
def features(tmp_path):
    journal = FeatureJournal(tmp_path, threading.RLock(), [500,500], Profile().model_dump()['channels'])
    rng = np.random.default_rng(5511)
    rows = np.zeros(12000, dtype=RESULT)
    for ch in (0,1):
        v = rows['values'][:,ch]
        v[:,0] = rng.uniform(2,498,len(v))
        v[:,1] = 80 + 3*v[:,0] + rng.normal(0,14,len(v))
        v[::113,1] += 12000
        v[:,2:4] = rng.multivariate_normal([1.4,4.8], [[.02,.06],[.06,.4]], len(v))
        v[::43,3] += 25
        v[::111,2] = np.nan
    journal.append(rows)
    try:
        yield journal,rows
    finally:
        journal.close()


def test_diagonal_rebins_raw_measurements_with_independent_reset_and_shared_wire_cells(features):
    journal,rows=features
    spec=dict(kind='area',channel=0,nx=512,ny=512)
    columns=journal.prepare_many([spec,{**spec,'role':'stop'}],area_views=True)
    captured=journal.capture(columns)
    journal.append(rows[:500])
    full,duplicate,focused,other=journal.render(captured,share_cells=True)
    assert full['total']==focused['total']==len(rows)
    assert duplicate['cells_from']==0 and not duplicate['cells']
    assert other['cells_from']==2 and not other['cells']
    assert full['axes'][:2]==focused['axes'][:2] and focused['axes'][3]<full['axes'][3]/3
    v=rows['values'][:,0]
    expected=np.histogram2d(v[:,1],v[:,0],bins=[512,512],range=[focused['axes'][2:],focused['axes'][:2]])[0].ravel()
    assert dict(focused['cells'])=={i:int(expected[i]) for i in np.flatnonzero(expected)}
    assert focused['visible']==expected.sum()<full['visible']
    journal.reset('area',0)
    after=journal.snapshot(journal.prepare_many([{**spec,'axes':focused['axes']},{**spec,'channel':1}]))
    assert [p['total'] for p in after]==[0,len(rows)+500]


def test_dense_512_by_512_and_explicit_legacy_resolution():
    settings=Settings.model_validate({'monitor':{'plots':{'area-A-start':{'nx':64,'ny':87}}}})
    assert (DensityView().nx,DensityView().ny)==(256,256)
    assert PlotSpec(kind='phs',channel=0).nx==512
    assert (settings.monitor.plots['area-A-start'].nx,settings.monitor.plots['area-A-start'].ny)==(64,87)
    assert settings.monitor.phs_bins==(512,512)
    for axis in ('nx','ny'):
        with pytest.raises(ValidationError):PlotSpec(kind='area',channel=0,**{axis:513})
    g=Grid(PlotSpec(kind='shape',channel=0,nx=512,ny=512,axes=(0,512,0,512)),500)
    y,x=np.indices((512,512));data=np.zeros((x.size,4));data[:,2]=x.ravel()+.5;data[:,3]=y.ravel()+.5
    g.add(data)
    view=g.snapshot('start',1)
    assert view['visible']==len(view['cells'])==262144 and view['max_cell']==1


def test_measured_coverage_spans_journal_blocks_and_accepts_tied_boundary(features):
    journal,rows=features
    for _ in range(7):journal.append(rows)
    options={'coverage':98.8}
    cut={'low':0,'high':500}
    ellipse=journal.fit(0,'shape',cut,options)
    pts=rows['values'][:,0,2:4]
    x,y=(pts[np.isfinite(pts).all(axis=1)]-[ellipse['rise'],ellipse['fall']]).T
    angle=np.radians(ellipse['angle_deg'])
    d=((x*np.cos(angle)+y*np.sin(angle))/ellipse['radius_rise'])**2+((y*np.cos(angle)-x*np.sin(angle))/ellipse['radius_fall'])**2
    assert np.count_nonzero(d<=1)==int(np.ceil(len(d)*.988))


def test_fit_percentiles_and_measured_coverage_use_full_window_history(features):
    journal,rows=features
    cut={'low':100,'high':400}
    hits=rows['values'][:,0];hits=hits[(hits[:,0]>=100)&(hits[:,0]<400)]
    opts={'low':10,'high':85}
    band=journal.fit(0,'area',cut,opts)
    slope,intercept=np.polyfit(hits[:,0],hits[:,1],1)
    residual=hits[:,1]-slope*hits[:,0]-intercept
    np.testing.assert_allclose([band['slope'],band['intercept']],[slope,intercept])
    q=np.percentile(residual,[10,85])
    np.testing.assert_allclose([band['below'],band['above']],np.maximum(0,[-q[0],q[1]]),atol=np.ptp(residual)/4096+.01)
    detail=journal.fit(0,'shape',cut,{'low':20,'high':80,'coverage':80,'fence':1},include_counts=True)
    assert detail['inside']==np.ceil(detail['total']*.8) and detail['first']==1
    a=detail['gate']
    b=journal.fit(0,'shape',cut,{'low':20,'high':80,'coverage':99,'fence':1})
    assert [a[k] for k in ('rise','fall','angle_deg')]==[b[k] for k in ('rise','fall','angle_deg')]
    pts=hits[np.isfinite(hits[:,2:4]).all(axis=1),2:4]
    for ellipse,coverage in ((a,80),(b,99),(journal.fit(0,'shape',cut,{'coverage':100}),100)):
        x,y=(pts-[ellipse['rise'],ellipse['fall']]).T
        theta=np.radians(ellipse['angle_deg'])
        d=((x*np.cos(theta)+y*np.sin(theta))/ellipse['radius_rise'])**2+((y*np.cos(theta)-x*np.sin(theta))/ellipse['radius_fall'])**2
        assert np.count_nonzero(d<=1)==np.ceil(len(pts)*coverage/100)
    untrimmed=journal.fit(0,'shape',cut,{'low':0,'high':100,'fence':0})
    assert untrimmed['fall']>a['fall']+.35
    for invalid in ({'low':85,'high':10},{'coverage':100.1},{'coverage':0},{'fence':-1}):
        with pytest.raises(ValidationError):journal.fit(0,'shape',cut,invalid)
    journal.reset('shape',0)
    with pytest.raises(ValueError,match='20 valid pulses'):journal.fit(0,'shape',cut)


def test_archived_geometry_is_per_transport_input_even_without_source_files():
    def header(length):
        return dict(role='na22_prompt',source='na22',material_names={'custom':'Archived crystal'},
                    profile={'detectors':[dict(id='B',scintillator_id='custom',shape='cylinder',
                                              dimensions={'diameter_mm':18,'length_mm':length},pmt_id='p')]},
                    pmt_snapshot=[dict(id='p',properties={'window_material':{'name':'Recorded glass'},'window_thickness_mm':1.5})])
    h={'inputs':[{'path':'unavailable1.tpstream','header':header(22)},{'path':'unavailable2.tpstream','header':header(33)}]}
    a,b=source_context(['archived.tppulses'],[h])['streams'][0]['inputs']
    assert a['apparatus']['detectors']['B']['Crystal']=='Archived crystal'
    assert 'Recorded glass' in b['apparatus']['detectors']['B']['PMT window']
    assert '22 mm long' in a['apparatus']['detectors']['B']['Geometry'] and '33 mm long' in b['apparatus']['detectors']['B']['Geometry']
    for transport,length in ((a,22),(b,33)):
        instrument=transport['apparatus']['instrument']['B']
        assert instrument['Shape']=='cylinder' and instrument['Cross section']=='Ø 18 mm'
        assert instrument['Length']==f'{length} mm' and 'Front face' not in instrument
    assert 'A' not in a['apparatus']['detectors']
    assert recorded_apparatus({})=={'source':{},'detectors':{}}
