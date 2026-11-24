# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""A scalar-parameter cell model, sampled once per simulated run.

For physical cell i, f_i = (-1)^i a/2 + Normal(0, fixed_sigma).
Its outgoing interval is dt + f_(i+1) - f_i (cyclic). The N intervals
therefore sum to N/fs exactly. Random sample-coordinate variation is added
later, independently for every acquisition. No user curve/table is used.
"""
import numpy as np


def generate_cell_intervals(device, seed):
    if device['architecture'] == 'uniform_adc':
        return []
    n = device['default_samples']
    dt_ps = 1000 / device['default_rate']
    sigma = device['default_fixed_jitter_ps']
    alternating = np.where(np.arange(n) % 2, -1., 1.) * device['cell_alternation_ps'] / 2
    rng = np.random.default_rng(np.random.SeedSequence([int(seed), 0x43454C4C]))
    # Independent of source generation, trigger history, previews and workers.
    for _ in range(32):
        offsets = alternating + rng.normal(0, sigma, (2, n))
        widths = dt_ps + np.roll(offsets, -1, axis=1) - offsets
        if np.all(widths > 0):
            return (widths / 1000).tolist()
    raise ValueError('Fixed cell pattern contains nonpositive intervals. Reduce its jitter or alternation.')
