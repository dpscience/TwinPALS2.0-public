# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Raw, QE-accepted cathode arrival histograms for a single transport event."""
import numpy as np


def arrival_plot(arrivals, event_id, role, bins=120):
    if type(bins) is not int or not 10 <= bins <= 1000:
        raise ValueError('Choose 10–1000 bins for cathode arrival times.')
    if len(arrivals) != 2:
        raise ValueError('Both detector arrival records are required.')
    values = [np.asarray(a, dtype=float) for a in arrivals]
    if any(a.ndim != 1 or not np.isfinite(a).all() or np.any(a < -1e-9) for a in values):
        raise ValueError('Invalid cathode arrival times.')
    nonempty = [a for a in values if a.size]
    low = min(float(a.min()) for a in nonempty) if nonempty else 0.
    high = max(float(a.max()) for a in nonempty) if nonempty else 1.
    pad = max(.005, (high - low) * .03)
    edges = np.linspace(max(0., low - pad), high + pad, bins + 1)
    series = []
    summary = []
    for ch, a in enumerate(values):
        # Absorb only floating-point negatives permitted by stream validation.
        counts, _ = np.histogram(np.maximum(0., a), bins=edges)
        name = f'Detector {"AB"[ch]}'
        series.append(dict(name=name, color=('#198f8c', '#688aca')[ch], dashed=bool(ch),
            points=[[float(x), int(count)] for i, count in enumerate(counts)
                    for x in (edges[i], edges[i+1])],
            bins=[dict(low=float(edges[i]), high=float(edges[i+1]), count=int(n))
                  for i, n in enumerate(counts)]))
        summary.append(dict(detector='AB'[ch], count=int(a.size),
                            mean_ns=float(a.mean()) if a.size else None))
    return dict(title='Cathode arrival times', xLabel='Time after gamma emission (ns)',
        yLabel='Accepted photons / bin', event_id=event_id, role=role,
        series=series, summary=summary,
        markers=[dict(x=s['mean_ns'], label=f"Mean {s['detector']} · {s['mean_ns']:.3f} ns",
                      color=series[i]['color']) for i, s in enumerate(summary) if s['count']],
        explanation=dict(text='Arrival times of QE-accepted photons for the displayed event, separately for detectors A and B.\n'
            '- X starts at gamma emission. It includes gamma flight and scattering, scintillation rise/decay and optical propagation/reflections to the cathode.\n'
            '- PMT transit time, TTS, anode pulse shaping and digitizer effects are not included here.\n'
            '- Each accepted photon contributes once. Y is an absolute count per bin, without area normalization. Both detectors use the same bin edges.\n'
            '- A detector with no accepted photons has zero counts; its mean arrival time is undefined.\n'
            '- Pause and Previous/Next select the same retained event as Anode I(t). Analysis Bins controls this histogram.'))
