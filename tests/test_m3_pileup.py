# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Check the Na-22 energy topologies independently of peak height, axis direction and display sums."""
import io
import json
import struct
import zlib
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from backend.m2_stream import FRAME, Reader, StreamError
from backend.m3_blocks import library, measured_blocks
from backend.m3_models import Profile, SpectrumDisplay
from backend.m3_signal import CATEGORIES, process, transport_support
from backend.m3_subtypes import subtype_key
from backend.m3_spectra import SpectrumJournal
from backend.m3_measurements import classify, scalar_rows
from backend.provenance import NODE, PREFIX, decode as decode_tree, fixture as birth_tree
from test_module3 import pair, pulse_stream


# Each entry gives detector, energy role, decay ID. The last record in the last case
# is from a different decay but arrives well after this pulse has settled.
CASES = [
    ([(0,0,7),(1,0,7),(0,1,7)], 'pileup_same_decay', 'bc1275'),
    ([(0,1,7),(1,1,7),(1,0,7)], 'pileup_same_decay', 'bc511'),
    ([(0,0,7),(1,0,7),(0,1,7),(1,1,7)], 'pileup_same_decay', 'bc_worst'),
    ([(0,0,7),(1,0,7),(0,1,8)], 'pileup_multiple_decays', None),
    ([(0,0,7),(0,0,7),(1,1,7)], 'pileup_same_decay', None),
    ([(0,0,7),(1,1,8)], 'accidental', None),
    ([(0,0,7),(1,1,7),(0,1,8,65.)], 'correlated', None),
]


def contributions(case, swap):
    pulses=[]
    for channel,role,decay,*late in case:
        ch=channel^swap
        pulses.append(dict(channel=ch,role=role,decay=decay,record=role,component=0,
                           onset_ns=late[0] if late else 20.,origin_ns=0.,source_time_ns=0.,
                           lifetime_ns=0.,height_mV=60.,light_origin='scintillation'))
    return pulses


@pytest.mark.parametrize('swap', [0,1])
@pytest.mark.parametrize('isotope', ['na22','co60'])
def test_subtypes_in_selected_lobes(isotope,swap):
    for case,category,sub in CASES:
        offset,meta,samples,profile,_=pair()
        meta['pulses']=contributions(case,swap)
        ref=process((offset,meta,samples,profile,isotope))['truth']
        selected=[entry[:3] for entry in case if len(entry)==3]
        expected=[[sum((c^swap)==ch and r==role for c,r,_ in selected) for role in (0,1)] for ch in (0,1)]
        assert ref['category']==category
        assert ref['contributions']==expected



def test_subtype_overlays_are_contained_in_the_parent_per_bin_and_stage(tmp_path):
    records=[]
    for i,(case,_,_) in enumerate(CASES):
        offset,meta,data,profile,isotope=pair(180+i,60)
        meta['pulses']=contributions(case,0)
        records.append(process((offset,meta,data,profile,isotope)))
    rows=scalar_rows(records,CATEGORIES,['scintillation','cherenkov','mixed','unknown'])
    profile['channels'][0]['start']['area'].update(enabled=True,slope=0,intercept=1260,below=2,above=2)
    cuts,reasons=classify(rows,profile['channels'])
    journal=SpectrumJournal(tmp_path,{},[500,500])
    try:
        journal.append(rows,cuts,reasons,rows['values'][:,1,4]-rows['values'][:,0,4],profile['channels'])
        view=SpectrumDisplay(individual=True)
        before,after=journal.query(journal.capture(),'AB',view,CATEGORIES)['stages']
        same=['na22_same_1_1_0_1','na22_same_1_0_1_1','na22_same_1_1_1_1','na22_same_0_2_1_0']
        assert before['classes']['pileup_same_decay']==4
        assert [before['subclasses'][k] for k in same]==[1,1,1,1]
        assert before['subclasses']['na22_multi_1_1_0_1']==1
        assert before['subclasses']['tc1']==before['classes']['correlated']==1
        assert before['subclasses']['random_1275_511']==before['classes']['accidental']==1
        for stage in (before,after):
            for h in (stage['lifetime'],*stage['phs']):
                assert sum(v for bins in h['layers'].values() for _,v in bins)==h['counts']
                for parent, keys in [('pileup_same_decay',same),('pileup_multiple_decays',['na22_multi_1_1_0_1'])]:
                    combined={}
                    for key in keys:
                        for i,n in h['sublayers'].get(key,[]):combined[i]=combined.get(i,0)+n
                    assert combined==dict(h['layers'][parent])
    finally:
        journal.file.close()


