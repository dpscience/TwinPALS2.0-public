# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import json
from pathlib import Path
import struct
import zlib
import numpy as np

import pytest

from backend.streams import (DETECTOR, FRAME, MAGIC, PREFIX, StreamError, AnalysisCancelled, _Snapshot, _open_shared_read,
                             analyze, inspect_stream, validate_complete)

def frame(tag, payload):
    return FRAME.pack(tag,len(payload),zlib.crc32(payload))+payload

def event(index, a=(80.,10,2.), b=(0.,0,0.), mask=1, minimum_energy_keV=0):
    # Tuple detector values: deposited energy, detected photon count, mean time.
    directions={1:(1.,0.,0.,0.,0.,0.,0.,0.,0.),3:(1.,0.,0.,0.,1.,0.,0.,0.,0.),6:(0.,0.,0.,1.,0.,0.,-1.,0.,0.)}[mask]
    prefix=PREFIX.pack(index,mask,0,0,0,*directions,0,0,0)
    responses=[]
    for d,(energy,count,mean) in enumerate((a,b)):
        interaction=energy>0
        flags=(17 if count else 0)|(2 if interaction else 0)|(4 if energy>=minimum_energy_keV else 0)
        xyz=(12.,0.,0.) if d==0 else (-13.,0.,0.)
        responses.append(DETECTOR.pack(flags,count,energy,mean,*(xyz if interaction else (0,0,0)),.1 if interaction else 0,4. if count else 0,3,0,-float(count),0.))
    return frame(b'EVNT',prefix+b''.join(responses))

def record(row):
    """Pair a summary fixture with explicit accepted PE times and XY positions."""
    prefix=PREFIX.unpack_from(row,12);ds=[DETECTOR.unpack_from(row,12+PREFIX.size+d*DETECTOR.size) for d in range(2)]
    arrays=[]
    for d in ds:
        a=np.zeros((d[1],4),dtype='<f8');a[:,0]=d[3];a[:,1]=d[3]+10;arrays.append(a)
    from backend.provenance import fixture as provenance_fixture
    provenance=frame(b'PROV',provenance_fixture(prefix[0],[len(a) for a in arrays]))
    return frame(b'APLS',struct.pack('<QII',prefix[0],len(arrays[0]),len(arrays[1]))+b''.join(a.tobytes() for a in arrays)+bytes([1,0])*sum(len(a) for a in arrays))+provenance+row


def fixture_header(role='na22_prompt'):
    response=dict(model='erlang-fixed-charge-v1',order=4,tau_ns=1.,charge_C=1e-13,load_ohm=50.,voltage_scale_mV=5.,polarity='negative')
    return {'format':'twinpals-stream','version':6,'light_components':[dict(id=0,volume='ScintA',label='Crystal A',material='Plastic')],'role':role,'profile':{'name':'fixture','detectors':[{'pmt_id':'fixture-pmt'}]*2},
            'physics':{'include_cherenkov':True,'minimum_energy_keV':0},
            'analog_response':[response.copy(),response.copy()],
            'pmt_snapshot':[{'id':'fixture-pmt','properties':{'photocathode_shape':'circle','photocathode_diameter_mm':40.}}],
            'resolved':{'detectors':[{'front_mm':[10,0,0],'axis':[1,0,0]},{'front_mm':[-10,0,0],'axis':[-1,0,0]}]}}


def analog_record(row):
    packed=record(row)
    return packed[12:12+struct.unpack_from('<I',packed,4)[0]]


def write(path, rows=None, role='na22_prompt', done=True, suffix=b'', header=None):
    header=header or fixture_header(role)
    data=json.dumps(header).encode()
    rows=rows if rows is not None else [event(0),event(1,(0,0,0),(60,4,3)),event(2,(10,1,4),(20,2,5)),event(3,(0,0,0),(0,0,0))]
    path.write_bytes(MAGIC+struct.pack('<I',len(data))+data+b''.join(record(row) for row in rows)+(frame(b'DONE',json.dumps({'status':'completed','events':len(rows)}).encode()) if done else b'')+suffix)
    return path

def test_both_detectors_and_missing_values(tmp_path):
    path=write(tmp_path/'run.tpstream')
    info=inspect_stream(path)
    assert info['completion']=={'status':'completed','events':4,'verified':False}
    assert validate_complete(path)['verified']
    result=analyze([path],{'metric':'mean_arrival','bins':4})
    assert result['total_events']==4 and result['complete']
    a,b=result['series']
    assert (a['events'],a['valid'],a['missing'])==(4,2,2)
    assert (b['events'],b['valid'],b['missing'])==(4,2,2)
    assert a['edges']==b['edges'] and sum(a['counts'])==sum(b['counts'])==2
    energy=analyze([path],{'metric':'energy','category':'both'})
    assert all(s['events']==1 and s['valid']==1 for s in energy['series'])
    assert len(energy['markers'])==2

