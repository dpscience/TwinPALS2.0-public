# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Same-detector histogram populations; production is distinct from detection."""
ORIGINS = ('none', 'scintillation', 'cherenkov', 'mixed')
CRYSTAL_METRICS = frozenset(('energy', 'depth', 'polar_angle', 'azimuth', 'reflections', 'cathode_reflections'))


def selected(flags, origin='all', basis=None):
    # None is the unconditioned internal diagnostic population.
    if basis not in (None, 'crystal', 'anode'):
        raise ValueError('Choose Crystal or Anode analysis.')
    code = (flags >> (6 if basis == 'crystal' else 4)) & 3
    keep = (flags & 4) != 0
    if basis == 'anode':
        keep = keep & ((flags & 1) != 0)
    if origin != 'all':
        keep = keep & (code == ORIGINS.index(origin))
    return keep


def available(metric, basis):
    return basis != 'crystal' or metric in CRYSTAL_METRICS