def frame(tag,payload):
    return FRAME.pack(tag,len(payload),zlib.crc32(payload))+payload


@pytest.mark.skipif(library() is None,reason='Native lifetime reader is unavailable')
def test_parallel_canonical_and_general_metadata_match_the_selected_lobes(pulse_stream):
    read=Reader(pulse_stream)
    try:
        header=read.header
        _,meta,_=next(read.records())
    finally:
        read.close()
    parts=[]
    for role in (0,1):
        electrons=struct.pack('<QII',role,1,1)+struct.pack('<8d',*([1.]*8))+bytes([1,0,1,0])
        payload=struct.pack('<IQI',role,role,len(electrons))+electrons+birth_tree(role,[1,1],role)
        parts.append(frame(b'TRTH',payload))
    _,_,wave,p,_=pair(180,60)
    meta=deepcopy(meta)
    meta['timeline'].update(pulses=[],total=0)
    expected=[]
    for i in range(84):
        case,category,sub=CASES[i%len(CASES)]
        meta.update(id=i,clipped=[False,False],pulses=contributions(case,i%2))
        # Alternate standard Module 2 output and older/extended JSON layouts.
        doc=meta if i%2==0 else {**meta,'extension':True}
        data=json.dumps(doc,sort_keys=i%2==0,separators=(',',':')).encode()
        parts.append(frame(b'WAVE',struct.pack('<I',len(data))+data+wave.astype('<f4').tobytes()))
        counts=[[sum((z[0]^(i%2))==ch and z[1]==role for z in case if len(z)==3) for role in (0,1)] for ch in (0,1)]
        expected.append((CATEGORIES.index(category),counts))
    content=b''.join(parts)
    def read_blocks(content):
        reader=SimpleNamespace(file=io.BytesIO(content),path=Path('test.tppulses.part'),start=0,limit=len(content),
                               samples=wave.shape[1],header=header)
        return np.concatenate([rows for _,rows,_ in measured_blocks(reader,lambda refs:list(refs),lambda:{**p,'workers':4},lambda:None)])
    rows=read_blocks(content)
    assert list(zip(rows['category'],rows['contributions'].tolist()))==expected
    corrupt=bytearray(content)
    corrupt[FRAME.size+16]^=1
    with pytest.raises(StreamError,match='CRC'):read_blocks(corrupt)

    # The canonical numeric reader may skip binary conversion for unmeasured
    # fields, but their JSON grammar, magnitude and positivity are still enforced.
    meta.update(id=0,pulses=contributions(CASES[0][0],False))
    canonical=json.dumps(meta,sort_keys=True,separators=(',',':')).encode()
    height=b'"height_mV":'+str(meta['pulses'][0]['height_mV']).encode()
    assert height in canonical
    def numeric_input(literal):
        data=canonical.replace(height,b'"height_mV":'+literal,1)
        return b''.join(parts[:2])+frame(b'WAVE',struct.pack('<I',len(data))+data+wave.astype('<f4').tobytes())
    for positive in (b'0.00001',b'6E-200',b'1e-310'):
        assert len(read_blocks(numeric_input(positive)))==1
    for invalid in (b'-0.2',b'0e30',b'1e900',b'1.e+1',b'01.2',b'2e'):
        with pytest.raises(StreamError):
            read_blocks(numeric_input(invalid))

