# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Five-component DLT lifetime mixtures, with explicit finite distribution support.

First choose a specific lifetime tau, then an exponential delay with mean tau.
Lognormal UI input is median in ns (DLT/std::lognormal uses log(median)).
Unlike the original grid mapper, both endpoints have correct half-bin weights.
"""
import math
from statistics import NormalDist
import numpy as np


def lifetime_grid(component):
    kind = component.get('distribution', 'discrete')
    centre = component['tau_ns']
    if kind == 'discrete':
        return np.array([centre]), np.array([1.])
    low, high = component['lower_ns'], component['upper_ns']
    grid = np.linspace(low, high, component['grid_points'])
    edges = np.r_[low, (grid[:-1]+grid[1:])/2, high]
    width = component['spread']
    if kind == 'lorentzian':
        cdf = .5 + np.arctan((edges-centre)/width)/math.pi
    else:
        normal = NormalDist()
        z = (edges-centre)/width if kind == 'gaussian' else np.log(np.maximum(edges, 1e-300)/centre)/width
        cdf = np.array([normal.cdf(float(t)) for t in z])
    weights = np.maximum(np.diff(cdf), 0)
    if weights.sum() < 1e-10:
        raise ValueError('Lifetime distribution has no usable probability in its selected range. Adjust its limits or width.')
    # Zero is allowed as the lower support boundary, but a distributed specific
    # lifetime cannot create a spurious prompt delta through grid rounding.
    if grid[0] == 0:
        grid[0] = (grid[1]-grid[0])/4
    return grid, weights/weights.sum()


def sample_lifetimes(components, count, rng, *, discrete_taus=None):
    indices = rng.choice(len(components), count, p=[c['intensity'] for c in components])
    if discrete_taus is not None:
        # The original weighted choice of a singleton consumes one uniform for
        # every decay, including zero-lifetime components. Preserve that state.
        rng.random(count)
        return rng.exponential(discrete_taus[indices]), indices
    specific = np.empty(count)
    for i, component in enumerate(components):
        mask = indices == i
        grid, weights = lifetime_grid(component)
        specific[mask] = rng.choice(grid, int(mask.sum()), p=weights)
    return rng.exponential(specific), indices
