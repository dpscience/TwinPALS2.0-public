# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Explicit physical metadata, not a replacement for particle transport."""
from __future__ import annotations
import math
from .execution import resolve_threads

MEC2_KEV = 510.99895069


def compton_edge(energy_keV: float) -> float:
    return 2 * energy_keV**2 / (MEC2_KEV + 2 * energy_keV)


def source_profiles():
    common = [
        "Selected gamma ensemble per event; not normalized to all physical decays or activity in Bq.",
        "No primary source beta/positron transport or source-electron deposition. Secondary pair-production positrons are transported by Geant4. No electronic TTS in Module 1.",
        "Compton markers describe single scattering on a free electron; multiple scattering can deposit more energy.",
    ]
    values = [
        dict(id="na22", name="Sodium-22", label="²²Na · prompt + annihilation transport", model="selected_gamma_ensemble", half_life_years=2.6029,
             gamma_lines_keV=[511.0, 1274.537], level_half_life_ps=3.60,
             decay=dict(parent="²²Na", daughter="²²Ne", mode="β⁺ / electron capture (EC omitted in selected ensemble)",
                        levels=[dict(energy_keV=1274.577, spin="2+", label="²²Ne*"), dict(energy_keV=0, spin="0+", label="²²Ne")],
                        transitions=[dict(from_keV=1274.577,to_keV=0,energy_keV=1274.537,label="Prompt γ" )]),
             limitations=common+["511 keV pair is back-to-back at rest; material positron lifetime is deferred to Module 2, using per-primary records.", "Prompt level time is exponential with mean 5.194 ps when enabled; annihilation pair is the zero-time transport kernel, not a physical annihilation timestamp."],
             references=[dict(title="LNHB DDEP Na-22 decay data",url="https://www.lnhb.fr/nuclides/Na-22_tables.pdf"),dict(title="NNDC adopted Ne-22 levels",url="https://www.nndc.bnl.gov/ensnds/22/Ne/adopted.pdf")]),
        dict(id="co60", name="Cobalt-60", label="⁶⁰Co · correlated γ cascade", model="selected_gamma_ensemble", half_life_years=5.2711,
             gamma_lines_keV=[1173.228,1332.492], level_half_life_ps=0.735,
             decay=dict(parent="⁶⁰Co",daughter="⁶⁰Ni",mode="β⁻ · main 4+ → 2+ → 0+ cascade",
                        levels=[dict(energy_keV=2505.748,spin="4+",label="⁶⁰Ni*"),dict(energy_keV=1332.514,spin="2+",label="⁶⁰Ni*"),dict(energy_keV=0,spin="0+",label="⁶⁰Ni")],
                        transitions=[dict(from_keV=2505.748,to_keV=1332.514,energy_keV=1173.228,label="γ₁ · E2"),dict(from_keV=1332.514,to_keV=0,energy_keV=1332.492,label="γ₂ · E2")]),
             limitations=common+["Ideal unperturbed E2–E2 angular correlation p(μ)=10/21·(1+μ²/8+μ⁴/24).", "First gamma defines time zero; intermediate-level delay has mean 1.060 ps. Minor branches omitted. No material positron lifetime."],
             references=[dict(title="LNHB DDEP Co-60 decay data",url="https://www.lnhb.fr/nuclides/Co-60_tables.pdf"),dict(title="NNDC adopted Ni-60 levels",url="https://www.nndc.bnl.gov/ensnds/60/Ni/adopted.pdf"),dict(title="ORTEC Co-60 angular correlation",url="https://www.ortec-online.com/-/media/ametekortec/third-edition-experiments/19-gamma-ray-decay-scheme-angular-correlation-60co.pdf")]),
    ]
    for source in values:
        source["compton_edges_keV"] = [compton_edge(e) for e in source["gamma_lines_keV"]]
        source["level_mean_lifetime_ps"] = source["level_half_life_ps"] / math.log(2)
        source["data_revision"] = "DDEP + NNDC adopted data reviewed 2026-10-17"
    return values