def test_depth_and_directions(tmp_path):
    path=write(tmp_path/'pair.tpstream',[event(0,mask=6)],role='na22_annihilation')
    depth=analyze([path],{'metric':'depth'})
    assert depth['positions'][0]['depth']==2
    directions=analyze([path],{'metric':'polar_angle','bins':2})
    for series in directions['series']:
        assert series['events']==1 and series['valid']==2
        assert series['counts']==[1,1]
    assert 'two primary directions' in ' '.join(directions['warnings'])

def test_range_and_category_nohit_denominator(tmp_path):
    path=write(tmp_path/'range.tpstream')
    result=analyze([path],{'metric':'energy','detector':'A','range':[5,50],'bins':3})
    series=result['series'][0]
    assert series['events']==series['valid']==4
    assert series['underflow']==2 and series['overflow']==1 and sum(series['counts'])==1
    nohit=analyze([path],{'metric':'photon_count','category':'none'})
    assert all(s['events']==1 and sum(s['counts'])==1 for s in nohit['series'])

def test_partial_recovers_only_complete_crc_frames(tmp_path):
    path=write(tmp_path/'partial.tpstream.part',[event(0)],done=False,suffix=event(1)[:111])
    result=analyze([path],{'metric':'energy'})
    assert result['total_events']==1 and not result['complete']
    assert result['streams'][0]['completion']['truncated_tail']
    with pytest.raises(StreamError,match='not complete'): validate_complete(path)
    complete=tmp_path/'bad.tpstream'; complete.write_bytes(path.read_bytes())
    with pytest.raises(StreamError,match='DONE'): analyze([complete],{})

def test_corruption_never_silently_skipped(tmp_path):
    path=write(tmp_path/'corrupt.tpstream')
    data=bytearray(path.read_bytes()); n=struct.unpack_from('<I',data,8)[0]; data[12+n+12+20]^=1; path.write_bytes(data)
    with pytest.raises(StreamError,match='CRC'): analyze([path],{})
    wrong_order=write(tmp_path/'order.tpstream',[event(1)])
    with pytest.raises(StreamError,match='ascending'): analyze([wrong_order],{})
    nan=bytearray(event(0)); struct.pack_into('<d',nan,12+132+12,float('nan')); nan[8:12]=struct.pack('<I',zlib.crc32(nan[12:]))
    wrong=write(tmp_path/'nan.tpstream',[bytes(nan)])
    with pytest.raises(StreamError,match='nonfinite'): analyze([wrong],{})

def test_live_growth_uses_same_snapshot_for_both_passes(tmp_path,monkeypatch):
    path=write(tmp_path/'live.tpstream.part',[event(0)],done=False)
    original=_Snapshot.events
    calls=0
    def wrapped(self):
        nonlocal calls
        yield from original(self)
        calls+=1
        if calls==1:
            with path.open('ab') as f: f.write(record(event(1)))
    monkeypatch.setattr(_Snapshot,'events',wrapped)
    result=analyze([path],{'metric':'energy'})
    assert result['total_events']==1
    assert all(s['events']==sum(s['counts'])==1 for s in result['series'])
    assert calls==2

def test_co_projection_and_duplicate_file_protection(tmp_path):
    one=write(tmp_path/'1173.tpstream',[event(0,a=(60,2,1),mask=3)],role='co60_1173')
    two=write(tmp_path/'1332.tpstream',[event(0,b=(100,5,2),mask=3)],role='co60_1332')
    result=analyze([one,two],{'metric':'energy','primary':'co60_1332'})
    assert len(result['series'])==2 and result['total_events']==1
    assert all(s['primary']=='co60_1332' for s in result['series'])
    with pytest.raises(StreamError,match='more than once'): analyze([one,one],{})

def test_archived_native_fixture_requires_new_physics_settings():
    path=Path(__file__).resolve().parents[1]/'validation/2.7.0/bc_511.tpstream'
    if not path.exists(): pytest.skip('Run scripts/verify_analog270.py to create a current Geant4 fixture')
    with pytest.raises(StreamError,match='current TwinPALS analog stream'):
        analyze([path],{'metric':'depth'})

def test_analysis_can_be_cancelled(tmp_path):
    import threading
    path=write(tmp_path/'cancel.tpstream')
    stop=threading.Event();stop.set()
    with pytest.raises(AnalysisCancelled): analyze([path],{},cancel=stop)
    calls=0
    def cancelled():
        nonlocal calls
        calls+=1
        return calls>=4
    with pytest.raises(AnalysisCancelled): analyze([path],{},cancel=cancelled)

