# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Bounded Module 3 frame batches. The scalar reader remains available without the native library."""
import ctypes as ct
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
import sys
import zlib
import numpy as np
from .m2_stream import FRAME, MAX_FRAME, StreamError, json_value
from .m3_signal import _response_span
from .execution import resolve_threads
from .m3_stream_input import ALIGNMENT, stream_input

FEATURES = ['height','area','rise_ns','fall_ns','cfd_ns']
REASONS = ['', 'Invalid samples or baseline region', 'No usable pulse', 'Missing leading CF crossing',
           'ADC clipping', 'Outside PHS windows', 'Area filter', 'Rise/fall filter', 'Insufficient pre-pulse baseline']
RESULT=np.dtype([('id','<u8'),('start','<f8'),('values','<f8',(2,5)),('reason','u1',2),
                 ('clipped','u1',2),('category','u1'),('origin','u1'),('scatter','u1'),('reserved','u1'),('contributions','<u4',(2,2))])
REF=np.dtype([('record','<u8'),('role','<u4'),('length','<u4'),('crc','<u4'),('reserved','<u4')])
class TruthConfig(ct.Structure):
    _fields_=[('flags',ct.c_void_p*2),('components',ct.c_uint32*2),('tails',ct.c_double*2)]

class Channel(ct.Structure):
    _fields_=[('positive',ct.c_int),('baseline',ct.c_int),('median',ct.c_int),('cfd',ct.c_double),('minimum',ct.c_double),('interpolation',ct.c_int),('steps',ct.c_int),('first',ct.c_int),('pre_pulse',ct.c_int),('gap',ct.c_int)]

@lru_cache(maxsize=1)
def library():
    root=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]
    path=root/'.runtime/bin/twinpals-lifetime.dll'
    if not path.is_file():return None
    lib=ct.CDLL(str(path))
    if not hasattr(lib,'tp_lifetime_abi') or lib.tp_lifetime_abi()!=8:return None
    ptr=ct.c_void_p
    lib.tp_lifetime_create.argtypes=[];lib.tp_lifetime_create.restype=ptr
    lib.tp_lifetime_destroy.argtypes=[ptr];lib.tp_lifetime_destroy.restype=None
    lib.tp_lifetime_lookup.argtypes=[ptr,ct.c_uint32,ct.c_uint64,ct.POINTER(ct.c_uint64),ct.POINTER(ct.c_uint32),ct.POINTER(ct.c_uint32)]
    lib.tp_lifetime_truth.argtypes=[ptr,ptr,ct.c_size_t,ct.c_uint64,ptr,ct.c_int,ct.POINTER(TruthConfig),ct.c_int,ptr,ct.c_char_p,ct.c_int]
    lib.tp_lifetime_batch.argtypes=[ptr,ptr,ct.c_size_t,ct.c_uint64,ptr,ct.c_int,ct.c_int,ptr,
                                    ct.c_char_p,ct.c_int,ct.c_int,ptr,ct.c_char_p,ct.c_int]
    return lib

class NativeTransportIndex:
    """Share the verified transport dictionary between acquisition and waveform inspection."""
    def __init__(self):
        self.lib=library()
        self.handle=self.lib.tp_lifetime_create()
        if not self.handle:raise MemoryError('Cannot allocate the Module 3 transport index')

    def __getitem__(self,key):
        role,record=key
        offset=ct.c_uint64()
        length,crc=ct.c_uint32(),ct.c_uint32()
        if not self.lib.tp_lifetime_lookup(self.handle,role,record,ct.byref(offset),ct.byref(length),ct.byref(crc)):
            raise KeyError(key)
        return offset.value,length.value,crc.value

    def close(self):
        if self.handle:self.lib.tp_lifetime_destroy(self.handle);self.handle=None


def channel_settings(channels,rule='highest'):
    return (Channel*2)(*(Channel(c['polarity']=='positive',c['baseline_samples'],c['median_samples'],c['cfd_percent'],c['minimum_height_mV'],
                                 ('linear','cubic','akima').index(c.get('interpolation','linear')),c.get('intra_steps',8),rule=='first',c.get('baseline_mode')=='pre_pulse',c.get('baseline_gap',4)) for c in channels))

def decode_block(lib,context,reader,block,at,offsets,profile):
    positions=np.asarray(offsets,dtype='<u4')
    results=np.zeros(len(positions),dtype=RESULT)
    error=ct.create_string_buffer(512)
    code=lib.tp_lifetime_batch(context,np.frombuffer(block,dtype='u1').ctypes.data,len(block),at,positions.ctypes.data,len(positions),reader.samples,
        channel_settings(profile['channels'],profile.get('pulse_selection','highest')),reader.header['class_filter'].encode(),reader.header['isotope']=='na22',
        resolve_threads(profile['workers'],len(positions)),results.ctypes.data,error,len(error))
    if code:raise StreamError(error.value.decode(errors='replace'))
    return at+positions.astype('<u8'),results

def truth_config(header, *, for_timing=True):
    def flags(c):
        volume=c['volume']
        return (2 if volume.startswith('Shield') else 4 if volume.startswith(('Sample','Foil','Source'))
                else 8 if volume=='ScintA' else 16 if volume=='ScintB' else 0)
    components=[inp['header']['light_components'] for inp in header['inputs']]
    tables=[]
    for group in components:
        table=np.zeros(len(group),dtype='u1')
        if for_timing:
            for c in group:table[c['id']]=flags(c)
        tables.append(table)
    tails=[0.,0.]
    if for_timing:
        bandwidth=header['profile']['digitization']['input_bandwidth_MHz']
        tails=[_response_span(r['order'],r['tau_ns'],bandwidth) for r in header['resolved']['analog_response']]
    return TruthConfig((ct.c_void_p*2)(*(t.ctypes.data for t in tables)),(ct.c_uint32*2)(*(len(t) for t in tables)),(ct.c_double*2)(*tails)),tables


