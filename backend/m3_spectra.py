# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Directional lifetime and pulse-height comparisons from the same measured pairs."""
from collections import Counter, OrderedDict
import math
from threading import Lock

import numpy as np

from .m3_measurements import SCATTERS
from .m3_signal import CATEGORIES
from .m3_subtypes import subtype_key

DIRECTIONS = ('AB', 'BA', 'SS')
GATES = (('start', 'stop'), ('stop', 'start'), ('stop', 'stop'))
ORIGINS = ('scintillation', 'cherenkov', 'mixed', 'unknown')
TOTAL = len(CATEGORIES)
# Only pairs that can enter a directional spectrum need an analysis record.
RECORD = np.dtype([('dt', '<f8'), ('height', '<f8', 2), ('direction', 'u1'),
                   ('category', 'u1'), ('origin', 'u1'), ('scatter', 'u1'),
                   ('passed', '?'), ('filtered', '?'), ('subtype', '<u4')])


def cable_delays(header):
    channels = (header or {}).get('profile', {}).get('channels', [])
    return [channels[i].get('cable_delay_ns') if i < len(channels) else None for i in (0, 1)]


def enabled_directions(channels):
    return [any(channels[i][role][filter_type]['enabled']
                for i, role in enumerate(roles) for filter_type in ('area', 'shape'))
            for roles in GATES]


class ComparisonBank:
    def __init__(self, view, floor, maxima, delay):
        bins = math.ceil((view.high_ns - view.low_ns) * 1000 / view.bin_ps)
        layer_count = TOTAL + 1
        self.subhist = [[{} for _ in range(3)] for _ in range(2)]
        self.time = np.zeros((2, layer_count, bins), dtype=np.uint64)
        self.heights = [np.zeros((2, layer_count, n), dtype=np.uint64) for n in view.phs_bins]
        self.at = floor
        self.maxima = maxima
        self.delay = delay
        self.extent = None
        self.filtered = 0

    def add(self, rows, direction, view):
        code = rows['direction']
        selected = rows[code < 2 if direction == 'merged' else code == DIRECTIONS.index(direction)]
        if not len(selected):
            return
        # The writer stores CF(B) - CF(A) in digitizer coordinates. Align before binning.
        dt = selected['dt'] - self.delay
        time = np.where(selected['direction'] == 1, -dt, dt) - view.zero_ps / 1000
        low, high = float(time.min()), float(time.max())
        self.extent = (low, high) if self.extent is None else (min(low, self.extent[0]), max(high, self.extent[1]))
        self.filtered += int(selected['filtered'].sum())
        truth = np.ones(len(selected), dtype=bool)
        if view.origin != 'all':
            truth &= selected['origin'] == ORIGINS.index(view.origin)
        scatter = SCATTERS[view.scatter]
        if scatter:
            truth &= (selected['scatter'] == 0 if scatter == -1 else (selected['scatter'] & scatter) != 0)
        inside = (time >= view.low_ns) & (time < view.high_ns)
        index = np.clip(np.floor((time - view.low_ns) * 1000 / view.bin_ps).astype(np.int64), 0, self.time.shape[-1] - 1)
        height_bins = [np.clip(selected['height'][:, i] * a.shape[-1] / self.maxima[i],
                               0, a.shape[-1] - 1).astype(np.int64) for i, a in enumerate(self.heights)]
        for stage, mask in enumerate((np.ones(len(selected), dtype=bool), selected['passed'])):
            cat = selected['category']
            visible = mask & inside
            np.add.at(self.time[stage, TOTAL], index[visible], 1)
            visible &= truth
            np.add.at(self.time[stage], (cat[visible], index[visible]), 1)
            layers = mask & truth
            for hist, bins in zip(self.heights, height_bins):
                np.add.at(hist[stage, TOTAL], bins[mask], 1)
                np.add.at(hist[stage], (cat[layers], bins[layers]), 1)
            # Sparse subtype histograms grow only for observed (subtype, bin) pairs.
            for panel, (bins, take, width) in enumerate(((index, visible, self.time.shape[-1]),
                    (height_bins[0], layers, self.heights[0].shape[-1]),
                    (height_bins[1], layers, self.heights[1].shape[-1]))):
                take = take & (selected['subtype'] != 0)
                packed = selected['subtype'][take].astype('int64') * width + bins[take]
                occupied, counts = np.unique(packed, return_counts=True)
                if not len(occupied):
                    continue
                ids, indices = np.divmod(occupied, width)
                edges = np.r_[0, np.flatnonzero(np.diff(ids))+1, len(ids)]
                hist = self.subhist[stage][panel]
                for start, end in zip(edges[:-1], edges[1:]):
                    counter = hist.setdefault(int(ids[start]), Counter())
                    counter.update(dict(zip(indices[start:end].tolist(), counts[start:end].tolist())))

    def result(self, view, available, names):
        selected = view.categories if view.categories is not None else (available if view.category == 'all' else [view.category])
        layers = [(key, CATEGORIES.index(key)) for key in selected if key in available] if view.individual else []

        def series(hist, subs):
            def sparse(array):
                idx = np.flatnonzero(array)
                return np.column_stack((idx, array[idx].astype(np.int64))).tolist()
            return dict(bins=sparse(hist[TOTAL]), counts=int(hist[TOTAL].sum()),
                        layers={key: sparse(hist[i]) for key, i in layers},
                        sublayers={names[i]: sorted(counter.items()) for i,counter in subs.items()})

        return dict(extent=self.extent, gated_pairs=self.filtered, stages=[
            dict(lifetime=series(self.time[s], self.subhist[s][0]),
                 phs=[series(h[s], self.subhist[s][i+1]) for i,h in enumerate(self.heights)],
                 classes={key: int(self.heights[0][s, CATEGORIES.index(key)].sum()) for key in available},
                 subclasses={names[i]:sum(counter.values()) for i,counter in self.subhist[s][1].items()})
            for s in (0, 1)])