def test_open_snapshot_allows_native_final_rename(tmp_path):
    path=write(tmp_path/'active.tpstream.part')
    with _open_shared_read(path) as file:
        snapshot=_Snapshot(path,file)
        path.replace(tmp_path/'finished.tpstream')
        assert len(list(snapshot.events()))==4
        assert snapshot.completion['status']=='completed'

def rewrite_header(path, update):
    data=path.read_bytes(); size=struct.unpack_from('<I',data,8)[0]
    header=json.loads(data[12:12+size]); header.update(update)
    encoded=json.dumps(header).encode()
    path.write_bytes(MAGIC+struct.pack('<I',len(encoded))+encoded+data[12+size:])

def settings_hash(profile):
    import hashlib
    return hashlib.sha256(json.dumps(profile,ensure_ascii=False,allow_nan=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def test_stream_identity_rejects_copies_and_cross_run_aggregation(tmp_path):
    one=write(tmp_path/'one.tpstream')
    two=write(tmp_path/'two.tpstream')
    rewrite_header(one,{'stream_id':'one','run_id':'run1'})
    rewrite_header(two,{'stream_id':'one','run_id':'run1'})
    with pytest.raises(StreamError,match='same stream_id'): analyze([one,two],{})
    rewrite_header(two,{'stream_id':'two','run_id':'run2'})
    with pytest.raises(StreamError,match='different simulation runs'): analyze([one,two],{})
    rewrite_header(two,{'stream_id':'two','run_id':'run1'})
    assert analyze([one,two],{})['total_events']==8

def test_embedded_profile_hash_and_settings_identity(tmp_path):
    one=write(tmp_path/'one.tpstream'); two=write(tmp_path/'two.tpstream')
    profile={'name':'München','value':1.0}
    rewrite_header(one,{'profile':profile,'settings_sha256':settings_hash(profile)})
    assert inspect_stream(one)['header']['profile']==profile
    other={'name':'another'}
    rewrite_header(two,{'profile':other,'settings_sha256':settings_hash(other)})
    with pytest.raises(StreamError,match='different setup profiles'): analyze([one,two],{})
    rewrite_header(one,{'profile':{'name':'changed'}})
    with pytest.raises(StreamError,match='does not match'): inspect_stream(one)

def test_unknown_role_rejected_and_co_single_or_partial_pair_allowed(tmp_path):
    bad=write(tmp_path/'bad.tpstream',role='unrecognized')
    with pytest.raises(StreamError,match='Unsupported stream primary role'): analyze([bad],{'metric':'polar_angle'})
    one=write(tmp_path/'one.tpstream',[event(0,mask=3)],role='co60_1173')
    two=write(tmp_path/'two.tpstream.part',[event(0,mask=3),event(1,mask=3)],role='co60_1332',done=False)
    rewrite_header(one,{'stream_id':'one','run_id':'same'})
    rewrite_header(two,{'stream_id':'two','run_id':'same'})
    assert analyze([one],{})['complete']
    pair=analyze([one,two],{})
    assert pair['total_events']==3 and not pair['complete']


@pytest.mark.parametrize('damage, message',[
    ('count','count/length'),('id','ascending'),('nan','Invalid photoelectron'),
    ('mean','count/mean'),('missing','Unpaired transport'),('unpaired','no transport ancestry')])
def test_analog_event_pair_corruption_is_rejected(tmp_path,damage,message):
    path=write(tmp_path/'bad.tpstream',[event(0)])
    original=path.read_bytes(); start=12+struct.unpack_from('<I',original,8)[0]
    tag,length,_=FRAME.unpack_from(original,start); assert tag==b'APLS'
    payload=bytearray(original[start+FRAME.size:start+FRAME.size+length])
    rest=original[start+FRAME.size+length:]
    if damage=='count': struct.pack_into('<I',payload,8,999)
    elif damage=='id': struct.pack_into('<Q',payload,0,3)
    elif damage=='nan': struct.pack_into('<d',payload,16+16,float('nan'))
    elif damage=='mean': struct.pack_into('<d',payload,16,7.)
    if damage=='missing': changed=rest
    elif damage=='unpaired': changed=frame(b'APLS',payload)+rest[FRAME.size+struct.unpack_from('<I',rest,4)[0]:]
    else: changed=frame(b'APLS',payload)+rest
    path.write_bytes(original[:start]+changed)
    with pytest.raises(StreamError,match=message):validate_complete(path)


@pytest.mark.parametrize('key,value,message',[
    ('load_ohm',25.,'charge and voltage'),('tau_ns',0.,'parameter'),
    ('order',3.5,'model'),('polarity','other','model')])
def test_inconsistent_analog_snapshot_rejected_before_reading_events(tmp_path,key,value,message):
    header=fixture_header(); header['analog_response'][0][key]=value
    path=write(tmp_path/'wrong-response.tpstream',header=header)
    with pytest.raises(StreamError,match=message):inspect_stream(path)