def ancestry_frame(role, record, detected, volumes, response, bandwidth):
    """Build shared gamma branches and the PE references observed by each detector."""
    nodes=[];shared_prefix={};refs=[[],[]]
    for ch,photons in enumerate(detected):
        for primary,steps in photons:
            parent=0
            for component,sign in steps:
                key=(primary,parent,component,sign)
                if key not in shared_prefix:
                    item=np.zeros(1,dtype=NODE);item['track']=primary+1;item['primary']=primary
                    item['pdg']=22;item['parent']=parent;item['component']=item['next_component']=component
                    item['energy_before_keV']=500;item['energy_after_keV']=400
                    item['direction_before']=[1.,0.,0.];item['direction_after']=[float(sign),0.,0.]
                    nodes.append(item);shared_prefix[key]=len(nodes)
                parent=shared_prefix[key]
            refs[ch].append(parent)
    a,b=map(len,refs);names=b'["compt"]'
    tree=PREFIX.pack(record,len(nodes),a,b,len(names))+names+b''.join(n.tobytes() for n in nodes)+np.asarray(refs[0]+refs[1],dtype='<u4').tobytes()
    q=[np.ones((n,4)) for n in (a,b)]
    analog=struct.pack('<QII',record,a,b)+b''.join(v.astype('<f8').tobytes() for v in q)+bytes([1,0])*(a+b)
    raw=frame(b'TRTH',struct.pack('<IQI',role,record,len(analog))+analog+tree)
    tr=dict(provenance=decode_tree(tree),photoelectrons=q)
    return raw,[transport_support(tr,ch,response[ch],bandwidth,volumes) for ch in (0,1)]


