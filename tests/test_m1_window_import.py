# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import json
import numpy as np
import pytest

from backend import m1_import
from backend.live_analysis import AnalysisStore
from backend.streams import _header, _open_shared_read
from test_streams_v1 import event, record, frame, write, fixture_header


@pytest.mark.parametrize('role,mask', [('na22_annihilation', 6), ('co60_1332', 3)])
def test_native_import_preserves_pulses_and_trajectories_across_windows(tmp_path, monkeypatch, role, mask):
    if not m1_import.binding():
        pytest.skip('Native transport reader unavailable')
    header = fixture_header(role)
    header['physics']['minimum_energy_keV'] = 5
    path = write(tmp_path/'input.tpstream', [], header=header, done=False)
    with path.open('ab') as stream:
        for i in range(48):
            a, b = (8., i % 3, 1. if i % 3 else 0.), (2. if i % 2 else 8., 2, 2.)
            stream.write(record(event(i, a, b, mask, minimum_energy_keV=5)))
            if i % 7 == 0:
                preview = dict(role=role,event_id=i,analog_onsets_ns=[[11.]*a[1], [12.]*b[1]],tracks=[])
                stream.write(frame(b'TRAK',json.dumps(preview).encode()))
        stream.write(frame(b'DONE',json.dumps({'status':'completed','events':48}).encode()))

    # Exercise split frames, optional trajectories and independent worker ranges.
    def small_windows(source, size, start):
        source.seek(0)
        for offset in range(0, size, 4096):
            block = np.frombuffer(source.read(4096), dtype='u1')
            yield offset, block, len(block)
    monkeypatch.setattr(m1_import, 'read_windows', small_windows)
    reference, fast = AnalysisStore(), AnalysisStore()
    try:
        reference.open_files([path])
        for t in reference.threads:t.join()
        fast.register(header, path)
        actual = fast.buffers[role]
        actual.total_bytes = path.stat().st_size
        with _open_shared_read(path) as f:
            _, actual.loaded_bytes = _header(f, actual.total_bytes)
        assert m1_import.import_completed(fast, actual, 3)
        expected = reference.buffers[role]
        assert expected.verified and actual.verified
        assert actual.loaded_bytes == expected.loaded_bytes == path.stat().st_size
        assert actual.previews == expected.previews
        assert actual.outcomes() == expected.outcomes()
        np.testing.assert_array_equal(np.concatenate(actual.chunks), np.concatenate(expected.chunks))
        for a, b in zip(actual.pulses, expected.pulses):
            assert a.axis_bounds == b.axis_bounds
            assert a.events.keys() == b.events.keys()
            for i in a.events:
                for method in ('event', 'event_arrivals', 'event_origins'):
                    np.testing.assert_array_equal(getattr(a,method)(i), getattr(b,method)(i))
        for detector in 'AB':
            assert fast.persistence(dict(detector=detector,bins=20)) == reference.persistence(dict(detector=detector,bins=20))
    finally:
        fast.close()
        reference.close()