def frame_blocks(reader):
    """Read aligned sequential chunks while the preceding block is being measured."""
    source, limit = reader.file, reader.limit
    source.seek(reader.start)
    block_size = 48 * 1024 * 1024
    def read_block(at, storage, carry, target):
        # Match the file offset modulo the sector alignment even when an incomplete
        # frame from the preceding slot sits in front of the next aligned read.
        offset = (at - storage.ctypes.data) % ALIGNMENT
        buffer = storage[offset:]
        length = len(carry)
        buffer[:length] = carry
        def fill(end):
            nonlocal length
            while length < end:
                n = read_into(at + length, buffer[length:end])
                if not n:
                    raise StreamError('Pulse stream became shorter while reading.')
                length += n

        # Align file addresses independently of the header length. Move only the
        # unfinished frame between slots, never issue a small tail read per block.
        end_at = ((at + target + ALIGNMENT - 1) // ALIGNMENT) * ALIGNMENT
        fill(min(limit, end_at) - at)
        pos, waves, truths, footer = 0, [], [], None
        while pos + FRAME.size <= length:
            tag, n, crc = FRAME.unpack_from(buffer, pos)
            if n > MAX_FRAME:
                raise StreamError('Pulse frame exceeds 32 MiB.')
            end = pos + FRAME.size + n
            if at + end > limit:
                if reader.path.suffix != '.part':
                    raise StreamError('Truncated pulse frame at the end of the stream.')
                return buffer[:pos], waves, truths, footer, limit, buffer[:0]
            if end > length:
                if pos:
                    break
                # A first-frame transport record may exceed the small startup block.
                fill(end)
            if tag == b'WAVE':
                waves.append(pos)
            elif tag == b'TRTH':
                truths.append(pos)
            elif tag == b'DONE':
                payload = memoryview(buffer)[pos+FRAME.size:end]
                if zlib.crc32(payload) != crc:
                    raise StreamError('Pulse frame CRC mismatch.')
                footer = json_value(bytes(payload))
                if not isinstance(footer,dict) or at + end != limit:
                    raise StreamError('Pulse footer disagrees with its records.')
            else:
                raise StreamError('Unknown pulse stream frame.')
            pos = end
        if at + length == limit and pos < length:
            if reader.path.suffix != '.part':
                raise StreamError('Truncated pulse frame at the end of the stream.')
            return buffer[:pos], waves, truths, footer, limit, buffer[:0]
        return buffer[:pos], waves, truths, footer, at+pos, buffer[pos:length]

    at = reader.start
    if at >= limit:
        return
    buffers = [np.empty(max(block_size, MAX_FRAME+FRAME.size)+2*ALIGNMENT,dtype='u1') for _ in range(2)]
    slot = 0
    with stream_input(reader) as read_into, ThreadPoolExecutor(max_workers=1, thread_name_prefix='M3-input') as pool:
        future = pool.submit(read_block, at, buffers[slot], buffers[slot][:0], 1024*1024)
        while at < limit:
            block, waves, truths, footer, next_at, carry = future.result()
            slot = 1-slot
            if next_at < limit:
                future = pool.submit(read_block, next_at, buffers[slot], carry, block_size)
            yield at, block, waves, truths, footer
            at = next_at


def read_truth_block(lib,context,block,at,truths,config,workers,register=None):
    if truths:
        offsets=np.asarray(truths,dtype='<u4')
        refs=np.empty(len(truths),dtype=REF) if register is not None else None
        error=ct.create_string_buffer(512)
        code=lib.tp_lifetime_truth(context,block.ctypes.data,len(block),at,offsets.ctypes.data,len(truths),
            ct.byref(config),min(workers,len(truths)),refs.ctypes.data if refs is not None else None,error,len(error))
        if code:raise StreamError(error.value.decode(errors='replace'))
        if refs is not None:
            register(zip(refs['role'].tolist(),refs['record'].tolist(),(at+FRAME.size+i for i in truths),
                         refs['length'].tolist(),refs['crc'].tolist()))


def verify_footer(reader,footer,count):
    if (not isinstance(footer,dict) or footer.get('status') not in ('completed','cancelled','failed') or footer.get('waveforms')!=count or
        reader.path.suffix!='.part' and footer['status']!='completed'):raise StreamError('Pulse footer disagrees with its records.')
    reader.completion=footer


def measured_blocks(reader, register, settings, cancel, index=None):
    """Validate transport and waveforms in parallel, commit in stream order."""
    config,tables=truth_config(reader.header)  # Keep table buffers alive for the C call.
    owned=index is None
    if owned:index=NativeTransportIndex()
    lib=index.lib;context=index.handle
    count=0;previous=-1;done=False
    try:
        for at,block,waves,truths,footer in frame_blocks(reader):
            cancel()
            profile=settings()
            read_truth_block(lib,context,block,at,truths,config,resolve_threads(profile['workers'],max(1,len(truths))),register)
            if waves:
                positions,rows=decode_block(lib,context,reader,block,at,waves,profile)
                ids=rows['id']
                if int(ids[0])<=previous or np.any(ids[1:]<=ids[:-1]):raise StreamError('Waveform IDs must be strictly increasing.')
                previous=int(ids[-1]);count+=len(rows)
                yield positions,rows,at+len(block)
            if footer is not None:
                verify_footer(reader,footer,count);done=True
        if not done and reader.path.suffix!='.part':raise StreamError('Pulse stream has no completed footer.')
    finally:
        if owned:index.close()