@pytest.mark.skipif(library() is None,reason='Native lifetime reader is unavailable')
@pytest.mark.parametrize('isotope',['na22','co60'])
def test_witnessed_photon_routes_through_native_and_scalar_readers(pulse_stream,isotope):
    read=Reader(pulse_stream)
    try:header=deepcopy(read.header);_,meta,_=next(read.records())
    finally:read.close()
    header['isotope']=isotope;volumes=[dict(id=i,volume=name) for i,name in enumerate(('ScintA','ScintB','Shield'))]
    for entry in header['inputs']:entry['header']['light_components']=volumes
    response=header['resolved']['analog_response'];bandwidth=header['profile']['digitization']['input_bandwidth_MHz']
    _,_,wave,profile,_=pair();meta=deepcopy(meta);meta['timeline'].update(pulses=[],total=0)
    a=[(0,1)];b=[(1,1)];ab=[(0,-1),(1,1)];ba=[(1,-1),(0,1)]
    prompt=[[(0,[(0,-1)])],[(0,ab)]]
    dd=[[(1,a)],[(2,b)]]
    bs=[[(1,[(0,-1)])],[(1,ab)]]
    ds=[bs[0],bs[1]+[(2,b)]]
    double=[bs[0]+[(2,ba)],bs[1]+[(2,[(1,-1)])]]
    forward=[bs[0],[(1,[(0,1),(1,1)])]]
    same_side=[bs[0],bs[1]+[(2,[(0,1),(1,1)])]]
    external=[[(1,[(2,1),(0,1)])],[(2,b)]]
    # All cases are routed through actual framed bytes, CF and lobe attribution.
    cases=[(dd,((0,0),(0,1),(1,1)),2,1,True),(bs,((0,0),(0,1),(1,1)),2,2,True),
           (ds,((0,0),(0,1),(1,1)),2,3,True),(double,((0,0),(1,0),(0,1),(1,1)),3,4,True),
           (forward,((0,0),(0,1),(1,1)),2,0,True),(same_side,((0,0),(0,1),(1,1)),2,0,True),
           (external,((0,0),(0,1),(1,1)),2,0,True),(dd,((0,0),(1,0),(0,1)),1,0,True),
           (dd,((0,0),(1,1)),4,0,False),(dd,((0,1),(1,0)),5,0,False),
           (bs,((0,0),(1,0)),6,0,False),(bs,((0,1),(1,1)),7,0,False)]
    if isotope=='na22':cases.extend([(dd,((0,1),(1,1)),8,0,False),(external,((0,1),(1,1)),0,0,False)])
    random_from=len(cases)
    for i in (0,1):
        for j in (0,1):cases.append((dd,((0,i),(1,j)),(9 if isotope=='na22' else 8)+2*i+j,0,False))
    parts=[];expected=[];record=0
    for paths,assignment,base,transport,prompt_tag in cases:
        support={}
        for role,detected in enumerate((prompt,paths)):
            raw,support[role]=ancestry_frame(role,record,detected,volumes,response,bandwidth)
            parts.append(raw)
        pulses=contributions([(ch,role,7) for ch,role in assignment],False)
        for z in pulses:
            z['record']=record
            if record>=random_from:z['decay']+=z['channel']
        meta.update(id=record,clipped=[False,False],pulses=pulses)
        doc=json.dumps(meta,separators=(',',':')).encode()
        parts.append(frame(b'WAVE',struct.pack('<I',len(doc))+doc+wave.astype('<f4').tobytes()))
        scalar=deepcopy(meta)
        for z in scalar['pulses']:
            evidence=support[z['role']][z['channel']]
            z.update(evidence,primary_ids=evidence['primaries'],end_ns=z['onset_ns']+evidence['span'])
        truth=process((0,scalar,wave,profile,isotope))['truth']
        category=('accidental' if record>=random_from else 'pileup_same_decay' if len(assignment)>2
                  else 'correlated' if assignment[0][1]!=assignment[1][1]
                  else 'annihilation_pair' if paths in (dd,external) and assignment[0][1]==1 else 'same_primary')
        counts=[[assignment.count((ch,role)) for role in (0,1)] for ch in (0,1)]
        assert truth['category']==category and truth['contributions']==counts
        if category=='same_primary':
            key=subtype_key(isotope,2,sum(counts,[]))
            assert key in (('be1275','shared511') if isotope=='na22' else ('shared1173','shared1332'))
        expected.append((CATEGORIES.index(category),counts));record+=1
    raw=b''.join(parts)
    reader=SimpleNamespace(file=io.BytesIO(raw),path=Path('routes.tppulses.part'),start=0,limit=len(raw),
                           samples=wave.shape[1],header=header)
    rows=np.concatenate([rows for _,rows,_ in measured_blocks(reader,None,lambda:{**profile,'workers':3},lambda:None)])
    assert list(zip(rows['category'],rows['contributions'].tolist()))==expected


def test_saved_subtype_overlays_accept_older_profiles():
    view=SpectrumDisplay.model_validate({'boras_overlays':['bc1275']})
    assert view.model_dump()['subtype_overlays']==['na22_same_1_1_0_1','na22_same_0_1_1_1']
    assert 'boras_overlays' not in view.model_dump()

@pytest.mark.parametrize('isotope,expected',[
    ('na22','na22_multi_257_1_1_0'),('co60','co60_multi_1_257_0_1')])
def test_multiple_decay_multiplicity_survives_journal_and_filters(tmp_path,isotope,expected):
    offset,meta,wave,profile,_=pair()
    case=[(0,1,10)]*257+[(0,0,10),(1,1,20)]
    meta['pulses']=contributions(case,False)
    result=process((offset,meta,wave,profile,isotope))
    assert result['truth']['subtype']==expected
    rows=scalar_rows([result],CATEGORIES,['scintillation','cherenkov','mixed','unknown'])
    cuts,reasons=classify(rows,profile['channels'])
    journal=SpectrumJournal(tmp_path,{'isotope':isotope},[500,500])
    try:
        journal.append(rows,cuts,reasons,rows['values'][:,1,4]-rows['values'][:,0,4],profile['channels'])
        for stage in journal.query(journal.capture(),'merged',SpectrumDisplay(individual=True),CATEGORIES)['stages']:
            assert stage['subclasses']=={expected:1}
            assert stage['classes']['pileup_multiple_decays']==1
    finally:
        journal.file.close()
