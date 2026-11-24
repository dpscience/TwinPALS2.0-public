# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Exclusive subtypes based on contributor multiplicity in physical A/B order."""
import re

ENERGIES = {"na22": (1275, 511), "co60": (1173, 1332)}
CORRELATED = {"na22": ("tc1", "tc2"), "co60": ("cascade1173_a", "cascade1332_a")}
SHARED = {"na22": ("be1275", "shared511"), "co60": ("shared1173", "shared1332")}


def pile_key(isotope, group, counts):
    return "_".join((isotope, group, *(str(n) for n in counts)))


def subtype_key(isotope, category, counts):
    a, b, c, d = counts  # role 0 and role 1 in A, then in B
    if category in (4, 5):
        group = "same" if category == 4 else "multi"
        if not (a+b and c+d and max(a+b, c+d)>1):
            return f"{isotope}_{group}_unknown"
        ordered = (b, a, d, c) if isotope == "na22" else counts
        return pile_key(isotope, group, ordered)
    role_a, role_b = int(b>0), int(d>0)
    if category == 0:
        return CORRELATED[isotope][role_a]
    if category == 2:
        return SHARED[isotope][role_a]
    if category == 3:
        e = ENERGIES[isotope]
        return f"random_{e[role_a]}_{e[role_b]}"
    return None


def migrate_overlays(keys):
    # The old energy-role overlays grouped both detector assignments.
    expanded = {}
    for iso, low, high, both in (("na22","bc511","bc1275","bc_worst"),
                                 ("co60","both1173","both1332","both_cascade")):
        for old, patterns in ((low, [(1,1,1,0),(1,0,1,1)]),
                              (high, [(1,1,0,1),(0,1,1,1)]), (both, [(1,1,1,1)])):
            expanded[old] = [pile_key(iso,"same",p) for p in patterns]
    retired = {"be511","dd511","bs511","dd_bs_s","dd_bs_d","s1275","bs1275"}
    fixed = {key for table in (CORRELATED,SHARED) for pair in table.values() for key in pair}
    fixed.update(f"random_{a}_{b}" for energies in ENERGIES.values() for a in energies for b in energies)
    result = []
    for key in keys:
        if key in retired:
            continue
        if key not in fixed and key not in expanded and not re.fullmatch(
            r"(na22|co60)_(same|multi)_(unknown|[0-9]{1,10}(?:_[0-9]{1,10}){3})", key):
            raise ValueError("Unknown spectrum subtype.")
        result.extend(expanded.get(key,[key]))
    return list(dict.fromkeys(result))
