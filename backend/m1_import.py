# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Project verified frames from finished transport streams into Module 1 analysis."""
import ctypes as ct
import json

import numpy as np

from .live_analysis import EVENT_DTYPE
from .native_transport_index import Arrays, Summary, ReferenceValidation, binding, read_windows, check_footer
from .provenance import decode
from .storage_health import StorageSpaceError
from .streams import EVENT_BYTES, FRAME, MAX_FRAME, StreamError, _header, _json, _open_shared_read, _tail_completion, analog_payload, frame_crc32

# APLS starts with an event ID and two counts. Each PE has four doubles,
# followed by a separate array with two light-origin bytes per PE.
ANALOG_HEADER = 16
PE_VALUES = 32
PE_TAGS = 2
PE_BYTES = PE_VALUES + PE_TAGS


def _project(buffer, mapped, index, provenance, first, last):
    """Gather variable-length records while preserving event and detector order."""
    sizes = index[first:last, 1:].view(np.int64)
    analog = index[first:last, 0].view(np.int64)
    prov = provenance[first:last].view(np.int64)
    totals = sizes.sum(axis=1)
    event_at = prov[:, 0] + prov[:, 1] + FRAME.size
    if (int(analog[0]) - FRAME.size != buffer.loaded_bytes
            or np.any(prov[:, 0] != analog + ANALOG_HEADER + PE_BYTES * totals + FRAME.size)
            or np.any(mapped[event_at - FRAME.size] != ord('E'))):
        raise ReferenceValidation('Noncanonical frame sequence')

    # Index a byte-strided view to gather EVNT structs from unaligned offsets.
    rows = np.ndarray(len(mapped) - EVENT_BYTES + 1, EVENT_DTYPE, buffer=mapped, strides=(1,))[event_at]
    ends = event_at + EVENT_BYTES
    next_frame = analog[1:] - FRAME.size
    previews = []
    # A native window ends after EVNT. Its optional TRAK belongs to that
    # event even when the following APLS falls into the next window.
    for j in [*np.flatnonzero(ends[:-1] != next_frame), len(rows)-1]:
        at = int(ends[j])
        while at + FRAME.size <= len(mapped) and mapped[at:at+4].tobytes() == b'TRAK':
            _, length, crc = FRAME.unpack_from(mapped, at)
            end = at + FRAME.size + length
            if length > MAX_FRAME or end > len(mapped):
                raise StreamError('Invalid trajectory frame length')
            data = mapped[at+FRAME.size:end].tobytes()
            if frame_crc32(data) != crc:
                raise StreamError('Trajectory frame CRC mismatch')
            event = first + int(j)
            start = int(analog[j])
            pe = analog_payload(mapped[start:start+ANALOG_HEADER+PE_BYTES*int(totals[j])], event)
            tree = decode(mapped[int(prov[j, 0]):int(prov[j].sum())], event,
                          sizes[j].tolist(), len(buffer.header['light_components']))
            previews.append(buffer.prepare_preview(_json(data), event, pe, tree, rows[j]))
            at = end
        if j < len(next_frame) and at != next_frame[j]:
            raise ReferenceValidation('Unexpected frames between events')
        ends[j] = at

    hits, clouds, births = [], [], []
    doubles = np.ndarray(len(mapped)-7, '<f8', buffer=mapped, strides=(1,))
    for ch in range(2):
        counts = sizes[:, ch]
        active = np.flatnonzero(counts)
        n = counts[active]
        offsets = np.cumsum(n) - n
        base = 0 if ch == 0 else sizes[active, 0]
        pe_index = np.arange(int(n.sum())) + np.repeat(base-offsets, n)
        values_at = np.repeat(analog[active] + ANALOG_HEADER, n) + PE_VALUES * pe_index
        tags_at = np.repeat(analog[active] + ANALOG_HEADER + PE_VALUES * totals[active], n) + PE_TAGS * pe_index
        tags = np.column_stack((mapped[tags_at], mapped[tags_at+1]))
        hits.append(np.column_stack((doubles[values_at+16], doubles[values_at+24])).astype('<f4'))

        accepted = (rows['detectors']['flags'][active, ch] & 4) != 0
        keep = np.repeat(accepted, n)
        selected = values_at[keep]
        clouds.append((rows['id'][active[accepted]], n[accepted], doubles[selected+8], doubles[selected], tags[keep]))

        # Count each (event, birth component) once, even with repeated photons.
        cherenkov = tags[:, 0] == 2
        labels = tags[cherenkov, 1]
        pairs = np.repeat(active, n)[cherenkov] * 256 + labels
        births.append((np.bincount(labels), np.bincount(np.unique(pairs) % 256)))

    with buffer.lock:
        for ch, (photons, events) in enumerate(births):
            for counts, target in ((photons, buffer.pending_births[ch]), (events, buffer.pending_birth_events[ch])):
                for k in np.flatnonzero(counts):
                    target[int(k)] = int(counts[k])
        buffer.append(rows.tobytes(), hits)
        for cloud, columns in zip(buffer.pulses, clouds):
            cloud.append_batch(*columns)
        buffer.previews.extend(previews[:max(0, 30000-len(buffer.previews))])
        buffer.loaded_bytes = int(ends[-1])


