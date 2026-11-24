# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Accepted-photoelectron provenance, independent of crystal interaction flags."""
import numpy as np

NAMES = ('none', 'scintillation', 'cherenkov', 'mixed')
LABELS = ('No pulse', 'Scintillation', 'Cherenkov', 'Mixed')

def origin_code(flags):
    return (flags >> 4) & 3

def selected(flags, origin):
    if origin not in ('all', *NAMES):
        raise ValueError('Choose all, scintillation, Cherenkov, mixed or no pulse.')
    return True if origin == 'all' else origin_code(flags) == NAMES.index(origin)

def validate(analog, flags, header):
    """Check tags against the immutable dictionary and detector summary."""
    from .streams import StreamError
    if not len(analog):
        if origin_code(int(flags)):raise StreamError('Photoelectron origin disagrees with DetectorInfo')
        return
    count=len(header.get('light_components',[]))
    codes=analog[:,4].astype(np.uint8)
    mask=int(np.bitwise_or.reduce(codes,initial=0))
    if mask != origin_code(int(flags)):
        raise StreamError('Photoelectron origin disagrees with DetectorInfo')
    if np.any(analog[:,5]>=count):
        raise StreamError('Unknown photon birth component')
    if not header['physics']['include_cherenkov'] and mask&2:
        raise StreamError('Cherenkov photons in a stream with Cherenkov disabled')

def summary(analog):
    counts=[int(np.count_nonzero(analog[:,4]==i)) for i in (1,2)]
    code=(1 if counts[0] else 0)|(2 if counts[1] else 0)
    return dict(kind=NAMES[code],scintillation=counts[0],cherenkov=counts[1])
