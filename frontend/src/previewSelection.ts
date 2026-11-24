// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

/** An absent response across both detectors means neither detector responded. */
export function matchesAnodePreview(masks:number[],detector:string,origin:string){
 if(origin==='all')return true;
 const names=['none','scintillation','cherenkov','mixed'];
 if(detector!=='all')return names[masks[detector==='A'?0:1]]===origin;
 return origin==='none'?masks.every(m=>m===0):masks.some(m=>names[m]===origin);
}

// Keep primary identity visible when origins share a hue family. Detector B
// remains dashed everywhere; styles never depend on series order or presence.
const origins:Record<string,[string,string]>={
 none:['#52667d','#8a7661'],
 scintillation:['#008d87','#448225'],
 cherenkov:['#bd7000','#a34524'],
 mixed:['#7750b8','#bc418a'],
};
export function originSeriesColor(primary:string,origin:string){
 const second=primary==='na22_annihilation'||primary==='co60_1332';
 return origins[origin]?.[second?1:0]??'#198f8c';
}
