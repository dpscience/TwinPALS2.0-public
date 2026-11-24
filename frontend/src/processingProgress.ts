// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

// Progress is based on processed records, never histogram entries (cuts can remove them).
export type StreamProgress={role:string;preview_count?:number;completed:number;total?:number;expected_events?:number;status?:string;outcomes?:{total:number}};
export function outcomeProgress(streams:StreamProgress[],planned:number){
 return 100*streams.reduce((n,s)=>n+(s.outcomes?.total??0),0)/Math.max(1,planned);
}
export function processingProgress(streams:StreamProgress[],primary='all'){
 const chosen=streams.filter(s=>primary==='all'||s.role===primary);
 return chosen.reduce((v,s)=>({processed:v.processed+(s.outcomes?.total??s.completed),total:v.total+(['cancelled','failed','stopped'].includes(s.status??'')?s.completed:(s.total??s.expected_events??s.completed))}),{processed:0,total:0});
}
