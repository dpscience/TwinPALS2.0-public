# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Stopped and actively written inputs retain their CRC and truth guarantees."""
import json
import hashlib
import os
import struct
import zlib
from pathlib import Path
import pytest
from backend.m2_stream import Reader, FRAME
from backend.m1_store import encode
from backend.m3_engine import LifetimeManager
from backend.m3_models import Profile
from test_module3 import pulse_stream


def run(path,tmp_path):
    class Store:
        def resolve_path(self,v):return Path(v)
    manager=LifetimeManager()
    manager.start(Store(),Profile(workers=1,input_paths=[str(path)]).model_dump())
    manager.session.thread.join(40)
    return manager


def test_existing_single_class_recording_preserves_its_original_header(pulse_stream,tmp_path):
    reader=Reader(pulse_stream)
    try:
        first,record,_=next(reader.records())
        header=reader.header
        header['profile']['output_mode']='classes'
        header['resolved']['profile']['output_mode']='classes'
        header['settings_sha256']=hashlib.sha256(encode(header['profile']).encode()).hexdigest()
        header['class_filter']=record['class']
        fields=encode(header).encode()
        original=pulse_stream.read_bytes()
        _,size,_=FRAME.unpack_from(original,first)
        path=tmp_path/'archived-class.tppulses.part'
        path.write_bytes(original[:8]+struct.pack('<I',len(fields))+fields+original[reader.start:first+FRAME.size+size])
    finally:reader.close()
    manager=run(path,tmp_path)
    try:
        state=manager.current()
        assert state['status']=='completed' and state['total_processed']==1
        assert manager.session.headers[0]['profile']['output_mode']=='classes'
    finally:manager.shutdown()


@pytest.mark.parametrize('ending',['cancelled','open','torn','corrupt'])
def test_m3_reads_valid_prefix_and_rejects_corruption(pulse_stream,tmp_path,ending):
    reader=Reader(pulse_stream)
    try:
        offsets=[at for at,_,_ in reader.records()]
        original=pulse_stream.read_bytes()
    finally:reader.close()
    assert len(offsets)>3
    cut=offsets[3]
    raw=bytearray(original[:cut])
    if ending=='cancelled':
        payload=json.dumps(dict(status='cancelled',waveforms=3,summary={})).encode()
        raw+=FRAME.pack(b'DONE',len(payload),zlib.crc32(payload))+payload
    elif ending=='torn':raw+=original[cut:cut+FRAME.size+5]
    elif ending=='corrupt':raw[offsets[1]+FRAME.size+4]^=1
    path=tmp_path/'stopped.tppulses.part';path.write_bytes(raw)
    manager=run(path,tmp_path)
    try:
        state=manager.current()
        if ending=='corrupt':
            assert state['status']=='failed' and 'CRC' in state['error']
        else:
            assert state['status']=='completed',state
            assert state['total_processed']==3
            assert len(manager.session.waveform(3)['samples'])==4
            manager.session.reset()
            assert manager.current()['processed']==0
    finally:manager.shutdown()


def test_open_reader_survives_writer_finalization(pulse_stream,tmp_path):
    part=tmp_path/'live.tppulses.part';part.write_bytes(pulse_stream.read_bytes())
    r=Reader(part)
    try:
        records=r.records();_,meta,_=next(records)
        part.rename(part.with_suffix(''))
        for p in meta['pulses']:assert r.transport(p['role'],p['record'])['record']==p['record']
        assert list(records)
    finally:r.close()
    reopened=Reader(part)
    try:assert reopened.header['run_id']==r.header['run_id']
    finally:reopened.close()
    manager=run(part,tmp_path)
    try:
        assert manager.current()['status']=='completed',manager.current()
        assert manager.current()['total_processed']>3
    finally:manager.shutdown()


@pytest.mark.parametrize('partial',[True,False])
def test_native_frame_reader_keeps_complete_frames_across_unaligned_buffers(tmp_path,partial):
    from types import SimpleNamespace
    from backend.m2_stream import StreamError
    from backend.m3_blocks import frame_blocks
    start=37
    path=tmp_path/('recording.tppulses.part' if partial else 'recording.tppulses')
    first=b'x'*(1024*1024+61769)
    second=b'y'*41670
    with path.open('wb') as file:
        file.write(b'h'*start)
        for body in (first,second):
            file.write(FRAME.pack(b'WAVE',len(body),zlib.crc32(body))+body)
        file.write(FRAME.pack(b'WAVE',99,0)+b'partial')
    with path.open('rb') as source:
        reader=SimpleNamespace(file=source,limit=path.stat().st_size,start=start,path=path)
        if not partial:
            with pytest.raises(StreamError,match='Truncated pulse frame'):list(frame_blocks(reader))
        else:
            recovered=[]
            for at,block,waves,_,_ in frame_blocks(reader):
                for pos in waves:
                    tag,size,crc=FRAME.unpack_from(block,pos)
                    body=bytes(block[pos+FRAME.size:pos+FRAME.size+size])
                    assert tag==b'WAVE' and zlib.crc32(body)==crc
                    recovered.append((at+pos,body))
            assert recovered==[(start,first),(start+FRAME.size+len(first),second)]


@pytest.mark.skipif(os.name!='nt',reason='Windows direct I/O')
def test_direct_input_preserves_source_identity_and_recovers_from_unsupported_read(tmp_path,monkeypatch):
    import io
    from types import SimpleNamespace
    import numpy as np
    from backend import m3_stream_input as input_reader

    original=bytes(range(251))*68000
    path=tmp_path/'shared.tppulses'
    path.write_bytes(original)
    size=12*1024**2
    storage=np.empty(size+input_reader.ALIGNMENT,dtype='u1')
    start=(-storage.ctypes.data)%input_reader.ALIGNMENT
    aligned=storage[start:start+size]
    with path.open('rb') as source:
        # The helper's size threshold chooses the large-file path. The windows
        # below all lie within the real fixture and include an unaligned tail.
        reader=SimpleNamespace(file=source,path=path,limit=300*1024**2)
        with input_reader.stream_input(reader) as read:
            assert read(65536,aligned)==size
            assert aligned.tobytes()==original[65536:65536+size]
            assert read(97,aligned[:43])==43 and aligned[:43].tobytes()==original[97:140]

        class Unsupported(io.BytesIO):
            def readinto(self,_):raise OSError('Unbuffered request is unsupported')
        monkeypatch.setattr(input_reader,'_direct_handle',lambda _:Unsupported())
        with input_reader.stream_input(reader) as read:
            assert read(0,aligned)==size and aligned.tobytes()==original[:size]
            assert read(21,aligned[:77])==77 and aligned[:77].tobytes()==original[21:98]


def test_active_reader_uses_bounded_prefix_and_restart_includes_growth(pulse_stream,tmp_path):
    full=Reader(pulse_stream)
    try:
        records=list(full.records())
        raw=pulse_stream.read_bytes()
    finally:full.close()
    part=tmp_path/'growing.tppulses.part';part.write_bytes(raw[:records[3][0]])
    first=Reader(part)
    try:
        with part.open('ab') as file:file.write(raw[records[3][0]:])
        assert len(list(first.records()))==3
    finally:first.close()
    second=Reader(part)
    try:assert len(list(second.records()))==len(records)
    finally:second.close()