def import_completed(store, buffer, workers):
    """Return False to resume with the reference reader at the last published event."""
    lib = binding()
    if lib is None:
        return False
    with _open_shared_read(buffer.path) as source:
        size = buffer.total_bytes
        header, start = _header(source, size)
        if header != buffer.header:
            raise StreamError('Stream changed before import')
        footer = _tail_completion(source, size, start)
        count = footer.get('events')
        if footer.get('status') != 'completed' or not count or count > (size-start)//(EVENT_BYTES+3*FRAME.size+40):
            return False
        # The native reader shares its output ABI with Module 2. Keep the
        # arrays alive until all of its window validators have finished.
        try:
            mapped = np.memmap(source, mode='r', dtype='u1', shape=(size,))
            layouts = ((4,'d'), (2,'d'), (2,'d'), (2,'d'), (3,'<u8'), (2,'<u8'), (2,'<u4'), (2,'u1'))
            fields = [np.empty((count, width), dtype=dtype) for width, dtype in layouts]
        except (MemoryError, OSError, OverflowError):
            return False
        index, provenance = fields[4:6]
        pointers = [a.ctypes.data for a in fields]
        pointers.insert(4, None)  # Module 2's optional cascade-prefix table.
        cfg = json.dumps(dict(header=header, count=count, tails=[0, 0]), allow_nan=False).encode()
        handle = lib.tp_transport_index_map(mapped.ctypes.data, size, cfg, ct.byref(Arrays(*pointers)))
        if not handle:
            return False

        seen, offset, summary = ct.c_uint64(), ct.c_uint64(), Summary()
        try:
            for pos, block, length in read_windows(source, size, start):
                if store.import_cancel.is_set():
                    return True
                if store.storage_error:
                    raise StorageSpaceError(store.storage_error)
                if offset.value >= pos + length:
                    continue
                first = seen.value
                offset.value = pos
                code = lib.tp_transport_index_window(handle, block.ctypes.data, length, workers,
                                                     ct.byref(offset), ct.byref(seen), ct.byref(summary))
                if code < 0:
                    return False
                if seen.value > first:
                    _project(buffer, mapped, index, provenance, first, seen.value)
                    store._prewarm_density()
                if code == 1:
                    check_footer(json.loads(lib.tp_transport_index_footer(handle)), summary, count)
                    with buffer.lock:
                        buffer.loaded_bytes = size
                        buffer.status = 'completed'
                        buffer.verified = True
                        buffer.revision += 1
                    return True
            return False
        except ReferenceValidation:
            return False
        finally:
            lib.tp_transport_index_destroy(handle)
