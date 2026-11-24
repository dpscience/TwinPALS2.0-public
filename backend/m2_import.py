# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Strict single-stream import. Only the current block contains full waveform arrays."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, nullcontext
import ctypes as ct
import numpy as np

from .m2_stream import FRAME, StreamError, decode_wave
from .m3_blocks import NativeTransportIndex, frame_blocks, library, read_truth_block, truth_config, verify_footer

MONITOR_ROW=np.dtype([('id','<u8'),('features','<f8',6),('classification','<u4'),('channels','<u4')])


class MonitorBlock:
    def __init__(self,block,waves,samples,persistence):
        self.block=block
        self.waves=np.asarray(waves,dtype='<u4')
        self.samples=samples
        self.rows=np.empty(len(waves),dtype=MONITOR_ROW)
        self.features=self.rows['features']
        self.densities=np.empty((len(waves),2,persistence.bins),dtype='<f8')
        self.ranges=[(*r,persistence.bins) for r in persistence.ranges]

    def record(self,i):
        offset=int(self.waves[i])
        _,size,_=FRAME.unpack_from(self.block,offset)
        start=offset+FRAME.size
        return decode_wave(bytes(self.block[start:start+size]),self.samples)


def read_scalar(reader,analysis,workers,cancel,progress,start=None,prior_truth=None):
    depth=min(8,workers)
    pool=ThreadPoolExecutor(max_workers=workers,thread_name_prefix='M2-read') if workers>1 else nullcontext()
    batch=[]
    def publish():
        nonlocal batch
        if batch:
            rows,batch=batch,[]
            analysis.publish_import(rows)
            progress(rows[-1][3])
    with pool as executor:
        records=reader.records(cancel,pool=executor,depth=depth,start=start,count=len(analysis.ids),
                               last_id=analysis.ids[-1] if analysis.ids else -1,prior_truth=prior_truth)
        with closing(records):
            try:
                for pos,meta,data in records:
                    batch.append((meta,data,str(reader.path),pos))
                    if len(batch)>=32:publish()
            finally:
                publish()


def read_stream(reader,analysis,workers,cancel,progress):
    lib=library()
    if lib is None or not hasattr(lib,'tp_pulse_monitor_batch'):
        return read_scalar(reader,analysis,workers,cancel,progress)
    ptr=ct.c_void_p
    monitor=lib.tp_pulse_monitor_batch
    monitor.argtypes=[ptr,ptr,ct.c_size_t,ct.c_uint64,ptr,ct.c_int,ct.c_int,ct.c_char_p,ct.c_int,
                      ptr,ct.c_int,ptr,ptr,ct.c_char_p,ct.c_int]
    config,tables=truth_config(reader.header,for_timing=False)  # Config borrows the two component tables.
    index=NativeTransportIndex()
    next_byte=reader.start
    try:
        try:
            with closing(frame_blocks(reader)) as blocks:
                for at,block,waves,truths,footer in blocks:
                    cancel()
                    read_truth_block(lib,index.handle,block,at,truths,config,workers)
                    if footer is not None:
                        verify_footer(reader,footer,len(analysis.ids)+len(waves))
                    if waves:
                        batch=MonitorBlock(block,waves,reader.samples,analysis.persistence)
                        bins=analysis.persistence.bins
                        centres=np.arange(bins)+.5
                        coords=np.array([lo+centres*(hi-lo)/bins for lo,hi,_ in batch.ranges])
                        error=ct.create_string_buffer(512)
                        code=monitor(index.handle,block.ctypes.data,len(block),at,batch.waves.ctypes.data,
                                     len(waves),reader.samples,reader.header['class_filter'].encode(),
                                     min(workers,len(waves)),coords.ctypes.data,bins,batch.rows.ctypes.data,
                                     batch.densities.ctypes.data,error,len(error))
                        if code:raise StreamError(error.value.decode(errors='replace'))
                        ids=batch.rows['id']
                        if (analysis.ids and int(ids[0])<=analysis.ids[-1]) or np.any(ids[1:]<=ids[:-1]):
                            raise StreamError('Waveform IDs must be strictly increasing.')
                        analysis.publish_monitor(batch,str(reader.path),at+batch.waves.astype('<u8'),
                                                 batch.features,batch.rows['classification'].astype('u1'),ids)
                    next_byte=at+len(block)
                    progress(next_byte)
            if reader.completion is None and reader.path.suffix!='.part':
                raise StreamError('Pulse stream has no completed footer.')
        except (StreamError,OSError):
            # Recover the exact valid prefix inside a rejected block. Use its
            # predecessor's verified truth entries without rereading the stream.
            cancel()
            reader.completion=None
            def prior(key):
                try:return index[key][0]-FRAME.size<next_byte
                except KeyError:return False
            read_scalar(reader,analysis,workers,cancel,progress,next_byte,prior)
    finally:
        index.close()