class SpectrumJournal:
    @classmethod
    def open_archive(cls, path, metadata):
        """Rebin a committed study journal without replaying either waveform."""
        from contextlib import contextmanager

        @contextmanager
        def archive():
            with open(path, 'rb') as stream:
                if stream.seek(0, 2) != metadata['count'] * RECORD.itemsize:
                    raise ValueError('The archived spectrum journal is incomplete.')
                journal = cls.__new__(cls)
                journal.file = stream
                journal.maxima = metadata['maxima']
                journal.delays = metadata['delays']
                journal.sub_names = metadata['sub_names']
                journal.banks = OrderedDict()
                journal.read_lock = Lock()
                yield journal
        return archive()

    def __init__(self, root, header, maxima):
        self.file = open(root / 'spectrum-pairs.bin', 'w+b')
        self.count = 0
        self.isotope = (header or {}).get("isotope", "na22")
        self.sub_ids = {}
        self.sub_names = [None]  # zero means this main class has no subtypes
        self.floors = {key: 0 for key in (*DIRECTIONS, 'merged')}
        self.delays = cable_delays(header)
        self.maxima = maxima
        self.banks = OrderedDict()
        self.read_lock = Lock()

    def append(self, rows, direction, reasons, dt, channels):
        enabled = enabled_directions(channels)
        raw = direction
        if any(enabled):
            # Restore candidates rejected solely by area or rise/fall gates.
            optional = (reasons == 6) | (reasons == 7)
            recover = optional.any(axis=1) & ((reasons == 0) | optional).all(axis=1)
            if recover.any():
                heights = rows['values'][recover, :, 0]
                roles = []
                for ch, settings in enumerate(channels):
                    phs = settings['start']['phs']
                    roles.append((heights[:, ch] >= phs['low']) & (heights[:, ch] < phs['high']))
                # Each candidate already passed one of the two (non-overlapping) PHS windows per channel.
                a, b = roles
                raw = direction.copy()
                raw[recover] = np.where(a, np.where(b, -1, 0), np.where(b, 1, 2))
        take = raw >= 0
        if not take.any():
            return
        records = np.empty(int(take.sum()), dtype=RECORD)
        records['direction'] = raw[take]
        records['dt'] = dt[take]
        records['height'] = rows['values'][take, :, 0]
        signatures = np.empty((len(records),5),dtype='<u4')
        signatures[:,0] = rows['category'][take]
        signatures[:,1:] = rows['contributions'][take].reshape(-1,4)
        # Deduplicate in NumPy before resolving names; never allocate a Python string per pair.
        unique, inverse = np.unique(signatures.view('V20').ravel(), return_inverse=True)
        codes = []
        for cat, *counts in unique.view('<u4').reshape(-1,5).tolist():
            key = subtype_key(self.isotope,cat,counts)
            if key is not None and key not in self.sub_ids:
                self.sub_ids[key] = len(self.sub_names)
                self.sub_names.append(key)
            codes.append(self.sub_ids.get(key,0))
        records['subtype'] = np.asarray(codes,dtype='<u4')[inverse]
        for name in ('category', 'origin', 'scatter'):
            records[name] = rows[name][take]
        records['passed'] = direction[take] >= 0
        records['filtered'] = np.asarray(enabled)[raw[take]]
        self.file.write(records.tobytes())
        self.count += len(records)

    def capture(self):
        self.file.flush()
        return self.count, self.floors.copy()

    def query(self, capture, direction, view, available):
        end, floors = capture
        floor = floors[direction]
        key = (direction, floor, view.low_ns, view.high_ns, view.bin_ps, view.zero_ps, view.origin, view.scatter, view.phs_bins)
        delay = self.delays[1] - self.delays[0] if None not in self.delays else 0.
        # A poll reads only new records; switching bins replays compact features outside the acquisition lock.
        with self.read_lock:
            bank = self.banks.get(key)
            if bank is None or bank.at > end:
                bank = ComparisonBank(view, floor, self.maxima, delay)
            if bank.at < end:
                with open(self.file.name, 'rb') as source:
                    source.seek(bank.at * RECORD.itemsize)
                    while bank.at < end:
                        block = np.fromfile(source, dtype=RECORD, count=min(65536, end - bank.at))
                        if not len(block):
                            raise IOError('Incomplete Module 3 analysis journal.')
                        bank.add(block, direction, view)
                        bank.at += len(block)
            self.banks[key] = bank
            self.banks.move_to_end(key)
            while len(self.banks) > 4:
                self.banks.popitem(last=False)
            return bank.result(view, available, self.sub_names)
