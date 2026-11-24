# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Self-contained CRC-framed pulse streams with bounded random-access reading."""
import hashlib
import ctypes as ct
import json
import os
from pathlib import Path
import struct
import zlib
import math
import numpy as np
from .m1_store import encode, Conflict
from .streams import _open_shared_read, StreamError, frame_crc32, read_done_footer
from .m2_physics import CLASS_NAMES

MAGIC = b'TPPULS06'
TRANSPORT = struct.Struct('<IQI')  # input role, M1 record ID, APLS byte count
FRAME = struct.Struct('<4sII')
MAX_HEADER = 16*1024*1024
MAX_FRAME = 32*1024*1024

class HistorySource(ct.Structure):
    _fields_=[('data',ct.c_void_p),('index',ct.c_void_p),('provenance',ct.c_void_p),('size',ct.c_uint64),('count',ct.c_uint64)]
    @classmethod
    def from_library(cls,lib):
        return cls(lib.map.ctypes.data,lib.index.ctypes.data,lib.provenance_index.ctypes.data,lib.map.nbytes,len(lib))

def json_value(payload):
    try:
        return json.loads(payload, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite number')))
    except (ValueError, UnicodeError) as exc:
        raise StreamError('Pulse stream contains invalid JSON metadata.') from exc


def decode_wave(payload, samples):
    if len(payload)<4: raise StreamError('Truncated pulse record.')
    n, = struct.unpack_from('<I',payload)
    if n>MAX_HEADER or len(payload)!=4+n+samples*16: raise StreamError('Pulse record length disagrees with sample count.')
    meta = json_value(payload[4:4+n])
    data = np.frombuffer(payload, dtype='<f4', offset=4+n).reshape(4,samples).copy()
    if not isinstance(meta,dict) or meta.get('class') not in CLASS_NAMES or type(meta.get('id')) is not int or meta['id']<0:
        raise StreamError('Pulse record has an invalid class or ID.')
    if not np.all(np.isfinite(data)) or np.any(np.diff(data[[0,2]],axis=1)<=0):
        raise StreamError('Pulse samples must be finite with increasing channel time axes.')
    if not isinstance(meta.get('pulses'),list) or not all(isinstance(p,dict) and p.get('role') in (0,1) and p.get('channel') in (0,1) and p.get('light_origin') in ('scintillation','cherenkov','mixed') for p in meta['pulses']):
        raise StreamError('Invalid pulse origin metadata.')
    def number(v): return type(v) in (int,float) and math.isfinite(v)
    def integer(v): return type(v) is int and v>=0
    if (not all(number(meta.get(k)) for k in ('start_ns','trigger_ns','end_ns','busy_until_ns'))
            or not meta['start_ns']<=meta['trigger_ns']<=meta['end_ns']<=meta['busy_until_ns']
            or meta['end_ns']<=meta['start_ns'] or meta.get('trigger_channel') not in (0,1)
            or not integer(meta.get('trigger_cell')) or meta['trigger_cell']>=samples
            or not isinstance(meta.get('baseline_mV'),list) or len(meta['baseline_mV'])!=2 or not all(map(number,meta['baseline_mV']))
            or not isinstance(meta.get('clipped'),list) or len(meta['clipped'])!=2 or not all(type(v) is bool for v in meta['clipped'])):
        raise StreamError('Invalid waveform timing, baseline or clipping metadata.')
    if not meta['pulses'] or any(
        not all(integer(p.get(k)) for k in ('channel','role','decay','record','component'))
        or not all(number(p.get(k)) for k in ('onset_ns','origin_ns','source_time_ns','lifetime_ns','height_mV'))
        or p['height_mV']<=0 or p['lifetime_ns']<0 for p in meta['pulses']):
        raise StreamError('Invalid pulse origin values.')
    context=meta.get('timeline')
    if (not isinstance(context,dict) or not all(number(context.get(k)) for k in ('low_ns','high_ns','known_until_ns'))
            or not context['low_ns']<=meta['start_ns']<meta['end_ns']<=meta['busy_until_ns']<=context['high_ns']
            or not meta['end_ns']<=context['known_until_ns']<=context['high_ns']
            or not integer(context.get('total')) or not isinstance(context.get('pulses'),list)
            or len(context['pulses'])!=min(context['total'],256)):
        raise StreamError('Invalid acquisition timeline metadata.')
    for pulse in context['pulses']:
        if (not isinstance(pulse,dict) or pulse.get('role') not in (0,1) or pulse.get('channel') not in (0,1)
                or pulse.get('light_origin') not in ('scintillation','cherenkov','mixed')
                or not all(integer(pulse.get(k)) for k in ('channel','role','decay','record','component'))
                or not all(number(pulse.get(k)) for k in ('onset_ns','origin_ns','source_time_ns','lifetime_ns','height_mV'))
                or pulse['height_mV']<=0 or pulse['lifetime_ns']<0
                or not context['low_ns']-1e-6<=meta['start_ns']+pulse['onset_ns']<=context['known_until_ns']+1e-6):
            raise StreamError('Invalid acquisition timeline pulse.')
    return meta,data


class Writer:
    def __init__(self,path,header,overwrite=False):
        self.path = Path(path)
        self.part = self.path.with_name(self.path.name+'.part')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        if not overwrite and (self.path.exists() or self.part.exists()):
            raise Conflict(f'File already exists: {self.path}. Confirm replacement first.')
        self.file = self.part.open('wb' if overwrite else 'xb',buffering=4*1024*1024)
        payload = encode(header).encode('utf-8')
        if len(payload)>MAX_HEADER: self.file.close(); raise ValueError('Pulse stream header exceeds 16 MiB.')
        self.file.write(MAGIC+struct.pack('<I',len(payload))+payload)
        self.file.flush()
        self.count = 0
        self.closed = False
        self.transports=set()
        self._packing=None
        self._sweep_seen=None

    def frame(self,tag,payload):
        if len(payload)>MAX_FRAME: raise ValueError('Too many overlapping pulses for one 32 MiB waveform frame. Reduce activity or the sweep duration.')
        self.file.write(FRAME.pack(tag,len(payload),frame_crc32(payload)))
        self.file.write(payload)

    def write(self,meta,data):
        prepared=getattr(data,'stream_frame',None)
        if prepared is not None:
            offset=self.file.tell();self.file.write(prepared);self.count+=1
            return offset
        payload = encode(meta).encode('utf-8')
        offset = self.file.tell()
        self.frame(b'WAVE',struct.pack('<I',len(payload))+payload+np.asarray(data,dtype='<f4').tobytes())
        self.count += 1
        return offset

    def retain_transport(self,meta,libraries,keys=None):
        """One copy per source record, however often shuffling reuses it."""
        references=((p['role'],p['record']) for p in meta['pulses']) if keys is None else ((role,record) for role,record,ch in keys)
        for key in references:
            if key in self.transports or (self._sweep_seen is not None and self._sweep_seen[key[0]][key[1]]):continue
            analog,provenance=libraries[key[0]].transport(key[1])
            self.frame(b'TRTH',TRANSPORT.pack(*key,len(analog))+analog+provenance)
            self.transports.add(key)
            if self._sweep_seen is not None:self._sweep_seen[key[0]][key[1]]=1

    def flush(self): self.file.flush()

    def write_group(self,rows,libraries):
        if self._sweep_seen is not None:
            offsets=[]
            for meta,data in rows:
                self.retain_transport(meta,libraries,getattr(data,'transport_keys',None))
                offsets.append(self.write(meta,data))
            return offsets
        if self._packing is None and all(getattr(lib,'verified_frame_crcs',False) for lib in libraries):
            from .analog_pmt import native_library
            fn=getattr(native_library(),'tp_wave_frames',None)
            if fn is not None:
                ptr=ct.c_void_p
                fn.argtypes=[ct.POINTER(HistorySource),ptr,ct.c_uint64,ptr,ct.POINTER(ct.c_char_p),ptr,ct.c_uint32,ptr,ct.c_uint64,ptr]
                fn.restype=ct.c_int64
                sources=(HistorySource*2)(*(HistorySource(lib.map.ctypes.data,lib.index.ctypes.data,
                            lib.provenance_index.ctypes.data,lib.map.nbytes,len(lib)) for lib in libraries))
                self._packing=(fn,sources,np.empty(2*1024*1024,dtype='u1'))
        n=len(rows)
        if self._packing is not None and all(hasattr(data,'transport_keys') for _,data in rows):
            fn,sources,buffer=self._packing
            keys=[];seen=set();counts=[];frames=[]
            for _,data in rows:
                previous=len(keys)
                for role,record,_ in data.transport_keys:
                    key=role,record
                    if key not in self.transports and key not in seen:keys.append(key);seen.add(key)
                counts.append(len(keys)-previous);frames.append(data.stream_frame)
            keys=np.asarray(keys,dtype=np.uint64);counts=np.asarray(counts,dtype=np.uint32)
            lengths=np.fromiter(map(len,frames),dtype=np.uint64,count=n);offsets=np.empty(n,dtype=np.uint64)
            pointers=(ct.c_char_p*n)(*frames)
            args=(sources,keys.ctypes.data,len(seen),counts.ctypes.data,pointers,lengths.ctypes.data,n)
            size=fn(*args,buffer.ctypes.data,buffer.nbytes,offsets.ctypes.data)
            if size>buffer.nbytes and size<=8*1024*1024:
                buffer=np.empty(size,dtype='u1');self._packing=(fn,sources,buffer)
                size=fn(*args,buffer.ctypes.data,buffer.nbytes,offsets.ctypes.data)
            if 0<=size<=buffer.nbytes:
                start=self.file.tell();self.file.write(memoryview(buffer)[:size])
                self.count+=n;self.transports.update(seen)
                return (offsets+start).tolist()
        offsets=[]
        for meta,data in rows:
            self.retain_transport(meta,libraries,getattr(data,'transport_keys',None))
            offsets.append(self.write(meta,data))
        return offsets

    def prepare_sweeps(self,batch,libraries,pool):
        """Claim new histories in order, then gather their checked bytes in parallel."""
        from .native_sweeps import FrameBuffers,binding
        if not all(getattr(lib,'verified_frame_crcs',False) for lib in libraries):return None
        if self._sweep_seen is None:
            sources=(HistorySource*2)(*(HistorySource.from_library(lib) for lib in libraries))
            self._sweep_seen=[np.zeros(len(lib),dtype='u1') for lib in libraries]
            for role,record in self.transports:self._sweep_seen[role][record]=1
            library=binding()._dll
            ptr=ct.c_void_p
            claim=library.tp_sweep_histories
            claim.argtypes=[ct.POINTER(HistorySource),ptr,ptr,ct.c_uint64,ptr,ct.c_uint32,ptr,
                            ct.c_uint64,ct.c_uint64,ptr,ptr,ct.POINTER(ct.c_uint64)]
            claim.restype=ct.c_int64
            copy_frames=library.tp_copy_sweeps
            copy_frames.argtypes=[ct.POINTER(HistorySource),ptr,ptr,ct.c_uint32,ptr,ct.c_uint64,ptr,ptr,ct.c_uint64,ptr]
            copy_frames.restype=ct.c_int64
            self._sweep_packing=(sources,claim,copy_frames,FrameBuffers())
        sources,claim,copy_frames,buffers=self._sweep_packing
        limit=8*1024*1024
        records=np.empty((len(batch.keys),2),dtype=np.uint64)
        per_wave=np.empty(len(batch.rows),dtype=np.uint32)
        new_count=ct.c_uint64()
        size=claim(sources,self._sweep_seen[0].ctypes.data,self._sweep_seen[1].ctypes.data,
                   len(batch.frames),batch.rows.ctypes.data,len(batch.rows),batch.keys.ctypes.data,len(batch.keys),
                   limit,records.ctypes.data,per_wave.ctypes.data,ct.byref(new_count))
        if size<0:raise ValueError('Invalid transport references in accepted sweeps')
        if size>limit:return None
        def gather():
            offsets=batch.rows['begin'].copy()
            if not new_count.value:return batch.frames,offsets
            frames=np.frombuffer(batch.frames,dtype='u1')
            output=buffers.acquire(size)
            written=copy_frames(sources,frames.ctypes.data,batch.rows.ctypes.data,len(offsets),
                                records.ctypes.data,new_count.value,per_wave.ctypes.data,
                                output.ctypes.data,size,offsets.ctypes.data)
            if written!=size:raise ValueError('Invalid transport history in accepted sweeps')
            return output,offsets
        return pool.submit(gather)

    def write_prepared(self,output,offsets):
        start=self.file.tell()
        self.file.write(output)
        self.count+=len(offsets)
        return offsets+start

    def finish(self,status,summary):
        if self.closed: return
        try:
            self.frame(b'DONE',encode({'status':status,'waveforms':self.count,'summary':summary}).encode('utf-8'))
            self.file.flush();os.fsync(self.file.fileno())
        finally:
            self.file.close();self.closed=True
        if status=='completed': os.replace(self.part,self.path)


class Reader:
    def __init__(self,path):
        self.path = Path(path).resolve()
        # A live writer can finalize between selection and opening a preview.
        try:self.file = _open_shared_read(self.path)
        except FileNotFoundError:
            if self.path.suffix!='.part':raise
            self.path=self.path.with_suffix('')
            self.file = _open_shared_read(self.path)
        try:
            self.limit = os.fstat(self.file.fileno()).st_size
            if self.file.read(8)!=MAGIC: raise StreamError('Choose a current .tppulses pulse stream.')
            nbytes=self.file.read(4)
            if len(nbytes)!=4: raise StreamError('Incomplete pulse stream header.')
            n,=struct.unpack('<I',nbytes)
            if n>MAX_HEADER or n+12>self.limit: raise StreamError('Invalid pulse stream header length.')
            self.header = json_value(self.file.read(n))
            if not isinstance(self.header,dict) or self.header.get('format')!='twinpals-pulse-stream' or type(self.header.get('version')) is not int or self.header.get('version')!=6:
                raise StreamError('Unsupported pulse stream format.')
            from .m2_models import RuntimeProfile as Profile
            p = Profile.model_validate(self.header.get('profile')).model_dump(mode='json')
            if hashlib.sha256(encode(p).encode()).hexdigest()!=self.header.get('settings_sha256'):
                raise StreamError('Pulse stream settings do not match their SHA-256.')
            if self.header.get('isotope') not in ('na22','co60') or any(not isinstance(self.header.get(k),str) or not self.header[k] for k in ('run_id','stream_id','created_utc')):
                raise StreamError('Pulse stream is missing its run, isotope or stream identity.')
            if self.header.get('class_filter') not in ('all',*CLASS_NAMES):
                raise StreamError('Invalid pulse stream class filter.')
            from .m2_models import resolve, reference_profile
            resolved=self.header.get('resolved')
            if not isinstance(resolved,dict) or resolved.get('profile')!=p:
                raise StreamError('Pulse stream has no consistent component snapshot.')
            components=[resolved.get('digitizer')]
            if not all(isinstance(c,dict) for c in components):
                raise StreamError('Pulse stream has invalid digitizer metadata.')
            expected=resolve(reference_profile(p),components,check_mixture=self.header['isotope']=='na22')
            # Output layout is archived as written and already covered by the hash.
            # New editable profiles always resolve to a single combined output.
            if expected['profile'] != {**p,'output_mode':'combined'}:
                raise StreamError('Pulse stream digitizer parameters disagree with its database snapshot.')
            if expected['cell_intervals_ns'] != resolved.get('cell_intervals_ns'):
                raise StreamError('Pulse stream fixed cell pattern disagrees with its seed and digitizer snapshot.')
            from .streams import validate_analog_responses
            responses=resolved.get('analog_response')
            validate_analog_responses(responses)
            inputs=self.header.get('inputs')
            roles=['na22_prompt','na22_annihilation'] if self.header['isotope']=='na22' else ['co60_1173','co60_1332']
            if not isinstance(inputs,list) or len(inputs)!=2:
                raise StreamError('Pulse stream requires the two original M1 input snapshots.')
            headers=[item.get('header') if isinstance(item,dict) else None for item in inputs]
            if any(not isinstance(h,dict) or h.get('format')!='twinpals-stream' or h.get('version')!=6
                   or h.get('role')!=roles[i] or h.get('analog_response')!=responses for i,h in enumerate(headers)):
                raise StreamError('Pulse stream input roles or analog PMT snapshots disagree.')
            if any(not headers[0].get(k) or headers[0].get(k)!=headers[1].get(k) for k in ('run_id','settings_sha256')):
                raise StreamError('Pulse stream inputs do not belong to one M1 run.')
            if not headers[0].get('stream_id') or headers[0].get('stream_id')==headers[1].get('stream_id'):
                raise StreamError('Pulse stream input identities are missing or duplicated.')
            self.samples = p['digitization']['samples']
            self.start = self.file.tell()
            self.completion = None
            self.transports={}
        except BaseException:
            self.file.close();raise

    def close(self): self.file.close()

    def inspect_completion(self):
        done = read_done_footer(self.file, self.limit, self.start, MAX_FRAME + FRAME.size)
        if done is None:
            if self.path.suffix != '.part':
                raise StreamError('Pulse stream has no completed footer.')
            return {'status': 'incomplete', 'waveforms': None, 'verified': False}
        if (done.get('status') not in ('completed', 'cancelled', 'failed')
                or type(done.get('waveforms')) is not int or done['waveforms'] < 0):
            raise StreamError('Invalid pulse stream footer.')
        if self.path.suffix != '.part' and done['status'] != 'completed':
            raise StreamError('An unfinished pulse stream must keep its .part suffix.')
        return {**done, 'verified': False}

    def record(self,offset):
        self.file.seek(offset)
        header=self.file.read(FRAME.size)
        if len(header)!=FRAME.size: raise StreamError('Truncated pulse frame.')
        tag,n,crc=FRAME.unpack(header)
        if tag!=b'WAVE' or n>MAX_FRAME: raise StreamError('Invalid waveform frame.')
        payload=self.file.read(n)
        if len(payload)!=n or zlib.crc32(payload)!=crc: raise StreamError('Waveform CRC mismatch or incomplete payload.')
        return decode_wave(payload,self.samples)

    def transport(self,role,record):
        """Call records() first to build the validated transport index."""
        at,n,crc=self.transports[role,record]
        # Independent file handle: never disturb an active waveform iterator.
        try:
            file=_open_shared_read(self.path)
        except FileNotFoundError:
            # The reader's original shared handle survives the writer's rename.
            # transport() is synchronous between records() yields: restore its
            # cursor before the iterator resumes, without trusting a new file.
            position=self.file.tell()
            try:self.file.seek(at);payload=self.file.read(n)
            finally:self.file.seek(position)
        else:
            with file:file.seek(at);payload=file.read(n)
        if len(payload)!=n or zlib.crc32(payload)!=crc:raise StreamError('Contribution truth CRC mismatch')
        return self._decode_transport(payload)

    def _decode_transport(self,payload):
        from .streams import analog_payload
        from .provenance import decode
        if len(payload)<TRANSPORT.size:raise StreamError('Truncated contribution truth')
        role,record,n=TRANSPORT.unpack_from(payload)
        if role not in (0,1) or n>len(payload)-TRANSPORT.size:raise StreamError('Invalid contribution truth reference')
        analog=analog_payload(payload[TRANSPORT.size:TRANSPORT.size+n],record)
        provenance=decode(payload[TRANSPORT.size+n:],record,[len(a) for a in analog],len(self.header['inputs'][role]['header']['light_components']))
        return dict(role=role,record=record,photoelectrons=analog,provenance=provenance)

    def _frames(self,cancel):
        while self.file.tell()<self.limit:
            cancel(); offset=self.file.tell(); header=self.file.read(FRAME.size)
            if len(header)!=FRAME.size:
                if self.path.suffix=='.part': return
                raise StreamError('Truncated pulse frame header.')
            tag,n,crc=FRAME.unpack(header)
            if n>MAX_FRAME: raise StreamError('Pulse frame exceeds 32 MiB.')
            if self.file.tell()+n>self.limit:
                if self.path.suffix=='.part': return
                raise StreamError('Truncated pulse frame payload.')
            payload=self.file.read(n)
            yield offset,tag,crc,payload

    def _decode_frames(self,frames):
        for offset,tag,crc,payload in frames:
            if zlib.crc32(payload)!=crc: raise StreamError('Pulse frame CRC mismatch.')
            if tag==b'WAVE':
                value=decode_wave(payload,self.samples)
            elif tag==b'TRTH':
                truth=self._decode_transport(payload)
                value=(truth['role'],truth['record'])
            elif tag==b'DONE':
                value=json_value(payload)
            else:raise StreamError('Unknown pulse stream frame.')
            yield offset,tag,len(payload),crc,value

    def _validated_frames(self,cancel,pool,depth):
        frames=self._frames(cancel)
        if pool is None:
            yield from self._decode_frames(frames)
            return
        from collections import deque
        pending=deque()
        def decode(batch):
            decoded=[]
            try:
                decoded.extend(self._decode_frames(batch))
            except ValueError as exc:
                decoded.append(exc)
            return decoded
        def take():
            for item in pending.popleft().result():
                if isinstance(item,ValueError):raise item
                yield item
        try:
            batch=[];size=0;read_error=None
            while True:
                try:frame=next(frames)
                except StopIteration:break
                except (StreamError,OSError) as exc:
                    read_error=exc
                    break
                batch.append(frame);size+=len(frame[3])
                if size>=512*1024 or len(batch)>=32:
                    pending.append(pool.submit(decode,batch))
                    batch=[];size=0
                    if len(pending)>=depth:yield from take()
            if batch:pending.append(pool.submit(decode,batch))
            while pending:yield from take()
            if read_error:raise read_error
        finally:
            for task in pending:task.cancel()

    def records(self,cancel=lambda:None,*,pool=None,depth=1,start=None,count=0,last_id=-1,prior_truth=None):
        self.file.seek(self.start if start is None else start)
        self.transports.clear()
        def known(key):
            return key in self.transports or (prior_truth is not None and prior_truth(key))
        for offset,tag,n,crc,value in self._validated_frames(cancel,pool,depth):
            if tag==b'WAVE':
                meta,data=value
                if any(not known((p['role'],p['record'])) for p in meta['pulses']):
                    raise StreamError('Waveform has an unresolved transport contribution')
                if self.header['class_filter']!='all' and meta['class']!=self.header['class_filter']:
                    raise StreamError('Waveform classification disagrees with the selected class stream.')
                if meta['id']<=last_id: raise StreamError('Waveform IDs must be strictly increasing.')
                last_id=meta['id'];count+=1
                yield offset,meta,data
            elif tag==b'TRTH':
                key=value
                if known(key):raise StreamError('Duplicate transport truth record')
                self.transports[key]=(offset+FRAME.size,n,crc)
            elif tag==b'DONE':
                done=value
                if not isinstance(done,dict) or done.get('status') not in ('completed','cancelled','failed') or done.get('waveforms')!=count or offset+FRAME.size+n!=self.limit:
                    raise StreamError('Pulse footer disagrees with its records.')
                if self.path.suffix!='.part' and done['status']!='completed':
                    raise StreamError('An unfinished pulse stream must keep its .part suffix.')
                self.completion=done
                return
            else: raise StreamError('Unknown pulse stream frame.')
        if self.path.suffix!='.part': raise StreamError('Pulse stream has no completed footer.')
