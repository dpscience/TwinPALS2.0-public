// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

export type Curve = {name:string;x_unit:string;y_unit:string;semantics:string;points:[number,number][]};
export type MaterialCategory='scintillator'|'coupling'|'window'|'pmt'|'digitizer'|'wrapping'|'sample'|'foil'|'shield';
export type Entry = {id:string;revision:number;name:string;category:MaterialCategory;builtin:boolean;description:string;provenance:Record<string,unknown>;properties:Record<string,unknown>;curves:Curve[]};
export type SourceProfile = {id:string;name:string;model:string;label:string;half_life_years:number;gamma_lines_keV:number[];compton_edges_keV:number[];level_half_life_ps:number;level_mean_lifetime_ps:number;decay:{parent:string;daughter:string;mode:string;levels:{energy_keV:number;spin:string;label:string}[];transitions:{from_keV:number;to_keV:number;energy_keV:number;label:string}[]};limitations:string[];references:{title:string;url:string}[]};
export type Trajectory = {ancestry?:import('./OutcomeSummary').AncestryPreview;pulse_origins?:number[];light_origins?:[number,number][][];cherenkov_births?:{component:number;position_mm:[number,number,number]}[][];event_id:number;tracks:{particle:string;points_mm:[number,number,number][]}[]};
export type Health = {status:string;version:string;engine:{available:boolean;path:string;version:string;message:string;multithreaded?:boolean;cpu_count?:number;recommended_threads?:number};schema_version:number};
