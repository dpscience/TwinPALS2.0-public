// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import type {AnalysisSelection} from './m1types';
export const basisHelp={
 crystal:'Crystal: selects events in this crystal, whether or not light reaches the cathode. Light origin describes photons generated inside this crystal only. Window and coupling light are not included in that origin.',
 anode:'Anode: selects only events producing an eligible anode pulse in this detector. Light origin describes QE-accepted photons, including light generated in the window or coupling. Crystal outcome remains an independent filter on the same detector.'
};
export function AnalysisBasis({selection,onChange,disabled=false}:{selection:AnalysisSelection;onChange:(fn:(s:AnalysisSelection)=>AnalysisSelection)=>void;disabled?:boolean}){
 return <nav className="analysis-basis" aria-label="Histogram population">{(['crystal','anode'] as const).map(basis=><button key={basis} role="tab" aria-selected={(selection.basis??'anode')===basis} title={basisHelp[basis]} disabled={disabled} className={(selection.basis??'anode')===basis?'active':''} onClick={()=>onChange(s=>({...s,basis,origin:'all'}))}>{basis==='crystal'?'Crystal':'Anode'}</button>)}</nav>;
}
